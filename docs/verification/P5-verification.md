---
title: P5 高级 RAG 验证报告
type: verification-report
tags:
  - verification
created: 2026-08-19
---

# P5 高级 RAG 验证报告（2026-08-19）

> 关联：[[docs/plans/phases/P5-advanced-rag|P5 阶段计划]] · [[docs/plans/roadmap|年计划]]

## 测试内容

### 检索层新用例（32，全部离线确定性）

| 文件 | 验证点 | 数量 |
| --- | --- | --- |
| `tests/test_query_rewrite.py` | MultiQuery 生成 / 开关直通 / 委派 / 非法 JSON 容错 / **空生成回退原查询** | 5 |
| `tests/test_multi_query_retriever.py` | RAGFusion 跨子查询融合 / MMR 去重 / 装饰器扇出 | 3+ |
| `tests/test_context_enriched_retriever.py` | 两路召回（native+context）/ RRF 融合 / **factory 装配测试** | 3 |
| `tests/test_corrective_rag.py` | 置信分 / 高置信直通 / 低置信重写重查 / 模式保持 / **factory 装配测试** | 5 |
| `tests/test_selfcheck.py` | 高一致不重答 / 低一致重答 1 轮 / 解析失败回退 / 空答案重答 / **factory 装配测试** | 5 |
| `tests/test_fusion.py` | rrf 既有 + rag_fusion / mmr_dedup | 既有+新增 |
| **合计** | | **32** |

### golden 回归（9 例 × 6 配置）

`config/golden_qa.yaml` 基于 `data/demo` 三份真实语料（稀土简报 / APT28 追踪 / 夜莺评估），`relevant_chunk_ids` 为真实 chunk id（`<doc>#0`），覆盖 native_rag / local / global 三种模式。

**离线桩回归结果**（`uv run python scripts/eval_p5.py`，StubLLM + Hash 嵌入 64 维，内存 stores，确定性可复现）：

| config | ctx_recall | faithfulness | answer_relevance |
| --- | --- | --- | --- |
| baseline | **0.4444** | 0.4444 | 1.0000 |
| multi_query | 0.4444 | 0.4444 | 1.0000 |
| contextual | 0.4444 | 0.4444 | 1.0000 |
| crag | 0.4444 | 0.4444 | 1.0000 |
| selfcheck | 0.4444 | 0.4444 | 1.0000 |
| all | 0.4444 | 0.4444 | 1.0000 |

## 技术栈

- **改写层**：`interfaces/rewriter.py`（`QueryRewriter` ABC）· `MultiQueryGenerator`（LLM JSON 数组，容错解析）· `RewriteRouter`（配置开关 + 空生成回退）。
- **融合层**：`fusion.py` 新增 `rag_fusion`（多子查询 RRF）与 `mmr_dedup`（MMR λ=0.7 去重）；`MultiQueryRetriever` 装饰器。
- **contextual**：`context_enriched_retriever.py`（native + 混摘要权重向量两路召回 → RRF）；工厂按 `contextual_retrieval_enabled` 装配。
- **答案后校验层**：`corrective_rag.py`（来源覆盖置信分，低置信重写重查 1 轮）· `selfcheck.py`（LLM judge 一致性，低分重答 1 轮）。
- **评估**：`eval/`（`EvalHarness` + `golden.py` + `metrics.py`）复用不重写；`scripts/eval_p5.py` 一键回归（`--dump-golden` / `--real` 切真实模型）。

## 验证原理

- **确定性离线**：默认 StubLLM + Hash 嵌入 + 内存 stores（CI 等价纪律），全链路零网络；`context_recall` 为硬指标（检索 id ∩ 相关 id）。
- **契约优先**：新检索器全部实现 `Retriever`/`SearchEngine` ABC，均为装饰器/内部编排，`/query` 响应契约不变。
- **装配即验证**：`build_default_search_engine` 各开关（`multi_query_enabled` / `contextual_retrieval_enabled` / `crag_enabled` / `selfcheck_enabled`）均有装配测试，杜绝“实现存在但未接线”（修复了 Task 3 历史遗留的死代码问题）。
- **golden 真实 id**：chunk_id 取真实 ingest 产物，非伪造，可复现。

## 验证过程

1. **Task 3 装配收尾**：`ContextEnrichedRetriever` 重构为 retriever 装饰器并接入 factory（此前只定义了类、从未被引用——`contextual_retrieval_enabled` 无任何代码读取）；新增 `contextual_context_weight` 配置与装配测试，提交 `f037942`。
2. **Task 4 CRAG**：`corrective_rag.py` + 5 用例 + `crag_enabled`/`crag_threshold` 装配，提交 `f265ea9`。
3. **Task 5 SelfCheck**：`selfcheck.py` + 5 用例 + `selfcheck_enabled`/`selfcheck_threshold` 装配，提交 `fdf9430`。
4. **健壮性修复（Task 2 收尾）**：回归发现 MultiQuery 在子查询生成失败/非法时**空召回**（context_recall 0.00）；`RewriteRouter` 增加空生成回退原查询 + 回归用例，提交 `ef6b643`。修复后 multi_query 恢复 baseline（0.4444）。
5. **golden 回归**：`scripts/eval_p5.py` → 6 配置全跑 → `docs/verification/p5-regression.json` 落盘（含每条 case 的检索 id 与分数）。
6. **全量验证**：`uv run pytest -q -m "not db"` 全绿（见下方证据）；ruff 全绿。

## 关键发现

- **baseline ctx_recall 0.4444**（9 例中 4 例召回相关 chunk，BM25/哈希稠密在 3 文档小语料上的确定性基线）。
- **MultiQuery 空生成缺陷已修**：改动前开启 multi_query 会因空子查询返回空候选（0.4444 → 0.00）；回退后 0.4444。真实模型下此缺陷同样存在保护。
- **contextual v1 为“查询向量缩放”模拟**：在归一化余弦向量库中缩放查询向量不改变排序，context 路与 content 路同排序 → 与 baseline 持平；真实收益需**独立摘要向量列**（`models_content.py` 的 `CommunityRecord.summary_embedding` 同款，留 roadmap P9）。这与 P5 计划「两路 search + 摘要权重缩放模拟」的 v1 边界一致。
- **CRAG/SelfCheck 属答案后校验层**：离线桩 judge 恒定分数下无区分度（数值与 baseline 持平），其重写/重答触发率需真实 LLM 才能度量。
- **answer_relevance=1.0 无区分度**：桩 judge 恒定输出所致；离线回归只承诺 `context_recall`（确定性），faithfulness/relevance 列仅占位，真实模型请跑 `scripts/eval_p5.py --real`。

## Task 6 决策（语义切分）

> **结论：跳过并记录（计划 Step 0 纪律）。**

语义切分启动门槛为「contextual retrieval 的 harness `context_recall` 提升 ≥ 0.05」。本回归中 contextual vs baseline 提升 = **0.00 < 0.05**（且 v1 实现本身是模拟混搜，无独立摘要向量），**不满足启动条件**——不引入高复杂度重切分，语义切分继续列 P5 后半可选（任务计划 checkbox 保持未勾），等待：①contextual v2（独立向量列，P9）落地；②真实模型 golden 回归证据。

## 已知边界与后续

- 本回归为**离线桩证据**（hash 嵌入无语义、judge 桩恒分）；真实模型（deepseek + remote 嵌入）从本次验证环境不可达（沙箱无外网、LAN 模型端点不可达），故真实精度留 `scripts/eval_p5.py --real` 在用户本机补跑。
- `multi_query`/`crag`/`selfcheck` 的真实触发率与收益、`contextual` 真实召回增益均需真实模型证据；接口与开关已就绪，`.env.example` 有完整接线。
- P9 承接：contextual v2 独立摘要向量列、ANN 索引、CRAG 的 LLM 决策路由（自适应 RAG）、SelfCheck → P8 证据验证/幻觉检测。

## 证据

- `docs/verification/p5-regression.json` —— 6 配置 × 9 例完整回归数据（检索 id / 分值 / 答案）。
- `scripts/eval_p5.py` —— 可复现脚本（`--dump-golden` 重建骨架 / 默认离线 / `--real` 真实模型）。
- `config/golden_qa.yaml` —— golden 集（真实 chunk id）。
- 提交链：`f037942`（Task3 装配收尾）→ `f265ea9`（Task4 CRAG）→ `fdf9430`（Task5 SelfCheck）→ `ef6b643`（MultiQuery 回退）→ 本报告。
