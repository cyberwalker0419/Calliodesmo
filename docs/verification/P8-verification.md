---
title: P8 证据验证与幻觉检测验证报告
type: verification-report
tags:
  - verification
created: 2026-11-06
---
# P8 证据验证与幻觉检测验证报告（2026-11-06）

> 关联：[[docs/plans/phases/P8-evidence-verification|P8 阶段计划]] ·
> [[docs/verification/README|验证索引]] · [[docs/verification/P7-verification|P7 验证]]

## 测试内容

### 后端（离线轨）

- `uv run pytest -q`：**1288 passed, 1 skipped**（真实 PG+pgvector+Neo4j；P7 基线
  1124 passed / 1 skipped）。`ruff check` / `format --check` 全绿。
- T1 语料与指标：`golden_qa_v2` 35 例（正例 12 / 多跳 7 / 无答案 6 / 干扰 7 /
  注入 3）、`golden_verification` 43 条 claim（四类各 10 + 跨文档 3；注入探针 3）、
  `golden_contradictions` 10 组（日期 2 / 否定 6 / 反义 2）；指标边界值（空输入 /
  除零 / 全同类 / 桶边界）单测全绿。
- T2 核验引擎：43 条 golden 判定 **43/43 匹配**、矛盾 10/10 命中；引注归一化
  （空白 + NFKC 全半角）、数值 / 日期区间 / 单位 / 否定极性 / 反义冲突、跨文档
  候选句检索、注入话术不服从、越权与不存在同一 `unsupported` 文案。
- T3 三输出面：分析报告 / QA / Agent 均落 `verification` 侧车（声明级判定 +
  汇总指标 + `needs_review`）；历史报告可空兼容；审计 `evidence_verify` 只记计数。
- T4 校准：温度缩放 / 网格拟合 / ECE 分箱 / 参数 YAML 幂等读写全绿；侧车输出
  `calibrated_confidence`；`scripts/eval_p8.py --real` 质量轨已实现（待用户本机执行）。
- T5 意图路由：规则决策表 15 项单测 + 标注集 22 例 **intent_accuracy 1.0**（离线
  基线）；显式模式零改写与 `auto` 审计经 API 回归锁定。
- T6 报告生命周期：版本 append-only / 回滚 / 软删除恢复 / 复核状态机 / 乐观锁 /
  owner 越权 404 / 删除后列表与详情不可见 —— 服务层 13 项 + API 8 项全绿。
- 侧车契约：`verification` 侧车版本 1，字段与 `api/schemas.py` / 前端
  `api/types.ts` 逐字段对齐；`analysis_reports` / `agent_runs` 可空列经
  `db/migrate.py` 幂等补齐。

### 前端

- 三件套绿：`npm run lint` / `test`（**80 passed**，P7 基线 70）/ `build`。
- 新增 `features/verification/VerificationPanel`（有据 / 无据 / 待定 / 矛盾 /
  未引注五态徽标 + 汇总指标 + 证据引文展开）与
  `features/analysis/ReportLifecyclePanel`（版本链 / 回滚 / 软删除 / 复核流）。
- 报告详情：验证汇总 + 声明级判定（默认展开）+ 版本记录 + 复核操作；旧报告
  `verification=null` 不渲染面板（向后兼容）。
- 报告历史：复核状态列、需复核徽标、删除二次确认、显示已删除 + 恢复入口。
- QA：模式选择器新增 `Auto`，答案卡片回显「自动路由 → mode」与回退原因；
  答案核验摘要与声明展开。
- Agent：助手消息下显示回合级接地度面板（在工具轨迹之上）。

### preview 交互闭环（桌面 + 移动双视口；admin / analyst 双角色）

- admin 登录 → 报告历史：`ok / 需复核 / 待复核` 徽标正确；打开详情：接地度
  0.50、矛盾 1、未引注 1、三条声明与证据引文展开正常；「通过」后状态即时变
  「已通过」，通过 / 驳回按钮消失；版本记录展开显示 v1 与回滚入口。
- analyst 登录：个人库隔离（仅见本人报告）；详情仅「提交复核 / 删除」，无
  通过 / 驳回（提示「待复核（需 approve 权限处理）」）；提交复核 → 待复核；
  删除 → 列表消失 → 「显示已删除」出现「恢复」→ 恢复后回到列表。
- QA `Auto` 模式：路由到 `global` 并回显；答案卡片渲染接地度验证与未引注声明。
- Agent 会话：注入一条带侧车的回合，助手消息下渲染接地度 1.00 / 有据 1 /
  工具轨迹 chips 正常。
- 移动视口（375×812）：报告列表 `scrollWidth == innerWidth`；详情 Dialog 宽
  375、无横向溢出；声明列表与生命周期面板无遮挡。DOM 探针零异常。
- 期间修复：复核动作后 Dialog 状态不刷新（改为本地状态 + 列表派生状态）；
  Node 26 + jsdom 25 不透明 origin 下 storage 不可用（vitest setup 内存
  polyfill + `environmentOptions.jsdom.url`）。

### 质量轨（--real；待用户本机执行）

- 命令：`uv run python scripts/eval_p8.py --real [--write-calibration]`。
- 产出：`docs/verification/p8-real-<模型名>.json`（ECE / 可靠性表 / 样本量 /
  答案准确率 / 注入探针 / 门槛判定）；样本 ≥100 才作 ECE 达标断言，否则如实
  标注「参考值」。
- **本机执行尝试（2026-11-06）**：`.env` 指向的真模型端点
  `http://192.168.50.212:8888/v1` 连接失败（curl exit 7），当前不可达，
  `--real` 未能执行；待服务恢复后补跑并更新本报告与证据文件。
- 门槛：citation_precision ≥ 0.80、claim_grounding ≥ 0.80、
  unsupported_rate ≤ 0.10、contradiction_rate ≤ 0.05、ece ≤ 0.10（样本 ≥100）、
  注入零诱导。**本报告不预设 --real 结论**。

## 技术栈

- 后端：`verification/`（models / engine / pipeline / calibration）·
  `eval/metrics_grounding.py` · `analysis/lifecycle.py` ·
  `db/models_analysis.py`（版本表 + 生命周期列）· `db/migrate.py` ·
  `api/analysis.py` / `api/app.py` / `api/query_with_image.py` ·
  `scripts/eval_p8.py`。
- 语料：`config/golden_qa_v2.yaml` / `golden_verification.yaml` /
  `golden_contradictions.yaml` / `golden_intent.yaml` / `calibration.yaml`。
- 前端：`features/verification/VerificationPanel` ·
  `features/analysis/ReportLifecyclePanel` · 既有 TanStack Query / Radix / lucide，
  无新增依赖。
- 验证工具：pytest + ruff + vitest + `preview_*`（交互与 DOM 探针）+ 截图终检。

## 验证原理

- **双轨严格分离**：确定性核验与 StubLLM 对真实幻觉发生率零区分度——离线全绿
  只承诺证据契约、判定状态、权限矩阵、评分公式、校准数值与生命周期状态机；
  质量结论仅来自 `--real`。
- **分层核验、确定性优先**：第一层纯函数（归一化 / 引注定位 / 矛盾启发式 /
  跨文档检索），可选 LLM judge 只做增量；同一输入恒得同一输出。
- **权限红线**：核验材料一律经 `visible_to`；越权与不存在同一 `unsupported`
  语义；证据片段不跨越当前 clearance。
- **侧车不改信封**：P6 `AnalysisEnvelope` 九字段保持不变，`verification` 独立
  端点 / 可空列，历史报告无需回填、可单独回滚。
- **append-only 生命周期**：版本快照不可变，回滚追加新版本；软删除不硬删；
  复核状态机 + 乐观锁 + 唯一约束。
- **验证只标记不处置**：低接地 / 矛盾只置 `needs_review` 并封顶校准置信，
  不自动删改报告。

## 验证过程

1. T1–T6 按 TDD 红绿循环实现并逐 Task 提交；每步先跑失败测试再实现。
2. T7 前端三件套 + preview 闭环：admin / analyst 双角色、桌面 / 移动双视口，
   报告验证 / 复核 / 版本 / 删除恢复、QA auto 路由、Agent 回合核验全路径。
3. preview 发现并修复两处真问题（复核后 Dialog 状态陈旧；Node 26 测试存储缺失）。
4. T9 全量后端回归 + `scripts/eval_p8.py` 离线结构基线落盘 + 前端三件套复跑。
5. `--real` 质量轨待用户本机执行（见未竟清单）。

## Task 闭合矩阵

| # | Task | 状态 | 提交 |
| --- | --- | --- | --- |
| 1 | 评估语料 v2 + 接地度指标 | ✅ | `feat(eval): P8 评估语料 v2 与接地度指标` |
| 2 | 确定性证据核验引擎 | ✅ | `feat(verification): 确定性证据核验引擎` |
| 3 | 三输出面接地度接入 | ✅ | `feat(verification): 报告/QA/Agent 接地度与幻觉标记接入` |
| 4 | 置信度校准（ECE） | ✅ | `feat(verification): 置信度校准与 P8 评估脚本` |
| 5 | 意图路由 | ✅ | `feat(retrieval): 意图路由 auto 模式` |
| 6 | 报告生命周期 | ✅ | `feat(analysis): 报告版本化、软删除与复核流` |
| 7 | 前端验证与生命周期 UI | ✅ | `feat(frontend): 证据验证与报告生命周期 UI` |
| 8 | Agent 会话生命周期（条件） | ⏸ 未启动 | W49 重评后决定做或移交 P9 |
| 9 | 收尾（报告 / 文档 / --real / 回归） | ✅ 文档与离线轨；--real 待执行 | 本报告 |

## 证据文件

- `docs/verification/p8-regression.json`：离线结构 / 契约基线（语料规模、
  43 条判定全匹配、矛盾 10/10、intent_accuracy、指标公式输出）。
- `docs/verification/p8-real-<模型名>.json`：--real 质量证据（待用户本机生成）。
- `config/calibration.yaml`：校准参数（默认恒等；`--real --write-calibration`
  拟合写入）。

## 未竟清单

| 事项 | 锚点 | 去向 |
| --- | --- | --- |
| `scripts/eval_p8.py --real` 质量轨（ECE / 门槛 / 注入） | 2026-W46（用户本机就绪可提前） | 本阶段收尾补跑，证据入库 |
| ECE 样本 ≥100 的达标断言 | 随 --real | 样本不足时只报参考值 |
| T8 Agent 会话生命周期（条件任务） | 2026-W49 重评 | 做则进 P8 尾巴 / 否则移交 P9 |
| NLI / 语义蕴含 / 交叉编码器核验 | P9+ | 本阶段 v1 确定性 + 可选 judge |
| 意图路由标注集扩充与分类器评估 | P9 | 22 例规则基线仅承诺决策表 |
| 前端 e2e 补验证 / Agent UI 核验组 | 2026-W49 随 e2e 进 CI 重评 | 本地 vitest + preview 已覆盖主路径 |
