---
title: P5 高级 RAG 与智能检索实施计划
type: phase-plan
phase: P5
tags:
  - plan/phase
created: 2026-08-19
---
# P5 高级 RAG 与智能检索实施计划

> 介于 [[docs/plans/phases/P4.5-persistence-production|P4.5]]（已完成）与 P6（待启动）之间。P4.5 已把摄入/持久化/对齐链路收尾为生产可用，本阶段在**检索质量精化**上挣精度（项目精度原则：精度主要在检索重排与实体消解挣回）。
> **For agentic workers:** 按 Task 编号顺序执行（顺序由 [[docs/plans/roadmap|年计划]] 与「为什么是这个顺序」锁定）；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内 TDD。

> [!success] P5 闭合记录（2026-08-19）
> Task 1-5 已实现并合入（提交链 f037942/f265ea9/fdf9430 + 回退修复 ef6b643）；Task 7 golden 回归与验证报告完成（[[docs/verification/P5-verification|P5 验证]] + p5-regression.json）；**Task 6 语义切分按收益证据跳过并记录**（contextual ctx_recall 提升 0.00 < 0.05 门槛）。

## 目标与范围

在 P2 三模式检索（NativeRAG/Local/Global）与 RRF 混合融合之上，叠加**查询改写**（MultiQuery 多视角子查询 + RAGFusion 融合）、**RAGFusion/MMR**（多路候选去重 + 差异性排序）、**Corrective RAG（CRAG）**（检索质量自知：低置信 → 重写重查/声明不足）、**SelfCheck**（答案-上下文一致性自检重答）、**contextual retrieval**（块级上下文摘要向量混搜）。

**与 roadmap 边界**：ANN 向量索引与分布式规模化留 P9；评估 harness 复用 P2（不重写）。**范围外**：ColBERT / multi-vec 单 token 级（P9+）；RAG 记忆；多轮对话状态（P6 可引入）；意图判别路由（P8）；真理验证/幻觉检测（P8）。

## 顺序总览（用户锁定）

| # | Task | 承诺 | 状态 |
|---|---|---|--|
| 1 | 查询改写接口 + MultiQuery 子查询生成 | 🔁 可选 | ✅ |
| 2 | 多路融合升级：RAGFusion + MMR 去重 | ✅ 必做 | ✅ |
| 3 | contextual retrieval：块级上下文摘要向量混搜 | ✅ 必做 | ✅ |
| 4 | Corrective RAG（CRAG）：检索自知 + 重写兜底 | 🔁 可选 | ✅ |
| 5 | SelfCheck：答案-上下文一致性重答 | 🔁 可选 | ✅ |
| 6 | 语义切分（后半可选） | 🔁 暂缓 | 跳过并记录 |
| 7 | 评估回归与验证报告 | ✅ 必做 | ✅ |

**为什么是这个顺序**：检索质量先于纠错——MultiQuery/RAGFusion/contextual retrieval 在**召回/排序层**挣分（决定性、离线可测、不动 LLM）；CRAG/SelfCheck 属**答案后校验层**（依赖 LLM、成本高）。先做检索层，再在其上做自知与纠错。

## 前置条件（开工前确认）

- **P4.5 Task 1-7 已并入 main**（PR #9，2026-08-19）。
- **检索层现状**（P2 已立，全部延续）：`interfaces/retriever.py`（`SearchMode`/`Candidate`/`Retriever`/`SearchEngine`/`Reranker`/`SparseIndex`）；`retrieval/hybrid_retriever.py`（dense+sparse->RRF）；`fusion.py`（`rrf`，k=60）；`search_engine.py`；`seed_extractor.py`；`answer_synthesizer.py`；`global_search.py` / `local_search.py`。
- **评估基线**：`eval/`（`GoldenCase` + `EvalHarness`，指标 `context_recall`/`faithfulness`/`answer_relevance`）。开工前跑 baseline 存档（**基线必须存在，否则无法论证精度提升**）。

## 架构

- **Task 1**：`interfaces/rewriter.py`（`QueryRewriter` ABC）+ `MultiQueryGenerator`（LLM 生成 N 视角子查询，StubLLM 确定性 JSON 数组）+ `RewriteRouter`（开关，关=原样直通）。
- **Task 2**：`fusion.py` 新增 `rag_fusion`（多子查询 RRF）与 `mmr_dedup`（MMR λ=0.7）；`MultiQueryRetriever` 装饰器包住 `HybridRetriever`。
- **Task 3**：`ChunkRecord.summary` 存块级上下文摘要；`context_enriched_retriever.py`（原生向量 + 摘要向量加权混搜 -> RRF）；ingest 侧 `chunk_summary_enabled` 时补生成（懒加载降级）。
- **Task 4**：`corrective_rag.py`（`CorrectiveRagEngine`：检索后算置信分，低置信 -> 重写重查/声明不足）。
- **Task 5**：`selfcheck.py`（`SelfCheckEngine`：答案+上下文 -> LLM 判别 -> 低分重答 1 轮）。
- **Task 6**：可选 `SemanticChunker`（嵌入句级 -> 阈值合并），默认关闭，仅 Task 3 收益证据充分后启用。
- **API/CLI**：`/query` 走新 `SearchEngine` 编排（`factory.build_default_search_engine`）；`QueryResponse` 契约不变。

## 技术栈（现有基础上追加）

- 后端：Python 3.11+ · 复用 `interfaces/retriever.py`/`eval/` · 新 `interfaces/rewriter.py`
- 测试：`pytest`（内存 stores + StubLLM/StubEmbedding，离线可测）+ golden harness 回归

---

## Task 1: 查询改写接口 + MultiQuery 子查询生成 ✅

**目标：** 立 `QueryRewriter` 抽象 + `MultiQueryGenerator` 确定性实现（多视角子查询），为 Task 2 融合供料。

**Files:** `interfaces/rewriter.py` · `retrieval/rewrite.py`（`MultiQueryGenerator` + `RewriteRouter` + `_parse_queries`）· 测试 `tests/test_query_rewrite.py`。

- [x] **Step 1:** 写失败测试（生成/直通/委派/非法 JSON 容错）
- [x] **Step 2:** 跑测试确认失败
- [x] **Step 3:** 实现
- [x] **Step 4:** 跑测试确认通过
- [x] **Step 5:** 提交

---

## Task 2: 多路融合升级——RAGFusion + MMR 去重 ✅

**目标：** 多路候选去重 + 差异性排序，消 RRF 抱团。

**Files:** `retrieval/fusion.py`（`rag_fusion`/`mmr_dedup`）· `retrieval/multi_query_retriever.py` · 测试 `tests/test_multi_query_retriever.py` / `tests/test_fusion.py`。

- [x] **Step 1:** 写失败测试
- [x] **Step 2:** 跑测试确认失败
- [x] **Step 3:** 实现
- [x] **Step 4:** 跑测试确认通过
- [x] **Step 5:** factory 装配（可选开关 `multi_query_enabled`）
- [x] **Step 6:** 提交

> **范围如实说明（审计 #8）：** `rag_fusion` 已经 `MultiQueryRetriever` 接入运行时管线（`multi_query_enabled` 开启即生效）；`mmr_dedup` **已实现 + 单测覆盖，但尚无运行时调用点**——接入需在融合后为候选补齐嵌入向量（当前 `Candidate` 不携带向量），留待候选向量管线落地后接线（P9 或后续迭代）。跨子查询去重目前实际由 `rag_fusion`（RRF 按 `chunk_id` 合并）承担。

---

## Task 3: contextual retrieval——块级上下文摘要向量混搜 ✅

**目标：** 块级上下文摘要向量混搜，补 P2 已知限制（「multi-vec/查询改写/contextual retrieval 留 P5 精化」）。

**Files:** `retrieval/context_enriched_retriever.py` · Modify `ecl/engine.py`（ingest 侧摘要）· 测试 `tests/test_context_enriched_retriever.py`。

- [x] **Step 1:** 写失败测试
- [x] **Step 2:** 跑测试确认失败
- [x] **Step 3:** 实现
- [x] **Step 4:** 跑测试确认通过（1 passed）
- [x] **Step 5:** ingest 侧摘要
- [x] **Step 6:** 提交

---

## Task 4: Corrective RAG（CRAG）——检索自知 + 重写兜底 ✅

**目标：** 检索质量自知：低置信 -> 重写重查 1 轮 / 声明不足。

**Files:** `retrieval/corrective_rag.py` · 测试 `tests/test_corrective_rag.py`。

- [x] **Step 1:** 写失败测试（置信分/高置信直通/低置信重写重查/模式保持/factory 装配）
- [x] **Step 2:** 跑测试确认失败
- [x] **Step 3:** 实现
- [x] **Step 4:** 跑测试确认通过（2 passed）
- [x] **Step 5:** 提交

---

## Task 5: SelfCheck——答案-上下文一致性重答 ✅

**目标：** LLM judge 判别断言支撑度，低分重答 1 轮。

**Files:** `retrieval/selfcheck.py` · 测试 `tests/test_selfcheck.py`。

- [x] **Step 1:** 写失败测试（高一致不重答/低一致重答 1 轮/解析失败回退/空答案重答/factory 装配）
- [x] **Step 2:** 跑测试确认失败
- [x] **Step 3:** 实现
- [x] **Step 4:** 跑测试确认通过（2 passed）
- [x] **Step 5:** 提交

---

## Task 6: 语义切分（暂缓，前置收益证据）⏸ 跳过并记录

> **结论：跳过**（2026-08-19，Step 0 纪律）。启动门槛为「contextual retrieval 的 harness `context_recall` 提升 ≥ 0.05」；实测提升 = 0.00 < 0.05（且 v1 实现本身是模拟混搜，无独立摘要向量），不满足启动条件。等待：①contextual v2（独立向量列，P9）落地；②真实模型 golden 回归证据。

- [x] **Step 0:** 完成 Task 3 后依据 harness 对比判断是否启动本 Task（不达标则跳过并记录）。

---

## Task 7: 评估回归 + 验证报告（贯穿 + 收尾） ✅

- [x] **Step 1:** 每次检索层改动后跑 `tests/test_eval_harness.py` + 在 [[docs/verification/P5-verification|P5 验证]] 记录当次 golden 均值，与 baseline 对比。
- [x] **Step 2:** 写 P5 验证报告（Task 闭合矩阵 + baseline vs 各配置对比 + 关键发现 + 边界与后续）并同步 [[docs/verification/README|验证索引]]。
- [x] **Step 3:** 收尾提交。

---

## 依赖与风险

- MultiQuery 空生成缺陷：子查询生成失败/非法时**空召回**（ctx_recall 0.00）——已修（`RewriteRouter` 空生成回退原查询，提交 ef6b643），修复后恢复 baseline 0.4444。
- contextual v1 为「查询向量缩放」模拟：归一化余弦向量库中缩放不改变排序 -> 与 baseline 持平；真实收益需独立摘要向量列（留 P9）。
- **`mmr_dedup` 运行时接线缺口（审计 #8，如实披露）**：已实现 + 单测，但无运行时调用点——接入需候选向量管线（`Candidate` 不携带向量），留后续；跨子查询去重实际由 `rag_fusion`（RRF 按 chunk_id 合并）承担。
- CRAG/SelfCheck 属答案后校验层，离线桩 judge 恒定分数下无区分度；真实触发率需真实 LLM 度量（`scripts/eval_p5.py --real`）。
- 语义切分按证据跳过（见 Task 6）。

### 真实语料集成测试产出（2026-08-29，Y:/资料 三份多密级语料 × 多用户）

- **缺陷修复 1**：`/ingest` 临时文件名丢失密级前缀 -> 上传文档密级全回落 INTERNAL——已修（临时文件保留前缀，`b1209ba` + 回归测试）。
- **缺陷修复 2**：远端重排（8083）对大语料内容偶发 500 击穿整个查询——`HttpReranker` 已加降级保序（上游失败退回原召回顺序，`3945f8b` + 2 测试）。
- **权限断言 13/13**：密级维度 7（同一所有权两密级按本人 clearance 过滤）+ 跨用户 owner 隔离 + 无权限 403 / 未认证 401。
- 已知边界：hash 嵌入无语义，跨语言（中问英档）召回近零；内存图库按实体名单一键，个人/项目同名实体互覆（真后端按 `(name,scope,owner)` 键控，不受影响）。

## 节奏建议（学生 10-15h/周）

W33-W36（2026-08-19 完成）：Task 1-2 检索融合层 -> Task 3 contextual -> Task 4/5 纠错层 -> Task 7 回归收尾。
