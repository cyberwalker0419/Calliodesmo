# P2 基础检索与 RAG 验证报告

> 验证日期：2026-07-27
> 阶段：P2 基础检索与 RAG（[[docs/plans/phases/P2-retrieval-rag|P2 计划]]）· 前置：[[docs/verification/P1-verification|P1 验证报告]]

## 总览

P2 打通「能问能答」主链路：三种检索模式（NativeRAG / LocalSearch / GlobalSearch）、混合检索融合（RRF）、交叉编码器重排、答案合成（来源标注）、评估 harness、L0 chunk 摘要按需补生，经 FastAPI `/query` 与 CLI `ask` 暴露，全程 `AccessContext` 越权过滤。

**测试结果：219 passed / 0 failed**（P1 127 + P2 新增 92）· **Ruff：All checks passed!**

## Task 验收明细（全部 ✅）

| Task | 验收要点 | 测试 |
|------|---------|------|
| 1 检索域抽象 | `SparseIndex/Reranker/Retriever/SearchEngine` 四 ABC + `Candidate/Answer/SearchMode`；`InMemoryBM25Index` 零依赖确定性、`visible_to` 过滤；`IdentityReranker` 保序 | `test_retrieval_interfaces.py`(17) |
| 2 RRF 融合 | `rrf` 按秩融合并集不交；`HybridRetriever` dense+sparse；缺路降级；越权不出召回 | `test_fusion.py`(11) + `hybrid_retriever.py`(5) |
| 3 交叉编码器重排 | `BgeReranker`（FlagEmbedding）打原文不打摘要；缺依赖友好报错；默认 Identity 降级；+9 配置 +3 extra | `test_bge_reranker.py`(9) |
| 4 三模式+合成 | Native/Local(图邻居 K 跳)/Global(社区摘要向量，不进重排)；种子抽取；`Answer` 标来源；空候选不编造；三模式皆过滤越权 | `test_local/global/answer_synthesizer/search_engine.py`(21) |
| 5 评估 harness | golden YAML 加载；`context_recall` 确定性；faithfulness/relevance LLM-as-judge；`EvalReport`；离线全桩 | `test_eval_harness.py`(18) |
| 6 L0 chunk 摘要 | 按需补生（~100 token）默认关；摘要不进稠密索引/rerank | `test_chunk_summarizer.py`(5) |
| 7 `/query`+CLI | 认证+`QUERY` 守卫；三模式+top_k+来源+审计；非法 mode 400/CLI 退出码 1 | `test_query_api.py`(3) + `ask_cli.py`(3) |

**涉及文件**：新增 `interfaces/retriever.py` + `retrieval/`(8 文件) + `eval/`(4) + `ecl/chunk_summarizer.py` + `config/golden_qa.example.yaml`；修改 `config.py`(+9)/`vector_store.py`(+get_chunks_by_ids)/`api/app.py`、`schemas.py`、`deps.py`/`cli.py`/`pyproject.toml`(+3 extra)。

## 架构验证

- **三模式分层**：NativeRAG（情景层 dense+sparse->RRF->rerank）· LocalSearch（语义层 SeedExtractor->图 K 跳->归一->rerank）· GlobalSearch（摘要层社区向量召回->成员 chunk 归一，不进 rerank）。
- **精度约束**：RRF 按秩（k=60）；重排打原文不打摘要；社区摘要进 LLM 上下文但不进 rerank/稠密索引；空候选不编造。
- **权限**：dense/sparse/local/global 四路均按 `AccessContext` 过滤；融合重排合成基于已过滤结果。

## 依赖与降级策略

| 组件 | 默认实现 | 重依赖 extra | 降级 |
|------|---------|-------------|------|
| 稀疏索引 | `InMemoryBM25Index`（零依赖） | `search-bm25` | 自建倒排 |
| 重排 | `IdentityReranker`（保序） | `search-rerank`（FlagEmbedding） | 缺依赖友好报错 |
| 评估 | 自建轻量指标 | `eval-ragas` | LLM-as-judge 走桩 |
| LLM | `StubLLMProvider`（离线桩） | LiteLLM（P1 已有） | `sys.modules` 桩 |

## 验证原理

- **离线确定性**：内存 stores + Hash 嵌入 + StubLLM，零网络；`context_recall` 数学化断言（id 交集）。
- **契约优先**：新检索器全部实现 ABC，`/query` 响应契约稳定。
- **TDD + checkbox 跟踪**（见 P2 计划）。

## 验证过程

```bash
uv sync && uv run ruff check . && uv run pytest -q   # 219 passed
```

## 已知限制与后续

- **内存 stores 非持久**：ingest 与 query 需共享 store 实例（同进程）。
- **种子实体抽取为轻量**：复杂指代留 P5/P8。
- **Global 召回依赖 P1 社区摘要质量**。
- **multi-vec / ColBERT / 查询改写 / contextual retrieval** 留 P5（已落地）。
- **ANN 索引（HNSW/IVF）** 留 P9。
