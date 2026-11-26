---
title: P9 质量硬化与可用化验证报告
type: verification-report
tags:
  - verification
created: 2026-11-15
---
# P9 质量硬化与可用化验证报告（2026-11-15/16）

> 关联：[[docs/plans/phases/P9-usable-scale|P9 阶段计划]] ·
> [[docs/verification/P8-verification|P8 验证报告]] · [[docs/verification/README|验证索引]]

## 测试内容

### 后端（离线结构 / 契约轨）

- `uv run pytest -q`：**1438 passed / 1 skipped**（真实 PG + pgvector + Neo4j；P8 末基线
  1288 passed / 1 skipped，本阶段 +150 例）。`ruff check` / `ruff format --check` 全绿。
- **T1 答案接地硬化**：`retrieval/answer_postprocess`（模板套话剥离、无效引注剔除、
  **仅证据覆盖率达标时**补句级引注）；核验引擎新增 `verify_claim_against` 多块联合核验
  （`contradicted > supported > uncertain > unsupported` 取最优）、转述支撑
  （二元组 ≥0.5 + 内容字 ≥0.80 + 关键事实一致）、整块单元严格化（内容字 ≥0.95，防把
  分散事实拼成一句）、否定极性冲突门槛提高并剔除「不仅 / 未来 / 不同」类误报。
  golden_verification **60/60** 判定匹配、golden_contradictions **10/10**——口径收紧后
  离线判定零倒退。
- **T2 输出层注入防御**：`security/output_guard` 四类拦截（`verbatim_dump` 源文连续重合
  ≥200 字、`internal_metadata` 字段赋值形态或 ≥2 字段名、`system_prompt_leak` 复述提示
  ≥24 字、`injection_compliance` 宣称已照做）；拒绝话术不误伤的专项用例；
  `[chunk_id]` 标记在检测前剔除——防止后处理插入的引注成为绕过缝隙。接入 QA 合成器、
  Agent 回合落库前（并写审计 `output_guard`）、分析报告 payload（证据节点按协议字段跳过）。
- **T3 语料与校准**：`golden_qa_v3.yaml` 70 例（正例 27 / 多跳 15 / 无答案 11 / 干扰 11 /
  注入 6）、`golden_verification.yaml` 60 条（supported 17 / unsupported 14 / uncertain 14 /
  contradicted 15，注入探针 4）、`config/eval_corpus/` 可追踪副本（`data/demo` 缺失时质量轨
  自动回退，全新克隆可复现）；`cross_validated_calibration` 5 折交叉验证（分折确定性、
  留出样本之和 = 全样本、单样本 / 空输入 / 长度不匹配专项测试）。
- **T4 审计硬化**：`sanitize_audit_detail` 递归脱敏（`record_audit` 写入前强制）；
  `list_audit_logs` 过滤 + 分页 + 总数 + 用户名 JOIN；`purge_expired_audit` 默认永久保留、
  删除时钟与列同源（`now() - make_interval`）；`GET /admin/audit` 需 `manage_users`，
  越权 403；`audit_logs.created_at` 升 TIMESTAMPTZ（原列在 `TimeZone=Asia/Shanghai` 的库里
  落本地墙上时间，与 UTC 语义差 8 小时，留存清理会误删）+ 两个查询索引 + 列型回填迁移。
- **T5 可观测性**：`/readyz` 组件级自检（database `SELECT 1` 带 3s 超时 / Neo4j
  `verify_connectivity` / 配置校验 / agent extra），任一 fail 即 503 且出参不含连接串；
  `X-Request-ID` 入站合法则沿用（≤128 字符防日志注入）否则生成，错误响应同样带；
  `config_validation.validate_settings` 纯函数分级（error/warn/info + 稳定 code），
  `calliodesmo doctor` 与 serve 启动前体检共用同一内核，生产 error 级拒启。
- **T6 迁移台账**：`schema_migrations` + 6 个有序步骤（0001 create_all … 0006 会话软删除列）；
  每步独立事务，失败不记账可续跑（专项测试）；`db init` 记账、`db migrate` 二次为 no-op；
  `ensure_missing_columns` 保留旧语义并与台账同源（不再两套清单）。
- **T7 谓词下推与置换契约**：`get_chunks_by_ids(..., access=)` 在取数层过滤（pgvector 走
  SQL WHERE）；local / global / Agent 取块工具与 worker 全部带 access（「实体可见」不等于
  「块可见」），工具层保留 `visible_to` 复核作双保险；BM25 改倒排候选预过滤（分数不变）；
  新增 `tests/test_vector_store_contract.py`——memory 与 pgvector 两后端在同数据下的可见集 /
  排序 / top_k 放大不泄漏逐项对等，且配置切后端即换实现。
- **T8 压测**：`eval/loadtest.py`（最近秩分位数、固定并发 runner、错误与泄漏计数）+
  `scripts/loadtest_p9.py`；三档并发 1/5/20，每级 120 请求，越权泄漏与失败均为 0，
  `with_hits = 120` 保证不是零命中空转。
- **T10 Agent 会话生命周期**：`agent/session_lifecycle`（软删除 / 恢复 / 列表，谓词下推 +
  密级不洗白复检，删除幂等，越权与不存在同一文案）；已删除会话不能再跑回合；
  API 三端点 + 审计；迁移步骤 0006；服务层与 API 共 10 例。

### 配置改动（压测暴露）

- `db_echo` 与 `debug` 解耦（原 `echo=settings.debug` 使 DEBUG=true 时每条 SQL 写 stdout）；
  新增 `db_pool_size` / `db_max_overflow` / `db_pool_pre_ping` 并同步 `.env.example` 与
  配置校验。实测本机到 `192.168.50.97` 的 `SELECT 1`：pre_ping 开时中位 95ms、关时 36ms
  ——一个往返的代价，跨机房部署可按需关闭（默认仍开，防陈旧连接）。

### 前端

- 三件套绿：`npm run lint`（tsc strict）/ `npm run test`（**82 passed**，P8 基线 80）/
  `npm run build`（1772 modules，dist 产物 1.17 MB；chunk >500 kB 警告留 P10 code-split，
  锚点 2026-W49）。
- 会话侧栏新增：行内二次确认删除（图标按钮，确认态与非确认态行高一致 50px、按钮同行）、
  「显示已删除」勾选后出恢复入口；移动端（<md）同等入口，不让窄视口成功能死角。
- 顺手修一个老 bug：新会话命名用 `total + 1`，删除后反复撞出「会话 1」；改为现有标签
  最大序号 + 1。

### preview 交互闭环

- 桌面 1280×900：登录 → `/app/agent` → 会话列表 20 行渲染正常 → 点删除出现确认/取消 →
  确认后网络面板 `DELETE /api/agent/sessions/{id} → 200` → 列表收敛 → 勾选「显示已删除」
  `GET ...?include_deleted=true → 200` 且出现恢复按钮与「已删除」标记 → 点恢复后计数递减。
  后端日志同步出现 `agent_session_delete` / `restore` 审计写入与
  `WHERE agent_sessions.deleted_at IS NULL` 的下推 SQL。
- `/healthz` 与 `/readyz` 双挂（根 + `/api`）经真实服务实测：`readyz` 200 并回显
  `X-Request-ID`，入站带 ID 时原样回显。
### 浏览器仿真（Playwright e2e，2026-11-16，`--workers=1` 双视口）

- 后端为本地 `serve --seed-demo`（演示语料命中 3 块）+ **桩生成模型**（`test/stub`，
  真模型端点本轮不可达）。结果 **12/14 通过**：登录 / 错误凭据 / 登出 / 管理越权 /
  QA 三模式与 Auto / 库浏览 / 分析提交与报告历史 / 权限矩阵，桌面 + 移动两视口。
- 2 例失败均为 `agent.spec.ts`「Agent 两回合」：断言要看到工具轨迹
  （`search_knowledge`）或预算收敛文案，而桩模型不发起 tool calls
  （实测 `steps=1 / tool_trace=0`，回合与侧车均正常落库）——与 P8 用真模型跑的
  14/14 不同因，属**测试环境降级所致，非产品回归**；真模型恢复后随质量轨一并复跑。
- 会话生命周期另经 API 端到端复核（不依赖 UI）：建会话 → 跑回合（job succeeded +
  `verification` 落库）→ `DELETE /agent/sessions/{id}` 返回 `deleted_at` → 默认列表消失
  → `include_deleted=true` 可见 → `restore` 恢复。

- **受阻项（如实记录）**：移动视口（375×812）的像素复检未能完成——Claude 桌面窗口在验证
  过程中被最小化，`preview_screenshot` 持续报「窗口未绘制」；期间视口仿真重置后
  `innerWidth` 归零，DOM 几何探针也拿不到有效值。该路径改由 vitest（移动端删除入口
  存在性）+ DOM 断言覆盖，**像素级双视口巡检待窗口可见时补做**（锚点 2026-W47，见未竟清单）。

### 运维轨（新增第三类证据）

- `docs/verification/p9-loadtest.json`：memory 后端 200 块，p50/p95 ≈ 1.7ms，
  吞吐 ≈ 590 rps，三档并发持平（说明该规模下瓶颈在单查询链路而非并发）。
- `docs/verification/p9-loadtest-osint.json`：真实数据集（CISA KEV）抽样 500 块，
  p95 ≈ 3.5ms、吞吐 ≈ 293 rps，命中 120/120。
- `docs/verification/p9-loadtest-postgres.json`：真 pgvector 后端同参数，p95 由
  72ms（并发 1）升至 ~705ms（并发 20），吞吐 14.7 → 50.7 rps——**远程单库 + 每请求
  多次往返**是主因，作为 P10 规模项（连接串复用 / 语句合并 / 就近部署）的输入。
- 三份证据的 `leaks_total = 0`、`failed_total = 0`。

### 质量轨（`--real`）

- **受阻（两次尝试，原因不同）**：
  1. **2026-11-16**：LLM 端点 `http://192.168.50.115:8888/v1` 连接被拒（备用
     `192.168.50.212:8888` 同样不可达），ECL ingest 阶段因
     `litellm.InternalServerError: Connection error` 中断。
  2. **2026-11-26 复测**：LLM 端点已恢复（`/v1/chat/completions` 冒烟通过，服务端自报
     模型名 `Qwen3.8-Flash-Next-Dual`），但**嵌入服务 `192.168.50.97:11234` 不可达**
     （TCP 连接超时；重排 `11235` 正常）。`eval_p8.py --real --phase p9` 在 ECL ingest
     的 `remote_embedding._embed_batch` 处以 `httpx.ReadError` 中断，仍未产出
     `p9-real-*.json`。嵌入服务是质量轨建索引与查询编码的硬依赖（`bge-m3`，1024 维），
     不能用 hash 嵌入顶替——那会改变 P8 的对照口径。
- 因此**本阶段不宣称质量达标**：P8 的质量结论（citation_precision / claim_grounding
  0.4091、unsupported 0.1364、contradiction 0.0682、ECE 0.2466 参考值、注入违规 2）
  仍是最新可用数字；P9 的产品改动（引注纪律 + 多块核验 + 转述支撑 + 输出层守卫 + 语料
  扩到 70 例 + 5 折交叉验证）已就位，但**尚未在真模型上重测**。
- 恢复清单（按序执行，全程无需改代码）：
  0. 先确认嵌入服务可用（不可达则后续必然中断）：
     `curl -s -X POST http://192.168.50.97:11234/v1/embeddings -H 'Content-Type: application/json' -d '{"input":["测试"],"model":"bge-m3"}'`
     应返回 1024 维向量；重排同样抽查 `http://192.168.50.97:11235/rerank`。
  1. `CALLIODESMO_LLM_MODEL=openai/qwen3.8-flash-next CALLIODESMO_LLM_API_BASE=http://192.168.50.115:8888/v1 uv run python scripts/eval_p8.py --real --phase p9 --write-calibration`
  2. 落盘 `docs/verification/p9-real-<模型 slug>.json`（slug 取服务端自报模型名），核对
     `threshold_checks` 与 `ece.status`（样本 ≥100 才能作达标断言）；
  3. 若注入违规仍 > 0，逐例看 `cases[].answer` 是否已被输出守卫替换为安全话术
     （守卫在交付面拦截，指标按交付文本判定）；
  4. 用实测数字更新本报告「质量轨」段与 [[docs/plans/phases/P9-usable-scale|P9 计划]]
     Task 11 Step 2，未达门槛则写差距与下一锚点，不放阈值。

## 技术栈

- 后端新增：`security/output_guard.py` · `retrieval/answer_postprocess.py` ·
  `verification/{engine,pipeline,calibration}.py`（口径 v3 + 5 折 CV）·
  `audit/service.py`（脱敏 / 查询 / 留存）· `config_validation.py` ·
  `api/observability.py` · `db/migrations.py` · `agent/session_lifecycle.py` ·
  `eval/loadtest.py` · `scripts/{eval_p8.py,loadtest_p9.py}` · `config.py` 新增 6 项配置。
- 语料：`config/golden_qa_v3.yaml`（70 例）· `golden_verification.yaml`（60 条）·
  `config/eval_corpus/`（可追踪副本）。
- 前端：`features/agent/{AgentPage,api,useAgent}.tsx?`（会话生命周期）+ `api/types.ts`，
  无新增依赖。
- 验证工具：pytest + ruff + vitest + Playwright（本地）+ `preview_*`（交互与 DOM 探针）
  + 截图核对；压测为自研 runner（纯标准库）。

## 验证原理

- **三轨分离**：结构轨（离线契约）/ 质量轨（`--real`）/ 运维轨（探针、体检、压测）各出
  各的证据，互不冒充。质量结论只能来自 `--real`；本轮 `--real` 受阻即明确写「未宣称达标」。
- **口径变更透明**：指标口径 v3（剥套话、多块联合核验、转述支撑、整块严格化、5 折 CV）
  与 P8 数字并列展示，写清「为什么变」与「变完更严还是更松」——本次是**更贴近事实**：
  P8 的 0.4091 有相当比例是核验覆盖不足造成的假 unsupported，而非模型幻觉
  （unsupported_rate 只有 0.1364 即为反证）。补引注只在证据支撑达标时发生，不为无据
  句子编造引注。
- **一票否决不放行**：注入零违规与越权零泄漏在离线、压测、`--real` 三处都按硬门判定；
  压测的每级都带 `with_hits`，零命中的时延数字视为无效。
- **红线随改动迁移**：可见性一律走 `visible_to` / SQL 谓词；新增的取数路径（按 ID 直取、
  倒排候选、会话列表）都必须在下推层过滤，后置过滤只作为双保险而不是唯一防线。
- **默认保守**：审计永久保留（0）+ 清理只在显式命令下发生；会话软删除不硬删消息与执行；
  pre-ping 保持默认开（性能换安全），关闭由配置的人来决定。

## 验证过程

1. 读 P8 计划与验证报告，确认三个真问题（核验覆盖不足 / 输出层防御缺位 / ECE 样本不足）。
2. 写 P9 阶段计划（11 个 Task + 口径 v3 表 + W49 重评判据）。
3. T1–T3 按 TDD 红绿推进，每步以离线 golden 守住「不放宽到假 supported」；
   期间回退过一次错误做法（引注包含规则会让「引用+自加内容」的声明假 supported）。
4. T4–T7 结构改造（审计、探针、台账、下推）逐 Task 提交，DB 测试连真实 PG/Neo4j。
5. T8 压测暴露 echo 绑 debug 与池参数写死两处实现口径问题，随后单独修正并重跑对照。
6. T9 bootstrap 全流程实跑（建表 / 种子 / 迁移核对 / 体检）；`serve` + `preview_*`
   驱动会话删除→恢复全链路；e2e 以 `--workers=1` 跑双视口。
7. T11 收尾：全量回归 1438 passed / 1 skipped；e2e 以 `--workers=1` 双视口跑通 12/14
   （2 例 agent 需真模型 tool calls）；质量轨因端点不可达受阻，按上述清单挂起。
8. 排障留痕：首轮 e2e 有 4 例失败，定位为联调后端未 `--seed-demo`（stores 为空）与
   桩模型不发 tool calls 两个环境原因，补齐语料后 analysis 两例转绿。

## Task 闭合矩阵

| # | Task | 状态 | 提交 |
| --- | --- | --- | --- |
| 1 | QA 答案接地硬化 | ✅ | `230eb07 feat(retrieval): QA 答案接地硬化与句级引注纪律` |
| 2 | 输出层注入防御 | ✅ | `70d1e6e feat(security): 输出层注入防御与敏感输出护栏` |
| 3 | 评估语料 v3 + 交叉验证 ECE | ✅ | `36812ce feat(eval): P9 评估语料 v3 与交叉验证 ECE` |
| 4 | 审计硬化 | ✅ | `f86d607 feat(audit): 审计查询、写入脱敏与留存策略` |
| 5 | 健康检查与配置校验 | ✅ | `8559c28 feat(api): 就绪探针、请求 ID 中间件与配置体检 doctor` |
| 6 | 迁移台账（Alembic 判据留痕） | ✅ | `26ed66a feat(db)` + `e5664be fix(db)` |
| 7 | 谓词下推与 VectorStore 置换 | ✅ | `d684eb6 refactor(retrieval)` |
| 8 | 压测基线 | ✅ | `b724fd3 feat(eval)` + `279e6e8 feat(config)` |
| 9 | 部署引导可用化 | ✅ | `b3f893f chore(deploy)` |
| 10 | W49 重评 + 会话生命周期 | ✅ | `05b11a1 feat(agent)`（结论表见计划 Task 10） |
| 11 | 收尾（--real / 报告 / 文档 / PR） | ⚠️ 结构·运维·回归齐备；`--real` 受阻 | 本报告 |

## 证据文件

- `docs/verification/p9-regression.json`：离线结构 / 契约基线（70 例语料、60 条判定全匹配、
  矛盾 10/10、intent 22/22）——**非质量结论**。
- `docs/verification/p9-loadtest.json` / `p9-loadtest-osint.json` / `p9-loadtest-postgres.json`：
  运维轨规模基线（并发阶梯 / p50-p95-p99 / 吞吐 / 命中数 / 泄漏计数）。
- `docs/verification/p8-real-qwen3.8-flash-next.json`：P8 末次真模型质量证据（口径 v2），
  仍为当前唯一的质量数字来源，P9 待重测。
- `config/calibration.yaml`：校准参数（默认恒等；`--real --write-calibration` 拟合写入）。

## 未竟清单

| 事项 | 锚点 | 去向 / 判据 |
| --- | --- | --- |
| P9 质量轨 `--real` 未执行（LLM 端点 2026-11-26 已恢复；嵌入服务 `11234` TCP 超时） | 2026-W47 | 先验嵌入/重排服务，再按「质量轨恢复清单」执行；达标与否如实登记，不放阈值 |
| 移动端像素级双视口巡检（窗口最小化致截图失败） | 2026-W47 | 桌面重评时补跑 `preview_*` 双视口 + DOM 探针 |
| SSE 回合流式 | 2026-W49（P10 体验批） | 收益真实但要动 API / 前端 / 代理与取消语义四端 |
| ReWOO / PlanExecute | 2026-W49（P10 模型层） | 等 agent golden 多步场景样本量上来再决策 |
| RAG 跨会话记忆 | 2026-W49（P10 数据层） | 先定「记忆」的权限归属与留存策略 |
| 会话归档 / 共享范围变更 | 2026-W49（P10） | 共享要重推三维权限与会话密级快照语义 |
| LangGraph checkpointer 行的物理清理 | 2026-W49（P10） | 与审计留存同批设计（跨表一致性） |
| BM25 稀疏索引与 ProfileCard 改 PG 数据源 | 2026-W52 | 多进程 serve 前必须改（判据见 `api/deps.py` TODO） |
| Alembic 全量迁移 | 2026-W49 | 出现列改名 / 回滚 / 数据回填类需求 ≥2 次再切 |
| 前端 bundle code-split（dist 1.17 MB 警告） | 2026-W49 | 图谱库按需拆分；不影响正确性 |
| pgvector 并发扩展瓶颈（c20 p95 ~705ms） | 2026-W49（P10 规模项） | 就近部署 / 语句合并 / 连接复用；本轮已提供池参数 |
| 前端 e2e 进 CI | 2026-W49 | 依赖真实 PG 与真模型，仍本地跑 |
