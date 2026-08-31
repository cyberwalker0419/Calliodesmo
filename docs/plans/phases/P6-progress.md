---
title: P6 进度快照与新会话交接
type: phase-progress
tags:
  - plan/phase
created: 2026-08-30
---
# P6 进度快照与新会话交接

> 快照时间：2026-08-30（2026-W35，可选 Task 24 补做收口后刷新）。**新会话先读本文件**，再按 [[docs/plans/phases/P6-llm-analysis-tasks|P6 计划]] 从断点续做。主线文档的 checkbox 与「顺序总览」状态列已随提交同步，是唯一权威口径；本文件只做交接索引。

## 总进度：23/23 必做 + 可选 #24 完成

- 分支：`feat/p6-llm-analysis-tasks`（已 push origin，PR #11：https://github.com/cyberwalker0419/Calliodesmo/pull/11，**已于 2026-08-30 合入 main**，`5c0bc0b`）
- 测试基线：**1015 passed, 1 skipped**（真实 PG+pgvector+Neo4j；开工前 475；Task 22 自定义分析 +36；Task 24 analyze CLI +7）；前端 vitest **62 passed**（Task 18 +9 / Task 19 +11 / Task 20 +17 / Task 23 +10；开工前 15）
- 执行纪律：每 Task TDD 五连 + 独立审查；提交信息用计划指定中文 Conventional Commit + `Co-Authored-By: Claude <noreply@anthropic.com>` 尾行

| 批次 | 范围 | 状态 |
|---|---|---|
| Task 1–3 | 时区 TODO / ANALYZE 权限+种子回填 / 配置对账 | ✅ `b066e8e` `aa3fa50` `569927c` |
| Task 4–10 | 信封 / 九类模型+注册表 / 模板 / 解析链 / 桩 / 材料 / 引擎 | ✅ `8be6f2f`…`87b8c1c` |
| Task 11–15 | Job 泛化 + migrate / 报告 ORM / worker / 分析 API / 导出 | ✅ `ee47783`…`88aa23c` |
| Task 16–17 | 评估两件套 + 离线基线（**第二批门槛之一已达成**） | ✅ `07272de` `17acae4` |
| Task 18 | 前端数据层（types / API 客户端 / `useAnalysis` hook + vitest） | ✅ `4d09e56` |
| Task 19 | 前端提交页 + 轮询（preview 闭环） | ✅ `2b57b77` |
| Task 20 | 前端报告渲染 + 历史 / 导出 + 三角色矩阵（preview 闭环） | ✅ `9ae1666` + 审查修复 `a3fd42e`（cookie 会话回退） |
| Task 21 | 第二批接线（关系映射 / 任务 / 概念，图谱复用） | ✅ `14627e7`（基线重落 15 例全 ok，972 passed） |
| Task 22 | 自定义分析：用户 schema sanitize + 动态 spec + 注入防御 | ✅ `7f319ed`（全量 1008 passed） |
| Task 23 | 第二批前端 + 验证报告 + 文档收尾（含新建 2026-09/10/11 月计划） | ✅ `4c08a55` `29e9dfd`（见 [[docs/verification/P6-verification|P6 验证]]） |
| Task 24（可选） | `analyze` CLI | ✅ `86ca6a8`（2026-08-30 补做：管理员提交 + barrier 同步等待 + 报告摘要；7 例测试） |

## 续接方法（新会话按序执行）

1. **探断点**：`git log --oneline -3` + `git status -s`。
   - 工作树有未提交改动 → 核查半成品质量 → `uv run ruff format . && uv run ruff check . && uv run pytest -q` 绿门槛 → 按计划提交信息提交；
   - 树干净 → 看计划「顺序总览」找第一个「未开始」的必做 Task，直接按该任务 Step 开工。
2. **每 Task**：严格 TDD 五连（写失败测试 → 确认红 → 实现 → 跑绿 → 提交）；提交前门槛 = ruff format/check + 全量 `uv run pytest -q`（真库、禁 `-n`，约 2.5–4 分钟）；完成后勾除计划 checkbox + 改状态列。前端任务另跑 `npm run lint/test/build`，有视觉表现的走 `preview_*` 交互闭环（前端 dev server 用 `preview_start frontend-dev`，后端 `uv run calliodesmo serve --seed-demo --port 8200`）。
3. **编排建议**：Workflow 顺序执行（每 Task 一个实现 agent + 一个独立审查 agent，审查 fail 派修复最多两轮）。旧脚本范式：会话目录 `workflows/scripts/p6-w1-tasks-1-10-*.js`、`p6-w2-tasks-11-17.js`（Task 数组 + 逐项提示词 + 审查/修复循环）；新会话可照抄结构建新脚本。
4. **可选**：`/loop 20m 检查任务进度，自动接续中断的任务，输出任务报告`（注意：定时器只在会话空闲时触发，长跑工作流期间不触发；汇报以工作流完成通知 + 随问随答为主）。

## 移交注意事项

- **`--real` 质量补跑已完成**（原锚点 2026-W45 提前于 2026-08-30（2026-W35）执行完毕；用户本机真模型 `Qwen3.8-27B-Q4_K_M`（GGUF Q4_K_M，LM Studio @ 192.168.50.97:8081，thinking 禁，32768 上下文约束））：两份证据已入库（`0d4da38` + 审查修复 `100a50d`）——`docs/verification/p6-real-Qwen3.8-27B-Q4_K_M.json`（`eval_p6.py --real`，15 例全 ok，mean_field_f1 0.1136 / mean_tuple_f1 0.5643 / mean_judge 4.4）与 `docs/verification/p5-real-Qwen3.8-27B-Q4_K_M.json`（`eval_p5.py --real`，9 例 × 6 配置三指标全 1.0000，小语料无区分度）；已登记 `docs/verification/README.md` 并更新 `docs/verification/P6-verification.md` 质量轨章节与未竟清单。离线基线 `p5-regression.json` / `p6-regression.json` 保持原样（离线≠质量，双轨口径不变）。收口待办已勾除。
- **P6 离线基线已落盘**（Task 17 立基线，Task 21 第二批补 5 例重落，`docs/verification/p6-regression.json`）：15 例全 `ok`，mean_field_f1 0.0 / mean_tuple_f1 0.0（桩零区分度）/ mean_judge_overall 3.0（桩固定分）——结构/契约证据，非质量结论；第二批（Task 21–22）门槛之一已满足。
- **Task 22 自定义分析已交付**（2026-08-30，`feat(analysis): 自定义分析（注入防御 + 动态 spec）`）：新 `analysis/sanitize.py`（`sanitize_user_schema` 拒根非对象 / `$ref` / 循环 / 深度 >4 / 键 >30 / 超字节 + `trim_to_safe_json_schema` 白名单裁剪）；`specs.py` 注册 `custom`（9 类全注册）+ `build_custom_spec` 安全闸门；新模板 `custom.txt`（指令 / schema / 材料均在 user 段）；`render_prompt` `{instruction}` 只进 user、system 令牌清除（结构性隔离，注入探针锁定）。**留痕**：团队级自定义模板注册表 + 完整 `jsonschema` 校验 → P7 评估（锚点 2026-W47）；custom 无固定金标，评估口径 = 结构校验 + judge 参考分（验证报告归 Task 23）。前端自定义表单归 Task 23，本任务未动前端。
- **Task 25 不做**：按计划顺延 2026-W49（P9 模型层清单）。
- `design/` 未追踪目录与本阶段无关，不动。
- 既有库迁移已由 `db/migrate.py` 承接并挂进 `db init`（Task 11）；复杂迁移需 Alembic 已留痕 2026-W49。
- litellm 钉版 `>=1.85,<1.91` 不动；`data/` `.env` `.obsidian/` 不入库。
- **dev 演示种子工具缺口**（Task 19 闭环发现，锚点 2026-W36）：`ecl/demo_seed._list_demo_files` 仅顶层 glob，用户把 `data/demo-docs` 改嵌套语料后 `serve --seed-demo` 直接 FileNotFoundError；seed-cache 无失效标记，dev 库团队重建后缓存 chunk 的 team_id 漂移致 `visible_to` 全过滤（本会话以 `CALLIODESMO_DEMO_DIR=data/demo` + 新缓存路径环境覆盖绕过，旧缓存改名 `.stale` 保留）。修法候选：`rglob` 递归 + 缓存记 team_id/demo_dir 哈希失效。
- **移动端布局**（P3 既有，锚点 2026-W37 评估）：App 固定 `w-56` 侧栏在 <md 视口挤压内容列（全站页面同症，非 Task 19 引入），候选折叠侧栏 / 抽屉导航。
- **外部识图 MCP 不可用**（Task 19/20 会话均复现）：GLM-EYE 401 / MiniMax 配额上限；preview 截图改以会话内视觉逐张分析（存 `data/verification/p6/t19-*.png` / `t20-*.png`），GLM-EYE 复跑锚点 2026-W36。
- **Task 20 三角色矩阵 dev 用户**（2026-W35 创建，dev 库本地测试用）：`p6analyst`（analyst / SECRET）与 `p6reviewer`（reviewer / SECRET），均已加入示例团队（team scope 可见演示语料；不加入则分析提交报「无可见材料」）。**密码不入库**：原明文密码已自本文档移除（曾随本地历史 `9ae1666` 入库，push/PR 前建议改密或重建账号）；后续预览需登录这两个账号时，以 admin 先停用再重建同名账号（`PATCH /admin/users/{id}` 不支持改密，仅 clearance/is_active/email），或直接新建账号（`POST /admin/users` + 授角色 + 加入示例团队），用完即弃不留档。admin 凭据仍取 `.env`（不回显）。
- **Task 20 审查修复——导出 401**（2026-08-30，`fix(frontend): 修复 Task 20 审查问题`）：报告导出裸 `<a href download>` 导航无 Authorization 头，旧 `get_current_context` 只收 Bearer -> 401。修法取审查二选一之「兑现 cookie 为主设计」：`api/deps.py::get_current_context` 增 cookie 消费（Bearer 优先、无则回退 `calliodesmo_session`；SameSite=Lax 限跨站子资源携带，状态变更端点均 POST 不受 CSRF 影响），`SESSION_COOKIE` 常量落 `deps.py`、`app.py` 改导入；前端零改动。新增 3 例后端回归（cookie 过 `/auth/me` 200 / 伪造 cookie 401 / cookie 过导出 200+附件头）。preview 实点导出 json/md 均 200 + `report_export` 审计，serve 日志佐证留 `data/serve-preview-p6-t20-fix.log`（不入库）；本会话截图以会话内视觉分析（preview_* 无落盘能力，同前会话回退口径）。
- **logout 方法不匹配**（P3 既有欠账，Task 20 闭环发现，锚点 2026-W37）：前端 `AuthContext.logout` 走 `DELETE /auth/logout`，后端 `api/app.py:103` 为 `POST /auth/logout` -> 405；客户端 catch ApiError 后仍本地清会话，登出 UX 不受影响。**cookie 消费启用后影响面升格**：登出仅清客户端 token，httpOnly cookie 服务端不删、JWT 过期前仍有效——修 logout（前端改 `api.post` 或后端补 DELETE 别名）时须同验 cookie 失效。
- 中断史：会话重启会杀掉后台工作流，但每 Task 完成即提交，工作树半成品可核查后验证提交，恢复零损失——遇中断按「续接方法」第 1 步处理即可。
