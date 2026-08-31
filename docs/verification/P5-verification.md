---
title: P5 高级 RAG 验证报告
type: verification-report
tags:
  - verification
created: 2026-08-19
---

# P5 高级 RAG 验证报告（2026-08-19）

> 关联：[[docs/plans/phases/P5-advanced-rag|P5 阶段计划]]

## 测试内容

### 检索层新用例（32，全部离线确定性）

| 文件 | 验证点 | 数量 |
| --- | --- | --- |
| `test_query_rewrite.py` | MultiQuery 生成/开关直通/非法 JSON 容错/**空生成回退原查询** | 5 |
| `test_multi_query_retriever.py` | RAGFusion 跨子查询融合 / MMR 去重 / 装饰器扇出 | 3+ |
| `test_context_enriched_retriever.py` | 两路召回 + RRF / **factory 装配** | 3 |
| `test_corrective_rag.py` | 置信分/高置信直通/低置信重写重查/**factory 装配** | 5 |
| `test_selfcheck.py` | 高一致不重答/低一致重答 1 轮/**factory 装配** | 5 |
| `test_fusion.py` | rrf 既有 + rag_fusion / mmr_dedup | 既有+新增 |
| **合计** | | **32** |

### golden 回归（9 例 × 6 配置）

`config/golden_qa.yaml` 基于 `data/demo` 三份真实语料，`relevant_chunk_ids` 为真实 chunk id，覆盖三模式。`uv run python scripts/eval_p5.py`（StubLLM + Hash 64 维 + 内存 stores，确定性）：

| config | ctx_recall | faithfulness | answer_relevance |
| --- | --- | --- | --- |
| baseline | **0.4444** | 0.4444 | 1.0000 |
| multi_query / contextual / crag / selfcheck / all | 0.4444（持平） | 0.4444 | 1.0000 |

## 技术栈

- 改写层 `interfaces/rewriter.py` + `MultiQueryGenerator`（容错解析）+ `RewriteRouter`（开关 + 空生成回退）· 融合层 `rag_fusion`/`mmr_dedup` + `MultiQueryRetriever` 装饰器 · contextual `context_enriched_retriever.py` · 校验层 `corrective_rag.py`/`selfcheck.py` · 评估复用 `eval/` 不重写，`scripts/eval_p5.py` 一键回归（`--real` 切真实模型）。

## 验证原理

- **确定性离线**：StubLLM + Hash + 内存 stores，零网络；`context_recall` 为硬指标。
- **契约优先**：新检索器全实现 ABC，`/query` 契约不变。
- **装配即验证**：`build_default_search_engine` 各开关均有装配测试（修复 Task 3 历史死代码问题）。
- **golden 真实 id**：chunk_id 取真实 ingest 产物，非伪造。

## 验证过程

1. Task 3 装配收尾（修复 `ContextEnrichedRetriever` 死代码，`f037942`）→ 2. Task 4 CRAG（`f265ea9`）→ 3. Task 5 SelfCheck（`fdf9430`）→ 4. MultiQuery 空生成回退修复（`ef6b643`，0.00→0.4444）→ 5. golden 回归全跑 → 6. `pytest -m "not db"` 全绿。

## 关键发现

- **baseline ctx_recall 0.4444**（9 例中 4 例召回相关，BM25/hash 在 3 文档小语料的确定性基线）。
- **MultiQuery 空生成缺陷已修**：改动前开启→空候选（0.4444→0.00）；回退后恢复；真实模型同样受保护。
- **contextual v1 为「查询向量缩放」模拟**：归一化余弦向量库中缩放不改变排序→与 baseline 持平；真实收益需**独立摘要向量列**（`CommunityRecord.summary_embedding` 同款，留 P9）。
- **CRAG/SelfCheck 属答案后校验层**：桩 judge 恒分下无区分度，真实触发率需真实 LLM。
- **answer_relevance=1.0 无区分度**：桩 judge 恒输出所致；离线回归只承诺 `context_recall`，真实模型跑 `--real`。

## Task 6 决策（语义切分）

> **结论：跳过并记录**（Step 0 纪律）。启动门槛 = contextual `context_recall` 提升 ≥0.05；实测 0.00 < 0.05（且 v1 为模拟混搜）→ 不满足。等待：①contextual v2（独立向量列，P9）；②真实模型 golden 证据。

## 已知边界与后续

- 本回归为**离线桩证据**（hash 无语义、judge 恒分）；真实模型在验证环境不可达（沙箱无外网），留 `scripts/eval_p5.py --real` 用户本机补跑。
- multi_query/crag/selfcheck 真实触发率与收益、contextual 真实召回增益需真实模型证据；`.env.example` 已完整接线。
- P9 承接：contextual v2、ANN 索引、CRAG LLM 决策路由、SelfCheck→P8。

## 证据

`p5-regression.json`（6 配置 × 9 例完整数据）· `scripts/eval_p5.py`（可复现）· `config/golden_qa.yaml` · 提交链 `f037942`→`f265ea9`→`fdf9430`→`ef6b643`。
