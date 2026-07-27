# P2 基础检索与 RAG 验证报告

> 验证日期：2026-07-27
> 阶段：P2 基础检索与 RAG（[[docs/plans/phases/P2-retrieval-rag|P2 计划]]）
> 前置：P1 ECL 管线 MVP（[[docs/verify/P1-verification|P1 验证报告]]）

## 总览

P2 打通了"能问能答"主链路。在 P1 落库的三层知识图谱之上，实现了三种检索模式（NativeRAG / LocalSearch / GlobalSearch）、混合检索融合（RRF）、交叉编码器重排、答案合成（来源标注）、评估 harness、L0 chunk 摘要按需补生，经 FastAPI `/query` 端点与 CLI `ask` 命令暴露。全程 `AccessContext` 越权过滤。

**测试结果：219 passed / 0 failed / 0 errors**
**Ruff：All checks passed!**

## Task 验收明细

### Task 1: 检索域抽象接口与确定性默认实现 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `SparseIndex` / `Reranker` / `Retriever` / `SearchEngine` 四抽象 | ✅ | `src/calliodesmo/interfaces/retriever.py` |
| `Candidate` / `Answer` / `SearchMode` 共享类型 | ✅ | 同上 |
| `InMemoryBM25Index` 零依赖、确定性、按 `visible_to` 过滤 | ✅ | `src/calliodesmo/retrieval/in_memory_sparse_index.py` |
| `IdentityReranker` 保序降级 | ✅ | `src/calliodesmo/retrieval/identity_reranker.py` |
| 全程经 `AccessContext` | ✅ | 17 tests passed |

测试文件：`tests/test_retrieval_interfaces.py`（17 tests）

### Task 2: 混合检索融合（RRF） ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `rrf` 基于秩融合、并集不交、确定性平局、`top_k` 截断 | ✅ | `src/calliodesmo/retrieval/fusion.py` |
| `HybridRetriever` 编排 dense+sparse | ✅ | `src/calliodesmo/retrieval/hybrid_retriever.py` |
| `native_rag` 模式可用 | ✅ | 同上 |
| 缺一路时优雅降级 | ✅ | `test_missing_sparse_index_degrades_to_dense` |
| 越权记录不出召回 | ✅ | `test_clearance_filter` / `test_scope_filter_personal` |

测试文件：`tests/test_fusion.py`（11 tests）+ `tests/test_hybrid_retriever.py`（5 tests）

### Task 3: 交叉编码器重排 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `BgeReranker` 经 FlagEmbedding 重排 | ✅ | `src/calliodesmo/retrieval/bge_reranker.py` |
| 打原文不打摘要 | ✅ | `test_rerank_feeds_content_not_summary` |
| 缺依赖友好报错 | ✅ | `test_missing_flagembedding_raises` |
| 默认 `IdentityReranker` 降级保序 | ✅ | `src/calliodesmo/retrieval/identity_reranker.py` |
| `config` 暴露重排/混合开关 | ✅ | `config.py` 新增 9 项 P2 配置 |
| `pyproject.toml` 新增 extra | ✅ | `search-rerank` / `search-bm25` / `eval-ragas` |

测试文件：`tests/test_bge_reranker.py`（9 tests）

### Task 4: 三检索模式与答案合成 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| NativeRAG（dense+sparse+rerank） | ✅ | `HybridRetriever` + `DefaultSearchEngine` |
| LocalSearch（图邻居 K 跳+rerank） | ✅ | `src/calliodesmo/retrieval/local_search.py` |
| GlobalSearch（社区摘要向量召回，摘要不进重排） | ✅ | `src/calliodesmo/retrieval/global_search.py` |
| 种子实体抽取命中图、未命中过滤 | ✅ | `src/calliodesmo/retrieval/seed_extractor.py` |
| `Answer` 标注 `source_chunk_ids` | ✅ | `src/calliodesmo/retrieval/answer_synthesizer.py` |
| 候选为空时不编造 | ✅ | `test_empty_candidates_no_fabrication` |
| 全程 `visible_to` 三模式皆不可见越权 | ✅ | `test_three_modes_all_visible_filtered` |

测试文件：`tests/test_local_search.py`（6）+ `tests/test_global_search.py`（3）+ `tests/test_answer_synthesizer.py`（6）+ `tests/test_search_engine.py`（6）= 21 tests

### Task 5: 评估 harness ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| golden Q&A 集从 YAML 加载 | ✅ | `src/calliodesmo/eval/golden.py` |
| `context_recall` 确定性 | ✅ | `src/calliodesmo/eval/metrics.py` |
| `faithfulness` / `answer_relevance` LLM-as-judge | ✅ | 同上 |
| `EvalHarness.run` 出 `EvalReport`（均值+详情） | ✅ | `src/calliodesmo/eval/harness.py` |
| 回归基线确定性 | ✅ | `test_deterministic` |
| 离线全桩可跑 | ✅ | 18 tests passed |

测试文件：`tests/test_eval_harness.py`（18 tests）
配置样例：`config/golden_qa.example.yaml`

### Task 6: L0 chunk 摘要按需补生 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| L0 chunk 短摘要按需生成（~100 token） | ✅ | `src/calliodesmo/ecl/chunk_summarizer.py` |
| 默认关，开关开时触发 | ✅ | `chunk_summary_enabled: bool = False` |
| 摘要不进稠密索引/不进 rerank | ✅ | 仅入 `metadata["summary"]` |
| 与 P1 `Chunk.summary` 预留字段对齐 | ✅ | L1 社区摘要复用 P1 既有 |

测试文件：`tests/test_chunk_summarizer.py`（5 tests）

### Task 7: API `/query` 端点与 CLI `ask` 命令 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `POST /query` 认证 + `QUERY` 权限守卫 | ✅ | `src/calliodesmo/api/app.py` |
| 三模式 + `top_k` + 来源标注 + 审计 | ✅ | 同上 |
| 非法 mode -> 400 | ✅ | `test_query_invalid_mode` |
| 缺权限 -> 403 | ✅ | `test_query_no_permission` |
| CLI `ask` 一问一答 | ✅ | `src/calliodesmo/cli.py` |
| CLI 非法 mode -> 退出码 1 | ✅ | `test_ask_invalid_mode` |

测试文件：`tests/test_query_api.py`（3）+ `tests/test_ask_cli.py`（3）= 6 tests

## 文件清单

### 新增源文件（18 个）

```
src/calliodesmo/interfaces/retriever.py          # 检索域 ABC + 共享类型
src/calliodesmo/retrieval/__init__.py             # 检索域包导出
src/calliodesmo/retrieval/in_memory_sparse_index.py  # BM25 倒排索引
src/calliodesmo/retrieval/identity_reranker.py    # 保序降级重排器
src/calliodesmo/retrieval/fusion.py               # RRF 倒数秩融合
src/calliodesmo/retrieval/hybrid_retriever.py     # 混合检索器
src/calliodesmo/retrieval/bge_reranker.py         # 交叉编码器重排
src/calliodesmo/retrieval/seed_extractor.py       # 种子实体抽取
src/calliodesmo/retrieval/local_search.py         # 图邻居 K 跳检索
src/calliodesmo/retrieval/global_search.py        # 社区摘要向量召回
src/calliodesmo/retrieval/answer_synthesizer.py   # 答案合成+来源标注
src/calliodesmo/retrieval/search_engine.py        # 默认搜索引擎编排
src/calliodesmo/eval/__init__.py                  # 评估包
src/calliodesmo/eval/golden.py                    # golden Q&A 加载
src/calliodesmo/eval/metrics.py                  # 三指标
src/calliodesmo/eval/harness.py                   # 评估 harness
src/calliodesmo/ecl/chunk_summarizer.py           # L0 chunk 摘要
config/golden_qa.example.yaml                     # golden 样例
```

### 新增测试文件（11 个）

```
tests/test_retrieval_interfaces.py    # 17 tests
tests/test_fusion.py                  # 11 tests
tests/test_hybrid_retriever.py         # 5 tests
tests/test_bge_reranker.py            # 9 tests
tests/test_local_search.py            # 6 tests
tests/test_global_search.py            # 3 tests
tests/test_answer_synthesizer.py       # 6 tests
tests/test_search_engine.py            # 6 tests
tests/test_eval_harness.py             # 18 tests
tests/test_chunk_summarizer.py         # 5 tests
tests/test_query_api.py                # 3 tests
tests/test_ask_cli.py                  # 3 tests
```

P2 新增测试：92 tests
P1 既有测试：127 tests
总计：219 tests

### 修改的既有文件

```
src/calliodesmo/config.py              # +9 项 P2 配置
src/calliodesmo/interfaces/vector_store.py  # +get_chunks_by_ids ABC 方法
src/calliodesmo/providers/in_memory_vector_store.py  # +get_chunks_by_ids 实现 + doc_id 入 metadata
src/calliodesmo/api/app.py             # +POST /query 端点
src/calliodesmo/api/schemas.py         # +QueryRequest / QueryResponse
src/calliodesmo/api/deps.py            # +get_search_engine 依赖
src/calliodesmo/cli.py                 # +ask 命令
pyproject.toml                         # +search-rerank / search-bm25 / eval-ragas extra
```

## 架构验证

### 三模式分层

- **NativeRAG**（情景层）：`HybridRetriever`（dense+sparse RRF）-> rerank -> `AnswerSynthesizer`
- **LocalSearch**（语义层）：`SeedExtractor` -> `GraphStore.neighbors` K 跳 -> chunk 归一 -> rerank
- **GlobalSearch**（摘要层）：`CommunityStore` 社区摘要向量召回 -> 成员实体 chunk 归一（不进 rerank）

### 精度约束验证

- 混合检索基于 rank 融合（RRF k=60），不按原始分数 ✅
- 重排打原文不打摘要 ✅
- 社区摘要进 LLM 上下文但不进 rerank/稠密索引 ✅
- 答案须标注来源 `[chunk_id]`，候选为空不编造 ✅
- 评估 harness 作为贯穿尺子（确定性回归基线） ✅

### 权限验证

- dense（store）/ sparse（index）/ local（graph store）/ global（community store）四路均按 `AccessContext` 过滤 ✅
- 融合/重排/合成基于已过滤结果，不再二次过滤 ✅
- 三模式跨模式检索均不可见越权 chunk ✅

## 依赖与降级策略

| 组件 | 默认实现 | 重依赖 extra | 降级方案 |
|------|---------|-------------|---------|
| 稀疏索引 | `InMemoryBM25Index`（零依赖倒排） | `search-bm25`（rank_bm25） | 自建倒排 |
| 重排 | `IdentityReranker`（保序） | `search-rerank`（FlagEmbedding） | 缺依赖友好报错 |
| 评估 | 自建轻量指标 | `eval-ragas`（ragas） | LLM-as-judge 走桩 |
| LLM | `StubLLMProvider`（离线桩） | LiteLLM（P1 已有） | sys.modules 桩 |

## 已知限制与后续

- **内存 stores 非持久**：ingest 与 query 需共享同一 store 实例（内存模式下同进程）
- **种子实体抽取为轻量**：复杂指代/歧义留 P5/P8
- **Global 社区召回依赖 P1 社区摘要质量**
- **multi-vec / ColBERT / 查询改写 / contextual retrieval** 留 P5 精化
- **ANN 向量索引（HNSW/IVF）** 留 P9（VectorStore 接口已预留）
