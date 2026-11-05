---
title: P8 证据验证与幻觉检测实施计划
type: phase-plan
phase: P8
tags:
  - plan/phase
created: 2026-11-06
---
# P8 证据验证与幻觉检测实施计划

> 介于 [[docs/plans/phases/P7-agent-mode|P7 Agent 模式]]（已完成并合入 main，PR #13）与 P9 动态更新与规模化（锚点 2026-W49）之间。P6 让平台「会分析」（单次提交 → 结构化报告），P7 让平台「会行动、会对话」（ReAct + 多轮状态）；**P8 让平台「会自证」**：对 QA / 分析 / Agent 的可核查声明做**答案-证据映射**、**接地度评分**与**幻觉标记**，把自报置信变成**经校准的置信（ECE）**，并以**报告生命周期（删除 / 版本化 / 复核流）**与**意图路由**把验证结果变成可复核、可追溯的产品能力。写行动工具（ingest / push / merge / 社区管理）仍留 P9+；持久队列与规模化属 P9，本阶段一律不碰。

> **For agentic workers:** 严格按 Task 编号顺序执行（顺序由「为什么是这个顺序」锁定）；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内遵循 TDD 五连（写失败测试 → 跑确认失败 → 实现 → 跑绿 → 提交，可加装配 / 迁移步骤）；不得并行跨 Task 提交，不得跨 Task 顺手扩张范围，发现的额外问题就地留痕（未竟点 + 周次 `2026-Www`）；新 ORM 必须在 `models.py` 集中导入注册；新配置项必须 `config.py` 与 `.env.example` 双同步；DB 依赖测试自动打 `@pytest.mark.db`（CI 的 `lint-and-test` 以 `-m "not db"` 跳过，`db-tests` job 用容器 PG+Neo4j 跑全量）；验收口径双轨——**离线证据只承诺结构与契约，质量证据必须 `--real` 真模型补跑**；有视觉表现的前端改动必须走 `preview_*` 交互闭环 + 三角色权限矩阵 + 多视口 DOM 探针自动巡检，发现即修、复验至零异常才进下一步；验证读取的材料一律经 `visible_to` 三维过滤，证据片段不得跨越当前 clearance；全量回归不低于基线 **1150 passed / 1 skipped**（含 P7 后补的依赖注入守卫测试）。

> [!note] 重锚说明
> P8 原锚点 **2026-W49（11/30–12/06）重评启动**。P7 于 2026-08-31（2026-W36）提前闭合，此后仅剩文档与 CI 维护；按 P6→P7「提前完成即提前开工」的先例（P6 提前约 10 周、P7 提前重锚移交项），P8 自 **2026-W45（11/02–11/08）** 提前启动。原 W49 的未竟重评议程仍保留：与其相关的 SSE / Agent 会话生命周期 / 写工具等条目在 W49 按既定判据决定进 P8 尾巴还是 P9；本计划不预设结论。

## 目标与范围

**总目标**：平台输出（分析报告 / QA 答案 / Agent 回答）中的每一条可核查声明，都能回答三个问题——**证据在哪里**（chunk_id + quote + 原文位置）、**证据是否支持它**（supported / unsupported / contradicted）、**这条置信可不可信**（校准后概率 + 可靠性报告）；报告作为派生情报资产具备**版本、复核、可恢复删除**的完整生命周期；查询入口具备**可审计的意图路由**，减少用户手工选错检索模式。验证只标记、不自动删改内容——低接地结论进入复核流，不静默丢弃。

**本阶段交付（承诺批次，按 Task 顺序）**

| # | 交付 | 判据 |
| --- | --- | --- |
| 1 | 评估语料 v2 + 接地度指标纯函数 | 语料含正例 / 无答案 / 不支持 / 矛盾 / 注入探针；指标函数确定性可测 |
| 2 | 确定性证据核验引擎 | 给定 claim + 源文，输出 supported / unsupported / contradicted + 证据定位；跨文档核验 |
| 3 | 接地度评分与幻觉标记接入 | 分析报告 / QA / Agent 输出带 `verification` 侧车；API 可见；越权不泄漏证据 |
| 4 | 置信度校准（ECE） | 校准器离线拟合 + 输出经校准置信；--real 报告 ECE 与可靠性表 |
| 5 | 意图路由 | 查询 → `native` / `local` / `global` / `agent`，确定性规则 + 置信 + 回退，决策可审计 |
| 6 | 报告生命周期 | 版本快照（append-only）+ 软删除/恢复 + 复核状态机；权限与审计齐备 |
| 7 | 前端验证展示与生命周期 UI | 声明级徽标 / 证据定位 / 版本与复核操作；preview 三角色 × 双视口闭环 |

**范围外（显式归属，不在 P8 做）**

| 事项 | 去向 |
| --- | --- |
| Agent 写行动工具（ingest / push / merge / 社区管理） | P9+（需先有写行动审计模型与复核流；P8 仍只读） |
| 回合 SSE 流式（P7 T21 让位） | P9 体验批（锚点 2026-W49 重评） |
| ReWOO / PlanExecute（P7 T20/T22） | P9 模型层清单（锚点 2026-W49） |
| NLI / ColBERT / 交叉编码器级语义核验 | P9+（P8 v1 确定性核验 + 可选 LLM judge） |
| 跨 chunk 关系补抽 / 别名歧义精解（P1 移交「P8 硬化」） | P8 只做**验证与标记**，不改进抽取模型；质量硬化归 P9 抽取批 |
| 谓词下推 / ProfileCard 改 PG / L2 摘要 / Alembic 复杂迁移 | P9（锚点 2026-W49，与 P7 附录一致） |
| Agent 会话生命周期完整形态（删除 / 归档 / 共享） | 🔁 条件任务 T8（W49 重评后决定做或移交 P9） |

## 验收口径

**双轨严格分离**：StubLLM 与确定性核验对「真实幻觉发生率」零区分度。离线全绿只承诺：证据契约、状态判定、权限矩阵、评分公式、校准器数值正确、生命周期状态机、路由决策表；**质量结论仅来自 `--real`**。两轨证据文件并列：`p8-regression.json`（离线结构 / 契约）与 `p8-real-<模型名>.json`（质量参考）。

**指标定义（单一事实源：`eval/metrics_grounding.py`）**

| 指标 | 定义 | 用途 |
| --- | --- | --- |
| `citation_precision` | 被核验为 supported 的引注数 / 引注总数 | 引用是否真实支撑声明 |
| `citation_recall` | 命中金标证据块数 / 金标证据块总数 | 是否引到了关键证据 |
| `claim_grounding` | supported 声明数 / 可核查声明总数 | 整体接地程度 |
| `unsupported_rate` | unsupported 声明数 / 可核查声明总数 | 幻觉面（无证据支撑） |
| `contradiction_rate` | contradicted 声明数 / 可核查声明总数 | 与源文冲突面 |
| `uncited_claim_rate` | 无引注的可核查声明数 / 可核查声明总数 | 引注纪律 |
| `ece` | 10 桶期望校准误差（confidence vs accuracy） | 置信可信度 |
| `intent_accuracy` | 路由正确数 / 标注查询数 | 意图路由质量 |

**质量门槛（`--real`，样本量不足时降级为参考并如实标注）**

- `citation_precision ≥ 0.80`、`claim_grounding ≥ 0.80`；
- `unsupported_rate ≤ 0.10`、`contradiction_rate ≤ 0.05`；
- `ece ≤ 0.10`（且样本 ≥ 100 条；不足 100 条只报数、不作达标断言）；
- 注入探针零诱导（工具未被诱导、禁用内容不入答案）与越权证据泄漏 = 0（一票否决，离线 + --real 双轨）。

## 关键决策

1. **分层核验，确定性优先**：第一层纯函数——归一化（去空白，复用 `analysis/evidence.py::normalize_for_match`）、引注 `[chunk_id]` 解析、quote 子串定位、跨文档同主题聚合、矛盾启发式（否定词 / 数值 / 日期 / 单位不一致）；第二层可选 LLM judge，只对第一层 `uncertain` 的声明做结构化裁决，离线桩可覆盖契约。理由：判定必须可复现、可单测、CI 全覆盖；LLM judge 只做增量，失败回退第一层结论。

2. **验证结果是侧车，不改 P6 信封契约**：`AnalysisEnvelope` 九字段保持不变；新增 `verification` 作为报告行 / job result / AgentRun 的 JSON 侧车（`AnalysisReportORM.verification` 等可空列，`db/migrate.py` 幂等补列）。理由：P6 已冻结契约，P7 已消费；侧车使 P8 可独立上线、可回滚，历史报告无需回填。

3. **声明粒度的 v1 边界**：分析报告按结构化 payload 中的 `Evidence` 节点与文本字段句子切分；QA / Agent 按句子切分 + 引注解析。v1 只对**带引注或可定位 quote 的声明**做支持性判定；无引注声明单独计入 `uncited_claim_rate`，不臆造证据。理由：给自由文本补引注属生成侧改造，应与核验解耦，避免一次做两件事。

4. **矛盾判定 v1 用启发式 + 可选 judge**：同一实体 / 主题下，数值（含单位）、日期、否定极性冲突判 `contradicted`；启发式命中但语义不确定时标 `uncertain` 并交 judge（若启用）。不引入 NLI 模型重依赖。理由：bge-reranker 只给相关性，不给蕴含；NLI 模型与语料语言/领域匹配成本高，先把确定性面做扎实。

5. **ECE 纯 Python、参数落盘**：10 桶分箱 + 温度缩放（一维网格搜索）离线拟合，参数写 `config/calibration.yaml`（模型 / prompt_version 维度切片），运行时只读参数做变换。理由：无 numpy 依赖、可离线测、可审计；样本不足时明确报「参考值」。

6. **意图路由 v1 确定性规则**：基于查询特征（显式模式、关键词、疑问类型、长度、是否含实体/关系线索、是否要求多步动作）打分，输出模式 + 置信 + 命中理由；低于阈值回退用户选择 / 默认 `native`，并记审计 `intent_route`。不做端到端小模型。理由：路由错误代价高，规则可解释可测试；训练分类器需标注集，先由 T1 语料积累。

7. **报告生命周期 = append-only 版本 + 软删除 + 复核状态机**：版本快照不可变（编辑 / 重新分析各生成新版本），`rollback` 采用 append 式（同 P4 社区版本先例）；删除置 `deleted_at`，可恢复，不硬删；复核状态 `draft → pending → approved / rejected`（拒绝可重提交），全程审计。理由：派生资产需要可追溯与可恢复；物理删除会破坏审计链。

8. **验证只标记，不自动改内容**：低接地 / 矛盾结论封顶置信、标 `needs_review`、进复核队列；不自动删报告、不改原文、不阻断导出。理由：验证器有假阳性，自动处置会放大错误；人工复核是最后一道闸。

## 为什么是这个顺序

1. **语料先行**：P8 的所有指标都依赖带标注的正例 / 无答案 / 不支持 / 矛盾样本；没有语料，评分器与校准器无法验收（P5「小语料饱和」教训）。
2. **核验引擎先于接入**：先把纯函数判定做对，再接报告 / QA / Agent 三条输出面，避免在每个面重复实现判定。
3. **接入先于校准**：ECE 需要置信与正确性的成对样本，必须先在真实输出上产出 `verification` 侧车。
4. **生命周期与路由相对独立**：放在核验链路稳定之后，避免并行扩张。
5. **前端最后**：先有稳定 API 与字段，再做展示与交互，减少返工。

---

## Task 1: 评估语料 v2 + 接地度指标纯函数 ✅ 必做

**目标：** 建立 P8 的验收数据基座：正例、无答案、无支撑、跨文档矛盾、注入探针五类样本，以及全部指标函数的确定性实现与离线基线。

**Files:** 新 `config/golden_qa_v2.yaml` · 新 `config/golden_verification.yaml`（claim + support 标注）· 新 `config/golden_contradictions.yaml` · 新 `src/calliodesmo/eval/metrics_grounding.py` · 测试 `tests/test_metrics_grounding.py` / `tests/test_golden_verification.py`。

- [ ] **Step 1:** 写失败测试：指标公式（citation_precision / recall、claim_grounding、unsupported_rate、contradiction_rate、uncited_claim_rate、ECE 分箱）边界值；空输入、除零、全 supported / 全 unsupported。
- [ ] **Step 2:** 跑确认失败 → 实现 `eval/metrics_grounding.py`（纯函数、无夹具、无 LLM）；ECE 10 桶，返回 `(ece, reliability_table, sample_count)`。
- [ ] **Step 3:** 扩充语料：`golden_qa_v2.yaml` ≥ 30 例（含 ≥5 无答案、≥5 多跳、≥5 干扰项）；`golden_verification.yaml` ≥ 40 条 claim（supported / unsupported / uncertain / contradicted 四类平衡）；`golden_contradictions.yaml` 用 `data/demo` 同源材料构造数值 / 日期 / 否定冲突。
- [ ] **Step 4:** 跑绿 + 落离线基线 `docs/verification/p8-regression.json`（结构 / 契约证据，非质量结论）；语料规模与类别分布打印进验证报告草稿。
- [ ] **Step 5:** 提交：`feat(eval): P8 评估语料 v2 与接地度指标`。

**验收：** 指标单测全绿；语料类别分布满足下限；基线 JSON 可复现。

---

## Task 2: 确定性证据核验引擎 ✅ 必做

**目标：** 给定 claim 与可见源文，输出 `supported / unsupported / uncertain / contradicted` + 证据定位（chunk_id / quote / 归一化偏移）+ 判定理由；支持跨文档同主题聚合。

**Files:** 新 `src/calliodesmo/verification/__init__.py` / `models.py` / `engine.py` · 测试 `tests/test_verification_engine.py`。

- [ ] **Step 1:** 写失败测试：quote 子串（含空白 / 全角标点归一化）、chunk_id 不存在、空 quote、数值 / 日期 / 否定矛盾、跨文档同实体聚合、`uncertain` 边界；判定顺序稳定（contradicted > supported > uncertain > unsupported）。
- [ ] **Step 2:** 跑确认失败 → 实现 `verification/models.py`（`Claim` / `EvidenceSpan` / `VerificationResult` / `Verdict` 枚举）与 `engine.py` 纯函数；复用 `normalize_for_match`，不复制归一化逻辑。
- [ ] **Step 3:** 跨文档核验：claim 无直接 quote 时，按实体 / 关键词在可见源文检索候选句，命中支持句判 supported 并记 `match_type="cross_document"`；命中冲突句判 contradicted。
- [ ] **Step 4:** 权限红线测试：源文只能来自 `visible_to` 过滤后的材料；不可见 chunk 与不存在 chunk 返回同一 `unsupported` 语义（不泄漏存在性）。
- [ ] **Step 5:** 跑绿 + 提交：`feat(verification): 确定性证据核验引擎`。

**验收：** 四类判定在 golden_verification 上确定性可复现；越权探测零泄漏；无新依赖。

---

## Task 3: 接地度评分与幻觉标记接入三条输出面 ✅ 必做

**目标：** 把核验结果变成产品可见的 `verification` 侧车：分析报告、QA 答案、Agent 回合都带声明级判定、汇总指标与 `needs_review` 标记；API 出参可读；审计留痕。

**Files:** 改 `src/calliodesmo/analysis/engine.py` / `job_worker.py` / `report_store.py` · 改 `src/calliodesmo/retrieval/answer_synthesizer.py` · 改 `src/calliodesmo/agent/job_worker.py` · 改 `src/calliodesmo/api/schemas.py` + 各出参 · 新 `src/calliodesmo/verification/pipeline.py` · 测试三条面各一组。

- [ ] **Step 1:** 写失败测试：分析报告落库带 `verification`（claim 数 / supported 数 / unsupported 数 / 指标）；QA 答案带引注核验；AgentRun 带 `verification`；越权材料不出现在证据片段。
- [ ] **Step 2:** 跑确认失败 → 实现 `verification/pipeline.py`（材料收集 → claim 抽取 → 核验 → 汇总），三处调用方注入同一实现；`uncited_claim_rate` 独立统计。
- [ ] **Step 3:** 持久化：`AnalysisReportORM.verification`、`AgentRunORM.verification` 可空 JSON 列；`db/migrate.py` 幂等补列；`models.py` 注册不变（同表加列）。
- [ ] **Step 4:** API 出参扩展（向后兼容，字段可空）：报告详情 / QA 响应 / Agent 回合带 `verification`；审计 `evidence_verify`（仅计数与回流，不记原文）。
- [ ] **Step 5:** 跑绿 + 提交：`feat(verification): 报告/QA/Agent 接地度与幻觉标记接入`。

**验收：** 三条面字段齐全、历史数据兼容；性能不显著劣化（单报告核验 < 1s，纯本地）。

---

## Task 4: 置信度校准（ECE） ✅ 必做

**目标：** 用 golden v2 的置信-正确性样本拟合温度缩放参数，输出经校准置信与可靠性表；--real 报告 ECE；样本不足时如实标注参考值。

**Files:** 新 `src/calliodesmo/verification/calibration.py` · 新 `config/calibration.yaml`（参数与切片）· 改 `verification/pipeline.py`（输出校准后置信）· 新 `scripts/eval_p8.py` · 测试 `tests/test_calibration.py`。

- [ ] **Step 1:** 写失败测试：温度缩放公式、网格搜索最优温度、ECE 计算与分箱边界、空样本 / 全同类样本、参数读写幂等。
- [ ] **Step 2:** 跑确认失败 → 实现校准器（纯 Python，无 numpy）；参数按 `model + prompt_version` 切片；缺参数时恒等映射并记 warning。
- [ ] **Step 3:** `scripts/eval_p8.py`：离线（桩）与 `--real` 两轨，输出 `p8-regression.json` / `p8-real-<模型名>.json`；质量门槛判定与「样本不足」提示。
- [ ] **Step 4:** 接入输出：报告 / QA / Agent 的 `verification.calibrated_confidence`；审计只记参数版本与指标，不记原文。
- [ ] **Step 5:** 跑绿 + 提交：`feat(verification): 置信度校准与 P8 评估脚本`。

**验收：** 校准器数值正确；参数落盘可复现；--real 报告含 ECE、可靠性表、样本量与达标判定。

---

## Task 5: 意图路由 ✅ 必做

**目标：** 查询入口支持 `auto` 路由：`native` / `local` / `global` / `agent`，确定性规则 + 置信 + 命中理由；低置信回退用户默认；决策审计。

**Files:** 新 `src/calliodesmo/retrieval/intent.py` · 改 `src/calliodesmo/api/query.py`（或对应端点）/ `api/schemas.py` · 改前端模式选择器（后续 Task 7）· 测试 `tests/test_intent_router.py`。

- [ ] **Step 1:** 写失败测试：显式模式绝不改写；多跳 / 全局主题 / 实体关系 / 操作指令四类正例；模糊查询回退默认；置信阈值与理由字段。
- [ ] **Step 2:** 跑确认失败 → 实现规则打分器（关键词、疑问类型、长度、实体/关系线索、动作词）；输出 `IntentDecision(mode, confidence, reasons)`。
- [ ] **Step 3:** API 接入：`mode=auto` 时路由并回显 `routed_mode` + `routing`；审计 `intent_route`；显式模式路径零变化（回归）。
- [ ] **Step 4:** 跑绿 + 提交：`feat(retrieval): 意图路由 auto 模式`。

**验收：** 路由决策表测试全绿；显式模式回归不变；标注集 `intent_accuracy` 有离线基线。

---

## Task 6: 报告生命周期（版本 / 软删除 / 复核流） ✅ 必做

**目标：** 报告成为可版本化、可复核、可恢复的派生资产：append-only 版本快照、软删除与恢复、复核状态机与审计。

**Files:** 改 `src/calliodesmo/db/models_analysis.py`（新 `AnalysisReportVersionORM` + 列扩展）· 改 `src/calliodesmo/db/migrate.py` · 新 `src/calliodesmo/analysis/lifecycle.py` · 改 `src/calliodesmo/api/analysis.py` / `api/schemas.py` · 改 `src/calliodesmo/cli.py` · 测试 `tests/test_report_lifecycle.py` / `tests/test_report_lifecycle_api.py`。

- [ ] **Step 1:** 写失败测试：版本快照 append-only（编辑 / 重分析生成新版本，旧版本不可变）；软删除后列表不可见、详情 404、恢复后可见；复核状态机合法 / 非法流转；并发乐观锁；越权 404 同文案。
- [ ] **Step 2:** 跑确认失败 → 实现 ORM（`version` / `snapshot` / `created_by` / `created_at`；报告行加 `deleted_at` / `review_status` / `reviewed_by` / `reviewed_at` / `review_note`）与 `db/migrate.py` 幂等补列；`models.py` 注册新表。
- [ ] **Step 3:** `analysis/lifecycle.py`：`create_version` / `list_versions` / `rollback`（append 式）/ `soft_delete` / `restore` / `submit_review` / `approve` / `reject`；全程 `record_audit`；权限：owner + `APPROVE` 复核。
- [ ] **Step 4:** API + CLI：`GET /analysis/reports/{id}/versions`、`POST .../rollback`、`DELETE` / `POST .../restore`、`POST .../review`；CLI `reports versions/rollback/delete/restore/review`。
- [ ] **Step 5:** 跑绿 + 提交：`feat(analysis): 报告版本化、软删除与复核流`。

**验收：** 状态机与权限矩阵全绿；删除可恢复；版本链可审计；既有报告读取回归不变。

---

## Task 7: 前端验证展示与生命周期 UI ✅ 必做

**目标：** 报告详情展示声明级验证徽标、证据定位与汇总指标；支持版本查看 / 回滚、删除 / 恢复、复核操作；QA / Agent 显示核验摘要；三角色可见性正确。

**Files:** 改 `frontend/src/features/analysis/*` · `frontend/src/features/agent/*` · `frontend/src/api/types.ts` + 客户端 · 测试 `*.test.tsx` · e2e 可选补一组。

- [ ] **Step 1:** 写失败测试：验证徽标按 verdict 渲染；`needs_review` 提示；版本列表与回滚确认；删除后列表消失、恢复入口；无复核权限隐藏操作。
- [ ] **Step 2:** 跑确认失败 → 实现组件与 API 接线；`verification` 字段可空时向后兼容（旧报告不报错）。
- [ ] **Step 3:** `preview_*` 闭环：分析详情（supported / unsupported / contradicted 三态）、QA 引用核验、Agent 回合核验；三角色 × 桌面 / 移动双视口；DOM 探针零溢出 / 遮挡。
- [ ] **Step 4:** 跑绿（vitest + build + lint）+ 提交：`feat(frontend): 证据验证与报告生命周期 UI`。

**验收：** 三角色权限一致；双视口无布局异常；旧报告兼容。

---

## Task 8（🔁 条件）: Agent 会话生命周期

**启用条件:** W49 重评判定「做」且 T1–T7 全部绿灯后剩余工时充足；否则整体移交 P9 并留痕。

- [ ] 写失败测试 → 实现会话软删除 / 归档 / 共享范围变更（复用 Task 6 生命周期范式）→ API / 前端 → 跑绿 → 提交 `feat(agent): 会话生命周期（删除/归档/共享）`。

**验收：** 与报告生命周期同一套权限 / 审计语义；越权 404 同文案。

---

## Task 9: 收尾（验证报告 / 文档 / --real / 全量回归） ✅ 必做

**Files:** 新 `docs/verification/P8-verification.md` · 改 `docs/verification/README.md` · 改 `CLAUDE.md` / `AGENTS.md` 当前阶段与结构段 · 改 `README.md`。

- [ ] **Step 1:** 离线轨：全量 `pytest -q` 绿（≥1150 基线）+ `scripts/eval_p8.py` 落 `p8-regression.json`；前端 vitest / build / lint 绿。
- [ ] **Step 2:** 质量轨（用户本机，`--real`）：`scripts/eval_p8.py --real`，落 `p8-real-<模型名>.json`；如实记录 ECE 样本量、unsupported / contradiction 率、注入零诱导。
- [ ] **Step 3:** 写 P8 验证报告（四要素 + Task 闭合矩阵 + 未竟清单），区分离线 / 质量两轨；登记证据文件。
- [ ] **Step 4:** 文档同步：CLAUDE.md / AGENTS.md 当前阶段补 P8 行、结构段补 `verification/` 与 `eval/metrics_grounding.py`；README badge 更新。
- [ ] **Step 5:** 提交 + PR：`docs(verification): P8 验证报告与文档同步`；PR 合入 main。

**验收：** 双轨证据齐备；P8 未竟项全部带锚点；PR CI 绿。

---

## 依赖与风险

| 风险 | 影响 | 防坑动作 | 落点 |
| --- | --- | --- | --- |
| 确定性核验假阳性（子串匹配 ≠ 语义支持） | 用户误信 supported / 误伤正确内容 | 判定分四类而非二值；`uncertain` 交可选 judge；--real 抽样人工复核；阈值配置化 | T2/T3 |
| 跨文档矛盾启发式误报（否定词 / 数值单位） | contradiction 率虚高，复核队列爆炸 | 只在同实体 / 同主题聚合内比较；数值解析失败降 uncertain；golden_contradictions 类别平衡 | T1/T2 |
| 自由文本 claim 切分质量差 | 指标失真 | v1 只核验带引注 / 可定位 quote 的声明；`uncited_claim_rate` 单列；切分规则测试钉死 | T2/T3 |
| ECE 样本不足（<100） | 校准结论不可信 | 报告显式标注样本量与「参考值」；语料不足则达标判定为「未评估」而非「通过」 | T1/T4 |
| 校准参数过拟合小语料 | 输出置信反而更差 | 按模型 / prompt_version 切片；留出集验证；样本不足保持恒等映射 | T4 |
| 证据片段越权泄漏 | 低密用户经验证读到高密原文 | 材料一律 `visible_to`；证据片段按当前 clearance 截断；越权与不存在同语义；专项矩阵测试 | T2/T3/T7 |
| 报告生命周期破坏既有读取 / 导出 | 回归面受损 | 新列可空 + 幂等补列；软删除仅在查询层过滤；旧报告兼容测试 | T6/T7 |
| 版本链并发写 | 版本号重复 / 丢失 | 乐观锁 + 唯一约束；并发测试 | T6 |
| 意图路由误判用户显式意图 | 体验倒退 | 显式模式绝不改写；低置信回退默认；决策理由可见；审计 | T5 |
| 前端展示增加信息噪声 | 阅读体验下降 | 默认折叠证据细节；三态徽标 + 汇总指标；移动端优先验证 | T7 |
| 范围膨胀（写工具 / SSE / NLI / Agent 生命周期） | 承诺无法兑现 | 范围外表逐项点名去向；T8 条件启动；W49 重评统一决断 | 全局 |
| 本地模型 thinking 默认开启 | --real 时延 / token 上升 | `--real` 脚本记录 thinking 状态；必要时服务端关闭；不计成本但需记录 | T4/T9 |

## 暂缓与移交记录

- **Agent 写行动工具**（P7 移交 P8+）：⏸ 本阶段不做。理由：写行动需先有写审计模型与复核流，P8 的复核流只覆盖派生报告；P9+ 再评估。
- **SSE 流式**（P7 T21 让位）：⏸ 移交 P9 体验批，锚点 2026-W49 重评。
- **ReWOO / PlanExecute**（P7 T20/T22）：⏸ 随 P9 模型层清单，锚点 2026-W49。
- **NLI / 语义蕴含模型**：⏸ P9+；P8 v1 用确定性 + 可选 LLM judge。
- **P1 跨 chunk 关系补抽 / 实体链接精化**：P8 只验证与标记，不改进抽取；质量硬化归 P9 抽取批。
- **RAG 记忆 / L2 摘要 / 谓词下推 / ProfileCard 改 PG / Alembic**：P9（锚点 2026-W49，承 P7 附录）。
