---
title: P6 LLM 分析任务验证报告
type: verification-report
tags:
  - verification
created: 2026-08-30
---

# P6 LLM 分析任务验证报告（2026-08-30）

> 关联：[[docs/plans/phases/P6-llm-analysis-tasks|P6 阶段计划]] · [[docs/plans/roadmap|年计划]] · [[docs/verification/README|验证索引]]

## 测试内容

### 后端（离线轨，全量）

- `uv run pytest -q`：**1008 passed, 1 skipped**（真实 PG+pgvector+Neo4j；开工前 475 → Task 22 后 1008）。2026-08-30 补做可选 Task 24（analyze CLI）后重落 **1015 passed, 1 skipped**（+7，`86ca6a8`，cli_db 夹具 + test/stub 离线桩）。
- `uv run ruff format .` / `ruff check .`：270 files unchanged / All checks passed。
- `uv run python scripts/eval_p6.py`：15 例全 `ok`，mean_field_f1 0.0 / mean_tuple_f1 0.0 / mean_judge_overall 3.0，落盘 `p6-regression.json`（结构 / 契约证据，非质量结论；解析失败率 0）。

### 前端（第二批 4 类 + 自定义表单，Task 23 新增）

- `npm run lint` / `test` / `build` 三件套绿；vitest **62 passed**（开工前 52，本会话 +10：AnalysisPage 选择器/自定义表单 +6、ReportViewer 第二批 4 类渲染 +4）。
- 第二批 4 类（关系映射 / 任务 / 概念 / 自定义）选择器解除「即将上线」门控、可提交；ReportViewer 新增 4 类渲染分节；自定义表单（指令必填、可选 schema 客户端 `JSON.parse` 预校验、敏感信息提示）。

### preview 交互闭环（离线桩后端 8200 + dev server 5173）

| 路径 | 结果 |
| --- | --- |
| 登录错误凭证 | ✅ POST /auth/token 401 + 「用户名或密码错误」 |
| 登录正确（admin） | ✅ 200 → 跳 /app/qa |
| 九类选择器 | ✅ 9 类全可选，无「即将上线」灰显 |
| 关系映射 / 任务 / 概念 / 自定义各提交一次 | ✅ 均 202 + job 轮询至 succeeded + 报告落库 + 审计 `analysis_report`；ReportDialog 分节渲染正确（关系条目 / 任务列表 / 概念 / 自定义字段） |
| 自定义缺指令 | ✅ 提交按钮禁用，不发 POST |
| 自定义坏 schema（非法 JSON / 数组根） | ✅ 客户端预校验「schema 不是合法 JSON / 须为 JSON 对象」+ 禁用 |
| 自定义 400 路径（`$ref` 过客户端、后端拒） | ✅ POST 400 + 错误盒「自定义输出 schema 不得包含 $ref（…注入面）」 |
| 三角色抽查（一次性账号 t23analyst/t23reviewer） | ✅ analyst / reviewer 均可见分析页 + 提交启用 + 无管理导航；仅 admin 有管理菜单（与 DEFAULT_ROLE_PERMISSIONS 对齐）；账号验完即停用 |
| console / network | ✅ 仅两条预期失败（401 错密、400 `$ref`），无意外错误 |

## 技术栈

- 后端：`analysis/` 域（schemas/specs/prompts/parser/evidence/access/materials/engine/sanitize/factory/job_worker/report_store）+ `interfaces/analysis.py` + `db/models_analysis.py` + `db/migrate.py` + `api/analysis.py`；评估 `scripts/eval_p6.py` + `eval/` harness；FastAPI + SQLAlchemy 2.0 async + PyJWT/Argon2。
- 前端：React 19 + Vite 6 + TanStack Query + Tailwind（`features/analysis/`：AnalysisPage / ReportViewer / ReportsHistory / api.ts / useAnalysis.ts），无新增依赖。
- 验证工具：pytest + ruff + vitest + `preview_*`（交互）+ Playwright channel=msedge 截图（headless 留档）。

## 验证原理

- **双轨严格分离**：离线桩（StubLLM + hash 64 维）对生成质量**零区分度**（固定输出 + 固定 judge 分），离线全绿只承诺状态机 / schema / 权限矩阵 / quote 子串 / 密级继承 / 轮询契约正确，**不得**表述为「分析质量好」；质量证据仅 `--real`（锚点 2026-W45，用户本机，含 P5 `--real` 同批）。
- **custom 类评估口径**：无固定金标，= 结构校验（sanitize 通过 + schema 符合）+ judge 参考分（见 Task 22 留痕）。
- **契约优先 + TDD**：9 类报告模型与注册表为四方共用锚点；前端 types.ts 与后端 schemas.py 逐字段对齐；每 Task 先写失败测试再实现。
- **权限唯一真相在后端**：前端导航隐藏 + 页内提交禁用为双保险，后端 `visible_to` / `require_permission` 为最终闸。

## 验证过程

1. TDD 红：改 AnalysisPage / ReportViewer / useAnalysis 三测试文件描述第二批新行为 → 11 failed 确认红。
2. 实现：types.ts 去 batch 门控 + 补 4 类 payload 类型；AnalysisPage 选择器解锁 + 自定义表单；ReportViewer 4 类分节 → vitest 47/47 绿 → 三件套绿。
3. preview 闭环：登录（错/对）→ 九类选择 → 4 类各提交 + 报告渲染 → 自定义三态（缺指令/坏 schema/`$ref` 400）→ 三角色抽查 → console/network 双查。
4. 离线轨：`pytest -q` 1008 passed + `eval_p6.py` 重落 + ruff 全绿。

## 关键发现

- **第二批 4 类端到端成立**：提交 → 202 → 轮询 succeeded → 报告落库 + 审计 → ReportDialog 分节渲染，链路完整。
- **自定义注入双闸生效**：客户端 `JSON.parse` 预校验拦非法 JSON / 非对象根；后端 sanitize 拦 `$ref` 等语义注入并返回可读 400（前后端互补，非单点）。
- **headless 环境两条非代码缺陷**（留痕，不修）：① `preview_screenshot` 因面板未显示无法合成帧、且 TanStack `refetchInterval` 默认后台暂停（`refetchIntervalInBackground:false`）致轮询在不可见面板停摆——以覆写 `visibilityState` 复跑确认代码无误（同代码 Task 19/20 已闭环）；② 移动端固定 `w-56` 侧栏挤压内容列为 P3 既有欠账（锚点 2026-W37），本会话未引入。
- **GLM-EYE 识图 401**（复现）→ 回退会话内视觉逐张分析截图（`data/verification/p6/t23-*.png`）。

## Task 闭合矩阵（对照计划「顺序总览」）

| # | Task | 状态 | 提交 / 去向 |
| --- | --- | --- | --- |
| 1–3 | 前置批 / 权限回填 / 配置对账 | ✅ | `b066e8e` `aa3fa50` `569927c` |
| 4–10 | 信封 / 九模型+注册表 / 模板 / 解析链 / 桩 / 材料 / 引擎 | ✅ | `8be6f2f`…`87b8c1c` |
| 11–15 | Job 泛化+migrate / 报告 ORM / worker / 分析 API / 导出 | ✅ | `ee47783`…`88aa23c` |
| 16–17 | 评估两件套 + 离线基线 | ✅ | `07272de` `17acae4` |
| 18 | 前端数据层 | ✅ | `4d09e56` |
| 19 | 前端提交页 + 轮询 | ✅ | `2b57b77` |
| 20 | ReportViewer + 历史/导出 + 三角色 | ✅ | `9ae1666` + 修复 `a3fd42e` |
| 21 | 第二批接线 | ✅ | `14627e7` |
| 22 | 自定义分析（注入防御） | ✅ | `7f319ed` |
| 23 | 第二批前端 + 验证报告 + 文档收尾 | ✅ | 本会话两笔提交 |
| 24 | `analyze` CLI（可选） | ✅ 完成 | `86ca6a8`（2026-08-30 补做：管理员提交 + barrier 同步等待 + 报告摘要；7 例 cli_db 测试，离线桩） |
| 25 | provider 能力探测（可选） | ⏭️ 顺延 | 2026-W49（P9 模型层清单） |
| 26 | 多轮对话状态 | ⏸ 移交 | P7 |
| 27 | L2 全库主题摘要 | ⏸ 移交 | P9（2026-W49，显式改道） |

## 未竟清单（逐条带锚点）

| 事项 | 锚点 | 说明 |
| --- | --- | --- |
| `eval_p6.py --real` + `eval_p5.py --real` 质量补跑 | 2026-W45 | 用户本机，同批合并；验证报告留 `p6-real-<模型名>.json` 待补 |
| demo_seed 顶层 glob 缺口 + seed-cache 失效 | 2026-W36 | 现以 `CALLIODESMO_DEMO_DIR` 环境覆盖绕过 |
| 移动端固定侧栏挤压 | 2026-W37 | P3 既有，候选折叠侧栏/抽屉 |
| logout 方法不匹配（DELETE vs POST 405） | 2026-W37 | cookie 启用后影响面升格，修时须同验 cookie 失效 |
| GLM-EYE 识图复跑 | 2026-W36 | 本会话 401，回退会话内视觉 |
| 团队级自定义模板注册表 + 完整 jsonschema | 2026-W47 | P7 评估（仿 ExtractionTemplateRegistry） |
| Alembic 复杂迁移 | 2026-W49 | 现 `db/migrate.py` 承接幂等补列 |
| `api/deps.py:89` ProfileCard/BM25 改 PG + 三 store 谓词下推 | 2026-W49 | P9 同批 |
| L2 主题摘要改道 | 2026-W49 | P9 重评（P2 原指派 P6，此处显式改道） |
| 报告删除/版本化/复核流、置信度校准 ECE | P8 | 见 roadmap P8 段 |
| 多轮对话状态 | P7 | LangGraph 宿主 |
| e2e 链路补建（frontend/e2e 空目录） | 2026-W47 起 | 随 P7 |

## 证据

- `p6-regression.json`（离线基线 15 例全 ok；结构/契约证据，非质量结论）· `p6-real-<模型名>.json`（**待补**，2026-W45 用户本机）。
- `pytest` 1008 passed（Task 23 门槛）→ 1015 passed（Task 24 补做，`86ca6a8`）/ ruff clean / 前端三件套绿。
- `data/verification/p6/t23-*.png`（preview 截图，不入库）· `data/serve-preview-p6-t23.log`（serve 日志，不入库）· `data/verification/p6/t23-capture.cjs`（截图脚本，不入库）。
- 提交链：`b066e8e`…`7f319ed` + `feat(frontend)` / `docs(verification)` 两笔 + Task 24 补做 `86ca6a8`。
