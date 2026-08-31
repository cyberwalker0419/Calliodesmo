---
title: P2 基础检索与 RAG 实施计划
type: phase-plan
phase: P2
tags:
  - plan/phase
created: 2026-07-27
---
# P2 基础检索与 RAG 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/phases/P1-ecl-pipeline|P1]] / [[docs/plans/phases/P3-web-ui|P3]]。

**Goal:** 打通"能问能答"主链路：三种检索模式（**NativeRAG** 向量+稀疏混合查情景层原文块 / **LocalSearch** 图邻居查语义层子图 / **GlobalSearch** 社区摘要查摘要层主题），全程按 `AccessContext` 过滤；混合检索稠密∪稀疏∪图三路 `RRF` 融合 + 交叉编码器重排，答案经 `LLMProvider` 合成并标注来源。FastAPI `/query` + CLI `ask` 暴露 Q&A。精度精化（multi-vec/ColBERT、contextual retrieval、查询改写）推迟 P5。

**Architecture:** 检索域新增 `SparseIndex`/`Reranker`/`Retriever`/`SearchEngine` 四抽象，与 P1 三 store 同构，均接收 `AccessContext` 复用 `visible_to` 过滤。默认实现确定性、零重依赖、离线可测（内存 BM25、`IdentityReranker` 保序降级，bge-reranker-v2-m3 列 extra）。检索引擎按 `SearchMode` 编排：多路召回 -> `RRF` -> 重排 -> `AnswerSynthesizer`（LLM + 来源标注）。**评估 harness（golden 集 + 忠实度/上下文召回/答案相关性）自本阶段建立并贯穿回归**——"精度由数据判定，不靠猜"。

**Tech Stack（P1 基础上追加）:**
- 融合：自建 `RRF` 倒数秩融合（零依赖）；稀疏：内存 BM25 倒排（默认零依赖），`rank_bm25` 列 extra `search-bm25`
- 重排：`bge-reranker-v2-m3`（extra `search-rerank`，与 `embedding-local` 同 FlagEmbedding 族），默认 `IdentityReranker` 降级
- 合成与评估：复用 `LLMProvider`（LiteLLM，离线桩）；自建轻量指标，`ragas` 列 extra `eval-ragas`
- 测试：`pytest` + 内存 stores + `HashEmbeddingProvider` + 桩 LLM/reranker

---

### Task 1: 检索域抽象接口与确定性默认实现

**目标：** 立 `SparseIndex`/`Reranker`/`Retriever`/`SearchEngine` 四抽象（路线图检索域扩展），与 P1 三 store 同构，全程接收 `AccessContext` 复用 `visible_to` 过滤；默认实现确定性、零重依赖、离线可测，pgvector/Neo4j 真后端与 bge 重模型列 extra（不阻塞验收）。

> [!note] `Candidate`/`Answer`/`SearchMode` 为 P2 全局共享类型（Task 2-7 引用）；`Candidate` 统一承载多路召回（向量/稀疏/图同型），图/社区召回最终归一到关联 chunk（`source` 标注原路），使三路同一口径 RRF 融合、重排与来源标注。

**Files:**
- `src/calliodesmo/interfaces/retriever.py`（四 ABC + `Answer` dataclass）· `retrieval/{__init__,in_memory_sparse_index,identity_reranker}.py` · `stores/__init__.py`（补导出）· 测试 `tests/test_retrieval_interfaces.py`

- [x] **Step 1:** `Candidate`/`Answer`/`SearchMode` 数据模型（字段齐全、默认值、三值）测试 -> 实现跑绿
- [x] **Step 2:** `InMemoryBM25Index` 建 token 倒排（小写化 + 简单分词，中英兼容：英文空白/标点、中文按字 + bigram 兜底）；search 按 BM25 分降序出 `Candidate`（`source="sparse"`、1-based `rank`）；空索引返空测试 -> 实现跑绿
- [x] **Step 3:** `InMemoryBM25Index` 按 `visible_to` 过滤（越权 chunk 不进索引、不出召回）测试 -> 实现跑绿
- [x] **Step 4:** `IdentityReranker` 保序（rank 重置 1..n、score 不变）、`top_k` 截断测试 -> 实现跑绿
- [x] **Step 5:** 四接口 ABC 不可直接实例化（`abstractmethod` 生效）、子类需实现全部方法测试 -> 实现跑绿

**验收：**
- 四抽象 + 三共享类型齐全；`InMemoryBM25Index` 零依赖确定性、按 `visible_to` 过滤；`IdentityReranker` 保序降级

### Task 2: 混合检索融合（稠密 ∪ 稀疏 ∪ 图，RRF）

**目标：** `HybridRetriever`（native_rag）：稠密（`VectorStore`+`EmbeddingProvider`）∪ 稀疏（`InMemoryBM25Index`）两路召回 -> **RRF 融合** -> 重排前 top-N。融合按 `rank` 而非原始分（量纲不同），公式 `score = Σ 1/(k+rank_i)`、`k=60`，全程 `AccessContext` 过滤。图召回独立成路在 Task 4。

> [!note] RRF 用秩不用分数：向量余弦（0-1）与 BM25（无界）量纲不同，按秩融合更稳健（GraphRAG/BEIR 实践一致）。

**Files:**
- `src/calliodesmo/retrieval/{fusion,hybrid_retriever}.py`（`rrf` + `HybridRetriever`）+ `__init__.py` 导出 · 测试 `tests/test_fusion.py`、`tests/test_hybrid_retriever.py`

- [x] **Step 1:** `rrf` 单路退化为按原秩排序、双路同 chunk 合并（分数相加）、平局按 `chunk_id` 确定性排序、`top_k` 截断测试 -> 实现跑绿
- [x] **Step 2:** 稀疏命中稠密未命中（或反之）的 chunk 仍保留（并集不交）测试 -> 实现跑绿
- [x] **Step 3:** `HybridRetriever` 编排：embed -> dense + sparse -> 赋 rank -> rrf -> 融合候选（`source` 标每候选主导来源）测试 -> 实现跑绿
- [x] **Step 4:** 全程 `visible_to` 过滤（dense 由 store、sparse 由 index 过滤，融合后不二次过滤）测试 -> 实现跑绿
- [x] **Step 5:** 缺 sparse index（注入 `None`）仅走 dense 不报错（容错）测试 -> 实现跑绿

**验收：**
- rrf 基于秩、并集不交、确定性平局、`top_k` 截断；`HybridRetriever` 编排 dense+sparse，越权不出召回，缺一路优雅降级

### Task 3: 交叉编码器重排（bge-reranker-v2-m3，打原文不打摘要）

**目标：** `BgeReranker`（`bge-reranker-v2-m3`，与 BGE-M3 同 FlagEmbedding 族，extra `search-rerank`）。重排**打原文**（`Candidate.content` = chunk 原文）**不打社区摘要**（摘要无事实细节）；缺依赖友好报错（提示 `uv sync --extra search-rerank`），默认 `IdentityReranker` 降级。

> [!note] "向量与 rerank 均打原文不打摘要"是路线图精度约束：社区/实体摘要供 GlobalSearch 主题召回与 LLM 上下文，但不进稠密索引、不进 rerank 打分。

**Files:**
- `src/calliodesmo/retrieval/bge_reranker.py` · `pyproject.toml`（extra `search-rerank`/`search-bm25`）· `config.py`（`reranker_model`/`rerank_top_n`/`hybrid_enabled`/`sparse_enabled`）· 测试 `tests/test_bge_reranker.py`（桩 FlagEmbedding，零真实模型）

- [x] **Step 1:** `BgeReranker` 对 `(query, content)` 打分、按分降序、`top_k` 截断、`rank` 重置、`score` 更新为重排分测试 -> 实现跑绿
- [x] **Step 2:** 打原文约束：断言喂 reranker 的是 `Candidate.content`（chunk 原文）、不喂社区/实体摘要测试 -> 实现跑绿
- [x] **Step 3:** 缺依赖友好报错（卸载 FlagEmbedding -> `RuntimeError` 提示重排需 `uv sync --extra search-rerank`）测试 -> 实现跑绿
- [x] **Step 4:** config 新增项默认值与环境覆盖测试 -> 实现跑绿
- [x] **Step 5:** 重排串联：`HybridRetriever` 召回 -> `Reranker.rerank`（默认 `IdentityReranker`，可注入 `BgeReranker`）-> top_k；缺注入退化保序测试 -> 实现跑绿

**验收：**
- bge 重排打原文不打摘要、`top_k` 截断与分更新；缺依赖友好报错；config 暴露重排/混合开关，离线全桩测试

### Task 4: 三检索模式与答案合成（NativeRAG / Local / Global）

**目标：** 三模式对应三层知识图谱访问面：**NativeRAG**（情景层：`HybridRetriever` dense+sparse RRF -> rerank，查原文块）、**LocalSearch**（语义层：query 种子实体沿 `GraphStore.neighbors` K 跳扩子图、归一到关联 chunk -> rerank）、**GlobalSearch**（摘要层：`CommunityStore.list_communities` 按社区摘要向量召回，成员实体归一 chunk；摘要进 LLM 上下文但**不进重排/稠密索引**）。统一交 `AnswerSynthesizer`（`LLMProvider`）生成带来源标注的 `Answer`。

**Files:**
- `src/calliodesmo/retrieval/{local_search,global_search,seed_extractor,answer_synthesizer,search_engine}.py` · `config.py`（`local_search_hops`=1 / `global_top_communities`=10）· 测试 `tests/test_{local_search,global_search,answer_synthesizer,search_engine}.py`

- [x] **Step 1:** `SeedExtractor` 从 query 抽种子实体名（桩 LLM）；命中 `GraphStore.get_entity` 为有效种子、未命中过滤测试 -> 实现跑绿
- [x] **Step 2:** `LocalSearchRetriever` K 跳扩展（默认 1）：沿 neighbors 收集实体+关系 -> 沿 `source_chunk_ids` 归一 chunk 去重；越权邻居被 store 过滤不可见测试 -> 实现跑绿
- [x] **Step 3:** `GlobalSearchRetriever`：list_communities（已按 `visible_to` 过滤）-> query 向量对社区摘要标题+文本余弦召回 -> top-N -> 成员实体归一 chunk 测试 -> 实现跑绿
- [x] **Step 4:** Global 摘要进 LLM 上下文但**不进 rerank、不进稠密索引**（断言 reranker 仅 Local/Native 通路被调）测试 -> 实现跑绿
- [x] **Step 5:** `AnswerSynthesizer` prompt 含来源标注与忠实度约束；桩 LLM 返带 `[chunk_id]` 标注 -> 解析 `source_chunk_ids`；候选为空返"无可引用证据"不编造测试 -> 实现跑绿
- [x] **Step 6:** `DefaultSearchEngine` 按 `SearchMode` 分派（native->Hybrid、local->Local、global->Global）-> rerank（仅 Local/Native）-> 合成 -> `Answer`（mode/source_chunk_ids/context_chunks）端到端测试 -> 实现跑绿
- [x] **Step 7:** 三模式全程 `visible_to`：低 clearance 跨模式检索均不可见越权 chunk（mixed-access 语料）测试 -> 实现跑绿

**验收：**
- 三模式可用；种子抽取命中过滤；`Answer` 标注 `source_chunk_ids`、候选空不编造；越权三模式皆不可见

### Task 5: 评估 harness（golden 集 + RAGAS 式指标回归）

**目标：** 建**贯穿项评估 harness**（"精度由数据判定"的核心尺子）：维护 golden Q&A 集（问题 + 标准答案 + 相关 chunk_id），指标含**上下文召回**（相关 chunk 是否被召回）、**忠实度**（答案由召回上下文支撑，LLM-as-judge）、**答案相关性**（是否切题）。自建轻量指标（judge 走桩），`ragas` 列 extra `eval-ragas`；golden 起步 ~10-20 条随用随扩，每次检索改动跑回归对照。

> [!note] 评估 harness 是 P1/P2 起的贯穿项：没有尺子不知检索改动好坏。P1 以功能测试+离线桩为主，质量评测自本 Task 接入，后续每个检索改动（hybrid 开关、rerank 模型、k 值）跑回归对照基线。

**Files:**
- `src/calliodesmo/eval/{__init__,golden,metrics,harness}.py` · `config/golden_qa.example.yaml` · `config.py`（`eval_golden_file`）· 测试 `tests/test_eval_harness.py`

- [x] **Step 1:** `GoldenCase` 数据模型 + YAML 加载（问题/标准答案/相关 chunk_id/模式）；空文件 -> 空集测试 -> 实现跑绿
- [x] **Step 2:** `context_recall` 确定性计算（相关 chunk 占比；无相关 -> 0；全召回 -> 1）测试 -> 实现跑绿
- [x] **Step 3:** `faithfulness`/`answer_relevance` LLM-as-judge（桩 LLM 返 0-1；非法返 -> 0 且不抛）测试 -> 实现跑绿
- [x] **Step 4:** `EvalHarness.run`：每 case 跑 `engine.query` -> `source_chunk_ids` 算 recall、`text` 算其余 -> 汇总均值 + 每条详情 `EvalReport` 测试 -> 实现跑绿
- [x] **Step 5:** 回归断言：固定语料 + 桩 LLM/reranker，harness 输出确定性（可作回归基线）测试 -> 实现跑绿

**验收：**
- golden 集 YAML 加载；recall 确定性、其余 LLM-as-judge；`EvalHarness.run` 出 `EvalReport`（均值+详情）离线全桩可跑；基线确定性，可对照改动前后是否退化

### Task 6: L0/L1 分层摘要按需补生（Chunk.summary）

**目标：** P1 仅在 `Chunk.summary` 预留字段（填 None）。本 Task **按需补生** L0 短摘要（~100 token）：ingest 时为每个 chunk 生成供展示与粗筛；L1 社区摘要 P1 已有。补生经 `LLMProvider`，**摘要不进稠密索引/不进 rerank 打分**。

> [!note] 取 OpenViking 三层理念（非目录递归）：L0=chunk 短摘要（本 Task）、L1=社区摘要（P1 已有）、L2=全库主题（P6）；P1 预留 `Chunk.summary=None` 即本 Task 接入点。

**Files:**
- `src/calliodesmo/ecl/chunk_summarizer.py`（`LLMChunkSummarizer`）· `ecl/load.py`（写 `metadata["summary"]`）· `ecl/engine.py`（开关 `chunk_summary_enabled` 默认 false）· `config.py` · 测试 `tests/test_chunk_summarizer.py`

- [x] **Step 1:** `LLMChunkSummarizer` 桩 LLM 生成 ~100 token 摘要；空/超短 chunk 返原文截断测试 -> 实现跑绿
- [x] **Step 2:** 摘要不进稠密索引：`LoadService` 写 `ChunkRecord` 时 content 仍为原文、摘要入 `metadata["summary"]`，断言 VectorStore 收到的 content 不被替换测试 -> 实现跑绿
- [x] **Step 3:** 开关默认关：False 时 engine 不调 LLM、summary 缺省；开启时按需生测试 -> 实现跑绿
- [x] **Step 4:** 展示层消费：`Candidate` 召回后携带 `metadata["summary"]` 供 UI 列表预览（native_rag 断言候选含摘要）测试 -> 实现跑绿

**验收：**
- L0 摘要按需生成（~100 token）默认关、开时 ingest 触发；摘要仅入 `metadata["summary"]` 供展示与粗筛；与 P1 预留字段对齐、L1 复用 P1 既有

### Task 7: API `/query` 端点与 CLI `ask` 命令

**目标：** 把检索能力经 FastAPI `POST /query` + Typer `ask` 暴露，支持 `mode` 选择与 `top_k` 调参，返回带来源标注的 `Answer`，全程 `AccessContext` 过滤（需 `query` 权限）并记审计。

**Files:**
- `src/calliodesmo/api/{app,schemas,deps}.py` · `cli.py`（`ask` 命令）· `config.py`（`default_search_mode`）· 测试 `tests/test_query_api.py`、`tests/test_ask_cli.py`

- [x] **Step 1:** `POST /query`：认证 + `Permission.QUERY` 守卫（缺权限 403）；桩 SearchEngine 返固定 Answer -> QueryResponse；来源标注透传测试 -> 实现跑绿
- [x] **Step 2:** 三模式参数路由（非法值 400）；`top_k` 边界（<=0 -> 422）测试 -> 实现跑绿
- [x] **Step 3:** 审计：记 `action="query"`、`detail={mode, sources_count}`、`source="api"` 测试 -> 实现跑绿
- [x] **Step 4:** CLI `ask <question> [--mode] [--top-k]`：构造默认引擎（内存 stores + `HashEmbeddingProvider` + `IdentityReranker` + 桩 LLM）-> 打印答案+来源 chunk_id；`CliRunner` 退出码 0 测试 -> 实现跑绿
- [x] **Step 5:** CLI 失败友好报错（无 query 权限提示；LLM 缺 key 指引 `CALLIODESMO_LLM_API_KEY`）测试 -> 实现跑绿
- [x] **Step 6:** 端到端（离线）：ingest 样例 -> `/query` native_rag 召回相关 chunk + 答案标注来源；低 clearance 不可见越权 chunk 测试 -> 实现跑绿

**验收：**
- `/query` 认证 + 权限守卫 + 三模式 + `top_k` + 来源标注 + 审计；CLI `ask` 一问一答打印来源；离线端到端越权不可见

---

## 精度策略与跨阶段改进（前瞻）

> [!note] 延续 P1 精度杠杆排序，本阶段落地"检索精度"第一杠杆的过门槛部分，更重的留 P5；评估 harness 自本阶段起为贯穿尺子；全部经可插拔接口接入，不动核心。

**本阶段落地的精度投资：**
1. **评估 harness（贯穿项，最大缺口）**——golden 集 + 三指标回归，每次检索改动对照基线（从 0 到 1 建立，是后续一切精度判断的前提）
2. **混合检索（第一杠杆，过门槛）**——dense+sparse RRF 融合 + 交叉编码器重排；打原文不打摘要（判别力约束）
3. **来源标注 + 忠实度约束**——答案须由召回上下文支撑，候选空不编造（prompt + `faithfulness` 双重把关）
4. **三模式分层**——Native/Local/Global 对应情景/语义/摘要三层，避免"一把向量查全部"的粒度错配

**留待后续阶段（不阻塞 P2 验收）：**
- P5 精化：multi-vec/ColBERT（BGE-M3 第三输出）、查询改写（MultiQuery/RAGFusion/SubQuestion/CRAG/Adaptive）、分层切分 + 上下文富化（contextual retrieval）
- ANN 向量索引（HNSW/IVF）支撑 ≥50 万文档：P9（`VectorStore` 接口已预留）
- 跨文档交叉验证 / 低接地声明幻觉标记：P8 证据验证硬化
- 图召回的实体链接精度（query 种子 NER/消歧）：P2 轻量过门槛，P5/P8 精化

**依赖与风险（P2 全量）：**
- 重排真模型 `bge-reranker-v2-m3` 列 extra `search-rerank`（同 FlagEmbedding 族）；稀疏默认 `InMemoryBM25Index`（零依赖），`rank_bm25` 列 extra `search-bm25`；CI 默认 Identity 降级 + 桩测，真机 `uv sync --extra search-rerank`
- 评估 LLM-as-judge 真实运行需 key；离线全 `sys.modules` 桩（沿用 P0/P1）；`ragas` 列 extra `eval-ragas`
- 检索全程 `visible_to`：dense/sparse/local/global 四路均按 `AccessContext` 过滤；融合/重排/合成基于已过滤结果不二次过滤（避免漏召回）
- 版本钉制：新增依赖与 litellm `>=1.85,<1.91`、FlagEmbedding 协调，避免传递依赖冲突（Windows 无 wheel 风险）
- 精度边界（如实声明）：Local 种子抽取 P2 轻量模板/LLM 过门槛，复杂指代/歧义留 P5/P8；Global 依赖 P1 社区摘要质量，社区越粗召回越泛
- 内存 stores 非持久：默认内存实现保证离线可测与 CI 可跑；pgvector/Neo4j 真后端列 extra（与 P1 同策略）；ingest 与 query 需共享同一 store 实例（同进程），跨进程持久化随真后端接入

> 精简于 2026-08（文档重构）：删除嵌入代码块，保留任务/勾选结构。
