---
title: P7 Agent 模式实施计划
type: phase-plan
phase: P7
tags:
  - plan/phase
created: 2026-08-30
---
# P7 Agent 模式实施计划

> 介于 [[docs/plans/phases/P6-llm-analysis-tasks|P6 LLM 分析任务]]（已完成并合入，PR #11）与 P8 证据验证与幻觉检测（待启动）之间。P6 让平台「会分析」（单次提交 → 单轮结构化报告）；P7 让平台「会行动、会对话」：围绕三层知识图谱已落库的能力，建**工具定义 + 多步推理（ReAct / PlanExecute，LangGraph 状态图）+ 多轮对话状态（PG checkpointer）**，一切行动受三维权限约束（「权限内行动」），同批承接 P6 移交三项——团队级自定义分析模板注册表评估（原锚点 2026-W47 → 重锚 W44）、`frontend/e2e` 链路补建（原锚点 2026-W47 起 → 重锚 W44）、多轮对话状态（P5 唯一显式移交，并入 P7 本体）。跨文档证据核验与幻觉检测属 P8，写行动工具属 P8+，持久队列与规模化属 P9，本阶段一律不碰。v1 工具集只读 + 分析桥；P6 产出的结构化报告契约与任务注册表被 Agent 直接消费、零返工（P6 移交承诺兑现）。

> **For agentic workers:** 严格按 Task 编号顺序执行（顺序由本文「为什么是这个顺序」锁定）；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内遵循 TDD 五连（写失败测试 → 跑确认失败 → 实现 → 跑绿 → 提交，可加装配 / 迁移步骤）；不得并行跨 Task 提交，不得跨 Task 顺手扩张范围，发现的额外问题就地留痕（未竟点 + 周次 `2026-Www`）；新 ORM 必须在 `models.py` 集中导入注册；新配置项必须 `config.py` 与 `.env.example` 双同步；DB 依赖测试自动打 `@pytest.mark.db`（CI 以 `-m "not db"` 跳过，本地 `.env` 全量回归留证据）；验收口径双轨——**离线证据只承诺结构与契约，质量证据必须 `--real` 真模型补跑**（见「目标与范围 · 验收口径」）；有视觉表现的前端改动必须走 `preview_*` 交互闭环 + 三角色权限矩阵 + **多视口 DOM 探针自动巡检**（横向溢出 / 竖排挤压 / 遮挡，发现即修、复验至零异常才进下一步，2026-08-31 用户指令固化）；**agent 一切工具调用必须过三维权限门控，越权与不存在返回同一错误消息（不泄漏存在性）**；agent 依赖走 extra `agent`，运行时懒导入 + 缺依赖友好报错（503 同 ingest 惯例）；全量回归不低于基线 **1015 passed**。

> [!note] 重锚说明
> P6 原排期 2026-W36–W45，实际于 2026-08-30（2026-W35）提前全部闭合并合入 main（约 10 周提前量），W36–W46 窗口整体让渡给 P7：P7 自 **2026-W36（08/31–09/06）** 直接开工（本计划「节奏建议」表即此窗口）；原移交锚点 2026-W47 两项（团队级模板注册表评估、e2e 补建）提前重锚至 **2026-W44**；`--real` 质量补跑定锚 **2026-W45**。重锚做法仿 P6 把 `--real` 从 W45 提前到 W35 的先例。

## 目标与范围

**总目标**：用户在 Agent 模式下建立会话，系统以 LangGraph 状态图经平台工具（检索 / 图谱 / 实体 / 文档 / 社区 / 分析桥）多步推理作答；每次工具调用经角色权限 + 密级 + 库范围三重门控，越权不泄漏存在性；会话 / 消息 / 执行以三维权限一等公民落库持久（可查询、可审计、`visible_to` 过滤），多轮状态经 checkpointer 跨请求 / 重启续接；配套 golden 轨迹评估 harness（工具集匹配 + 边界泄漏=0 一票否决 + 预算指标），让工具调用行为首次有回归口径。

**阶段边界**（本计划定义：P7 Agent 模式——ReAct / ReWOO / PlanExecute（LangGraph）+ 工具定义，权限内行动）：

- **三模式归宿（决策 3）**：ReAct ✅ 必做（v1 主链，手写 StateGraph）；PlanExecute 🔁 可选（批 2，启动门槛 = ReAct `--real` 质量证据达标）；ReWOO ⏸ 暂缓（留痕，锚点 2026-W49 随 P9 模型层清单重评，`AgentMode` 枚举预留值）——三模式均有明确归宿，符合定义域。
- **三项承接**：多轮对话状态（P5 唯一显式移交，并入本体，LangGraph 状态图 + PG checkpointer 为宿主）；团队级自定义分析模板注册表评估（先评估后决定实现，锚点重锚 2026-W44）；`frontend/e2e` 链路补建（重锚 2026-W44）。
- 保持 v1 工具只读 + 分析桥；写行动工具（ingest / push / merge / 社区管理）整体划出（P8+，需先有 agent 写行动审计与复核模型，P7 只读压低注入爆炸半径）。

**验收口径（双轨，硬性）**：

- **离线证据**（CI 可跑、桩驱动）只承诺：状态图结构与轨迹结构正确（节点序列 / messages 结构 / usage 累计）、工具契约正确（输入映射与输出结构）、三角色 × 四密级权限矩阵正确（越权与不存在同一消息、不泄漏存在性）、预算三重帽语义正确（超限强制收敛）、会话持久化与多轮续接正确、审计字段齐全。**桩对工具选择恰当性与答案质量零区分度**（脚本化工具序列 ≠ 真模型决策），离线全绿**不得**表述为「agent 行为质量好」。
- **质量证据**（仅 `--real`）：真模型跑 `scripts/eval_agent.py --real`——轨迹 / 工具选择恰当性、答案接地、预算行为（步数与 token 分布）、循环稳定性。补跑锚点 **2026-W45**（用户本机，就绪可提前）；若延误顺延至 2026-W46 并在验证报告留痕。证据文件：`agent-regression.json`（离线）与 `agent-real-<模型名>.json`（质量）。**真模型后端必须支持原生 tool calls**，不支持则换模型并留痕，不做 prompt-based 文本协议降级。

**范围外（逐条点名去向）**：

| 事项 | 去向 |
|:--|:--|
| 跨文档证据核验 / 幻觉判定（答案-证据映射、接地度评分、低接地声明标记） | P8（证据验证与幻觉检测阶段；与 P6 quote 子串自验证同域） |
| 意图判别路由（查询 → 检索模式 / agent 分派） | P8（P5/P6 范围外显式移交） |
| 报告生命周期（删除 / 版本化 / 复核流） | P8（与证据验证配套） |
| 置信度校准（ECE） | P8（P6/P7 自报置信仅作排序 / 复核标记） |
| Agent 写行动工具（ingest / push / merge / 社区管理） | P8+（需先有 agent 写行动审计模型与复核流；P7 只读压低注入爆炸半径） |
| Agent 会话生命周期完整形态（删除 / 归档 / 共享范围变更） | P8 候选（随报告生命周期同批评估；P7 仅创建与读取） |
| RAG 记忆（跨会话长期记忆） | P7 显式点名：会话内多轮状态由 checkpointer + 窗口截断承接；跨会话记忆锚点 2026-W49 随 P9 清单一并重评（P5 范围外「RAG 记忆」原未点名去向，此处补） |
| L2 全库主题摘要 | P9（锚点 2026-W49，随候选向量管线落地重评；材料侧复用 `retrieval/global_search` 社区摘要召回路径） |
| `api/deps.py` ProfileCard/BM25 改 PG TODO | P9（锚点 2026-W49，与谓词下推同批；agent 工具经 store 接口消费，不新增依赖） |
| 三 store list 谓词下推（按 `doc_ids` 过滤） | P9（锚点 2026-W49；agent 工具检索范围 = 全可见库，前端文案沿用 P6 明示口径） |
| mmr_dedup 运行时接线（P5 遗留） | P9（锚点 2026-W49，随候选向量管线落地重评） |
| contextual v2 独立摘要向量列（P5 遗留） | P9（锚点 2026-W49，随 contextual 收益证据重评） |
| 语义切分 | 等证据重评（锚点 2026-W49；启动门槛 ctx_recall 提升 ≥0.05，实测 0.00） |
| Celery+Redis 持久队列 / ANN / 分布式规模化 | P9（P7 复用 `BackgroundTasks`；checkpoint 高并发吞吐优化随压测同批重评） |
| VectorStore 置换验证 + 审计硬化 / 合规 / 压测 + 社区规模化增量 | P9（锚点 2026-W49；e2e 进 CI 随审计硬化一并重评） |
| Alembic 复杂迁移 | P9（锚点 2026-W49；agent 新表走 `create_all` + `db init` 幂等，补列由 `db/migrate.py` 承接） |
| Provider 原生结构化输出能力探测（P6 Task 25 顺延） | P9（锚点 2026-W49 模型层清单；agent 的 tool_calls 走 LiteLLM 原生能力，不依赖此项） |
| ColBERT / multi-vec 单 token 级检索 | P9+ |
| 回合 SSE 流式输出 | P7 🔁 可选（T21）；若让位则留痕未竟清单（锚点 2026-W49，随 P8/P9 清单重评） |
| ReWOO 模式 | P7 ⏸ 暂缓（T22 留痕），锚点 2026-W49 随 P9 模型层清单重评；前置 = 预算控制与轨迹评估成熟 |
| checkpoint 高并发吞吐优化（AsyncPostgresSaver 内部锁串行化） | P9 压测同批（留痕锚点 2026-W49；P7 单用户交互场景不承诺） |

## 顺序总览

| # | Task | 承诺 | 状态 |
|---|---|---|---|
| 1 | 前置批：清 W36/W37 移交操作债（GLM-EYE 复跑 / demo_seed / 移动侧栏 / logout+cookie） | 必做 | ✅（GLM-EYE 停用、全原生视觉，W38 锚点注销，2026-08-31 用户指令） |
| 2 | 依赖引入与钉版验证：extra `agent`（langgraph 家族）+ Windows wheel + CI 接线 | 必做 | ✅ |
| 3 | LLMProvider 原生工具调用契约扩展 | 必做 | ✅ |
| 4 | StubLLM `[AGENT:*]` 脚本化工具序列分支 | 必做 | ✅ |
| 5 | 工具契约：`interfaces/agent.py` 冻结 + 注册表 + 三维权限门控 | 必做 | ✅ |
| 6 | BaseChatModel 适配器：LLMProvider → LangGraph 桥 | 必做 | ✅ |
| 7 | 第一批工具：只读检索 / 图谱 / 实体 / 文档 / 社区 | 必做 | ✅ |
| 8 | 第二批工具：分析桥（reports + run_analysis） | 必做 | ✅ |
| 9 | 评估 harness v1：agent golden 轨迹集 + 指标 + 边界探针（离线） | 必做 | ✅ |
| 10 | ReAct 手写 StateGraph + 三重预算帽 | 必做 | ✅ |
| 11 | 会话 ORM 三表 + AsyncPostgresSaver 接线 | 必做 | ✅（Windows 开发态 InMemory 降级留痕 W49） |
| 12 | 多轮状态 × 三维权限交叉专项（历史截断 + 降级重验 + 注入探针） | 必做 | ✅ |
| 13 | 回合编排 worker：job 范式 + AccessContext 重建 + 审计 | 必做 | ✅ |
| 14 | API 面：`/agent` sessions / runs / messages（job 范式） | 必做 | ✅ |
| 15 | 前端聊天面：会话列表 + 消息流 + 工具轨迹 + 轮询（preview 闭环） | 必做 | ✅ |
| 16 | e2e 补建：`frontend/e2e` smoke 套件六组（本地绿，不进 CI；重锚 W47→W44） | 必做 | ✅（LAN DB 抖动留痕，见验证报告） |
| 17 | 团队级分析模板注册表评估（评估口径先行；重锚 W47→W44） | 必做 | ✅ 结论顺延 P9 |
| 18 | 按评估结论实现轻量模板注册表（评估门控） | 🔁 可选 | ⏭️ 取消（评估结论顺延 P9） |
| 19 | `--real` 质量补跑与验收（锚点 2026-W45） | 必做 | ✅（提前于 2026-08-31） |
| 20 | Plan-and-Execute 可选模式（批 2，条件启动） | 🔁 可选 | 门槛达标，让位收尾（锚点 W49） |
| 21 | 回合 SSE 流式（可选增强） | 🔁 可选 | 让位（锚点 W49） |
| 22 | ReWOO 归宿留痕（暂缓，锚点 2026-W49） | ⏸ 暂缓 | ✅ 留痕 |
| 23 | 收尾：阶段计划勾除 + 路线图 / 月计划同步 + PR | 必做 | 🚧 本会话 |

**为什么是这个顺序**：

1. **风险前置**（最可能翻车的坑最早拆）：T1 先清操作债——`demo_seed` 修复直接恢复 `serve --seed-demo`，是 P7 preview 闭环与 e2e 的硬前置，四条尾巴（GLM-EYE 复跑 / demo_seed / 移动侧栏 / logout+cookie）一次清掉；T2 把依赖未知数（Windows wheel、uv 解析）这两个最便宜的坑在写任何 agent 代码前拆掉。
2. **契约先于装配、离线先行**：T3–T4 落「桩循环能力」——LLMProvider 工具调用契约 + StubLLM 脚本化工具序列，是全部后续 agent 测试的地基（桩不能驱动工具循环，后面一切离线测试无从谈起）；T5 一次性冻结 agent 域契约（引擎无关可插拔，LangGraph 仅为实现细节），越权与不存在的同形语义当周钉死。
3. **复刻已验证范式**：T6 适配器保持 LLM 所有权在 `LLMProvider` 内（不旁落）；T13–T14 按 P4.5 ingest / P6 analyze 的 job 范式 1:1 复刻（`Job.task_type="agent"` + `BackgroundTasks` + barrier），零新范式成本。
4. **评估先立**：T9 harness 作为图实现的放行门槛（边界探针零泄漏 + 工具集匹配达标才进 T10 主链），避免「先实现后评估」的质量黑洞；主指标用工具集匹配而非严格序列匹配（稳健、减伪不稳定）。
5. **最大翻车面专项周**：T11–T12 把多轮状态持久化（ORM + AsyncPostgresSaver 工程坑集一次做对）与三维权限交叉矩阵（会话跨密级泄漏 = 本阶段最高危风险）集中在 W41 独立拆掉。
6. **UI 在 API 贯通后、轻周独享**：T15 前端聊天面单独占 W43（含 preview 闭环与三角色 × 双视口验收，隐性缓冲）；原 2026-W47 锚点两项（e2e / 模板评估）重锚后落 W44；`--real` 质量轨定锚 W45。
7. **批次门槛与让位序**：T20（PlanExecute）启动条件 = T19 `--real` 质量达标；T18（模板注册表实现）启动条件 = T17 评估结论为「轻量实现」；超载让位序 T21 → T20 → T18，承诺批次不带病增量。

## 关键决策（8 个决策点已拍板）

1. **工具调用集成：原生 function calling，不做 prompt-based 文本协议**。`LLMProvider.complete` 增可选 `tools` 参数（`ToolSpec`/`ToolCall` frozen dataclass，`LLMResponse` 增可选 `tool_calls`），LiteLLM 走原生 `tools=` / `tool_calls` 透传；再经约百行内 `providers/langgraph_adapter.py`（`BaseChatModel` 子类，仅依赖 langchain-core）桥接 LangGraph。理由：**桩可测性是硬约束**——StubLLM 按 `[AGENT:*]` 标记脚本化 `tool_calls` 序列，循环完全确定、离线可断言轨迹；文本协议解析脆弱且桩只能脚本化字符串，失真最重；LiteLLM 主流后端原生支持 OpenAI 格式 `tools`。显式避开两条坑：已弃用的 `create_react_agent`（LangGraph 2.0 移除）与 `langchain-litellm` 重复包装。适配器委派而非旁落 LLM 所有权，旧调用面（`tools` 默认 `None`）零变化。文本协议仅留痕为「后端无原生 tool calling」时的降级预案，不实现。
2. **checkpointer 双轨：离线测试 InMemorySaver；运行态与 `@pytest.mark.db` 集成测试用官方 AsyncPostgresSaver**（extra `langgraph-checkpoint-postgres`），独立 `psycopg[binary]` `AsyncConnectionPool`（与 SQLAlchemy engine 分池、指向同一 PG），FastAPI lifespan 内 `setup()` + 保活，`thread_id` = 会话 id。**不自写 SQLAlchemy checkpointer**。理由：项目测试与运行皆真 PG（P4.5 起无 SQLite 模式），多轮状态必须持久、可审计、重启不丢；官方 psycopg saver 是生产参考实现（有 conformance 套件背书），自写需自背一致性维护成本。已知坑显式检查单：忘 `setup()` / `autocommit=True` / `dict_row`、`from_conn_string` 上下文提前退出、异步 saver 配同步 `invoke` 静默挂死、内部 `asyncio.Lock` 串行化（单用户规模接受，留痕锚点 2026-W49 压测批）。
3. **三模式归宿：ReAct ✅ 必做（v1 主链，手写 StateGraph）；PlanExecute 🔁 可选（批 2，启动门槛 = ReAct `--real` 质量证据达标，共享状态 / 工具节点 / 预算帽，加 planner/executor/replan）；ReWOO ⏸ 暂缓（留痕，锚点 2026-W49 随 P9 模型层清单重评；`AgentMode` 枚举预留 `rewoo` 值，契约留门）**。理由：风险前置要求单模式一条主链先打通「工具定义 → 权限门控 → 多轮状态 → 前端」；ReAct 是标准工具循环形状、两节点环最小；PlanExecute 计划可检查可回放、契合审计文化，但以质量门槛门控而非无条件排期；ReWOO 执行中无法按观察自适应、计划失误链式失败、需 `#E` 变量绑定 DAG 独立基建，当前分析场景无批量并行证据需求。
4. **新 ORM 三表 + job 范式**：`AgentSession`（owner + 五 access 字段默认 personal + 创建时 clearance/scope 快照 + mode）/ `AgentMessage`（role / content / 引用指针，内容不得含高于会话密级的证据明文）/ `AgentRun`（轨迹 JSON + usage + 状态）；`models.py` 集中注册 + `db/migrate.py` 幂等补列。**ORM 是 system of record，checkpoint 只承载执行态**。AccessContext 不入 checkpoint 状态（经 config 带外、每回合重建）；读会话须当前 clearance ≥ 建时（密级不洗白）+ 当前 AccessContext 复检。API：`POST /agent/sessions`、`POST /{id}/runs`（`Job.task_type="agent"`：`BackgroundTasks` + `session_factory` 注入 + barrier）、`GET messages`；**v1 无流式**。理由：checkpoint 格式不可查询 / 不可审计 / 无法 `visible_to` 过滤，不能当系统记录；同步回合方案被否——真模型回合动辄数十秒，同步 HTTP 时延难有界；AccessContext 带外防密级快照序列化漂移。
5. **团队级自定义分析模板注册表：先评估后决定**——评估 ✅ 必做（T17，锚点 2026-W47 → 重锚 2026-W44），实现 🔁 评估门控（T18）。评估口径五项：① Agent 消费是否依赖注册表（BUILTIN 9 类已可经 `run_analysis` 消费，借 `config/golden_analysis.yaml` 案例量化覆盖缺口）；② `jsonschema` 完整校验与 `sanitize_user_schema` 衔接（拒 `$ref` / 递归 / 超深 / 超大）；③ 持久化形态（纯 YAML 仿 `ecl/extraction_template.py` `ExtractionTemplateRegistry` + 每调用点重建、无 ORM 无持久化权限，vs 升 ORM + 五 access 字段 + team scope，`ChunkRecordORM` 先例）；④ 与内置九类冲突语义（覆盖 / 禁止）；⑤ 多用户写审计需求。产出备忘录 + 决策记录；结论为缓则整体顺延 P9 留痕。理由：P6 移交原文即「评估」而非实现；直接上 ORM 有范围膨胀风险；重锚理由同重锚说明。`jsonschema` 若需要，走 extra + 懒加载 + 缺依赖友好报错。
6. **e2e 补建：建 `frontend/e2e/` 六组用例**——登录（错 / 对凭据）、QA 冒烟（三模式 + 来源展开）、分析（提交 → 轮询 → 报告）、admin 越权 403 探测、agent（会话多轮 + 工具轨迹）、logout + cookie 失效断言；双视口（现有 `playwright.config.ts` 已配）。本地 `npm run e2e` 绿（前置 `serve --seed-demo --port 8200`，README 固化启动顺序 + `/healthz` 等待）；**不进 CI**（需真 PG+Neo4j，与 CI `-m "not db"` 纪律冲突），留痕锚点 2026-W49 随审计硬化重评；顺带清理 git 已追踪的 `playwright.config.js/.d.ts` 等编译产物副本（见 T16）。锚点 2026-W47 → 重锚 2026-W44。理由：移交原话是「链路补建」，playwright config 已是可跑的空壳（`testDir "./e2e"` 目录缺失、`npm run e2e` 报 no tests found），补的只是目录与用例，成本低；CI 装 playwright 浏览器下载重且需真库——先进本地纪律，等证据再入 CI。
7. **工具集圈定（v1 只读 + 分析桥，写工具整体划出）**：`search_knowledge`（SearchEngine 三模式）/ `graph_neighbors`（neighbors + subgraph）/ `list_entities` / `entity_profile` / `list_documents` / `list_communities` / `get_chunk` → `query` 权限；`reports_list` / `reports_get` → `query` + 报告可见语义；`run_analysis` → `analyze`，走 job 范式异步返回 `job_id`/`report_id` 指针、不内联明文（复用 `gather_materials` / `compute_report_access_level` 纯函数，P6 语义零修改）。每工具三道闸：权限门（`list_for(access)` 预过滤）+ 参数 JSON Schema 校验 + 数据层 `visible_to`；越权与不存在返回同一错误消息（不区分、不泄漏存在性）+ 每次 `record_audit`。**`get_chunk` 必须在工具层自补 `visible_to`**——`VectorStore.get_chunks_by_ids` 接口无 access 过滤，是跨密级泄漏通道。工具只包 store 接口，不碰内存态 BM25（`api/deps.py` TODO，P9）。理由：roadmap 红线「权限内行动、越权工具结果不得泄漏存在性」落到派发层与数据层双保险——注入防御不寄托提示词；只读起步把提示注入放大面压到最小；`run_analysis` 兑现 P6 移交承诺（报告契约被 Agent 直接消费、无返工），异步指针避免分析耗时阻塞循环。
8. **依赖形态：新增 extra `agent`**：`langgraph>=1.2,<2` + `langgraph-checkpoint-postgres>=3.1.1,<4`（下限 = CVE-2026-71433 修复版，见 T2 调研证据）+ `psycopg[binary]>=3.2,<3.4` + `psycopg-pool>=3.2,<3.4`；运行时懒导入 + 缺依赖友好报错（503 同 ingest 惯例）；CI 后端 job 改 `uv sync --frozen --extra agent`，保证 agent 离线测试（核心能力）CI 可跑。langchain-core 由 langgraph 硬依赖带入（`>=1.4.7,<2`），**显式不装 langchain / langchain-community / langchain-litellm**（与 P6 拒 LangChain 主体一致）。litellm `>=1.85,<1.91` 不动。钉版纪律同 litellm：**禁裸 psycopg**（Windows 无系统 libpq）与 `psycopg[c]`（无 Windows wheel 触发源码编译）；checkpoint-postgres 自身依赖裸 psycopg，须以 `[binary]` 覆盖；安装前先审 `uv lock` 的 httpx / requests / pydantic 解析。理由：项目纪律——重型依赖一律走 `optional-dependencies` + 懒加载（persistence / analysis extra 先例，即使是运行必需）；langgraph 全链虽为纯 Python wheel（orjson / ormsgpack / psycopg[binary] 均有 cp311 win_amd64 预编译），但依赖树不小，主依赖会强迫所有安装者吃下；extra + CI 装上两头兼顾；LangChain 边界集中在一个适配器文件，可审计、可替换。

## 前置条件（开工前确认）

- [x] P6 合入基线：main 含 PR #11（`5c0bc0b`），全量基线 1015 passed + 1 skipped、前端 vitest 62 passed（2026-08-30 合入时验证）。
- [x] 本地 `uv run pytest -v` 全量回归绿确认（真实 PG+pgvector+Neo4j，`.env` 驱动）；`uv sync --extra persistence` 已装（neo4j / pgvector，DB 测试必需）。
- [x] litellm 钉版 `>=1.85,<1.91` 保持不变（≥1.93 无 Windows 预编译 wheel），本阶段**不升级**。
- [x] 前端三件套基线绿：`npm run lint && npm run test && npm run build`；`.nvmrc` Node 22；`preview_start frontend-dev`（5173）可用。
- [x] dev 演示环境：`serve --seed-demo --port 8200` 可用——当前被 `demo_seed` 缺口卡住，T1 修复后即恢复（preview 闭环与 e2e 的硬前置）；三角色账号按 [[docs/plans/phases/P6-progress|P6 交接]] 口径重建（密码不入库，用完即弃）。
- [x] GLM-EYE / MiniMax 识图服务状态：**2026-08-31 用户指令停用 GLM-EYE，识图全用原生视觉**——W38 锚点注销，不阻塞任何事项。
- [x] `--real` 质量补跑至少一路可用模型（用户本机 LM Studio / ollama 或 API），且该后端支持原生 tool calls；不支持则换模型并留痕（不做文本协议降级）。
- [x] 重锚规则确认：多轮状态并入 P7 本体、模板评估 W47→W44、e2e W47→W44、`--real` 定锚 W45；W36–W48 窗口 10-15h/周、周日回顾节奏。

## 架构

### 域分层总览

```text
src/calliodesmo/
├── interfaces/agent.py            # 对外契约：AgentMode / ToolSpec / ToolCall / ToolResult /
│                                  #   TurnResult / AgentTool 协议 / AgentEngine(ABC)（新增可插拔抽象）
├── agent/                         # P7 Agent 域（新增）
│   ├── errors.py                  # 统一工具错误（越权与不存在同一消息，不泄漏存在性）
│   ├── registry.py                # DefaultToolRegistry：list_for(access) 预过滤 / get / dispatch + 参数 schema 校验 + 审计钩子
│   ├── tools/                     # search / graph / entities / documents / communities / analysis 桥（各文件独立）
│   ├── budget.py                  # 三重预算帽：步数 / token / 挂钟 → 强制收敛（纯函数 + 策略）
│   ├── graph.py                   # 手写 ReAct StateGraph（model 节点 → should_continue 条件边 → 工具节点 → 回 model）
│   ├── access.py                  # 会话复检 verify_access（密级不洗白）+ 落库前密级断言钩子
│   ├── history.py                 # 滑动窗口截断（保留系统提示 + 最近 N 回合 + 截断 warning，纯函数）
│   ├── checkpoint.py              # build_checkpointer：InMemory | AsyncPostgresSaver（独立 psycopg[binary] 池，懒导入）
│   ├── factory.py                 # build_agent_engine：复用 retrieval/factory.build_llm_provider 路由规则
│   └── job_worker.py              # run_agent_job(job_id, *, engine, session_factory, barrier=None)
├── providers/
│   ├── stub_llm.py                # 扩 [AGENT:<script>] 标记分发（脚本化 tool_calls 序列）
│   └── langgraph_adapter.py       # BaseChatModel 子类：委派 LLMProvider.complete(tools=)，仅依赖 langchain-core
├── api/agent.py                   # /agent 路由（新增，根 + /api 前缀双挂，同既有路由范式）
├── db/models_agent.py             # AgentSession / AgentMessage / AgentRun（新增，三维权限字段）
├── eval/agent_metrics.py          # tool_set_match / trajectory_valid / no_forbidden_leak / budget_within（纯函数）
└── models.py                      # 集中导入注册三张新表（漏注册 → 测试 schema 缺表）
config/golden_agent.yaml           # agent golden 轨迹集（场景 ≥6 例：单工具 / 多工具 / 无工具直答 / 越权探针 ≥3 例 / 注入探针）
scripts/eval_agent.py              # 三用法：--dump-golden / 默认离线桩落盘 agent-regression.json / --real
frontend/
├── src/features/agent/            # AgentPage / SessionList / ChatView / ToolTrace / api.ts / useAgent.ts
└── e2e/                           # 六组 spec（auth / qa / analysis / admin / agent / logout，本阶段补建）
```

### interfaces/agent.py 形状（Task 5 冻结）

```python
class AgentMode(enum.StrEnum):
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"
    REWOO = "rewoo"  # 预留值（⏸ 暂缓，锚点 2026-W49 重评，见决策 3）


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema（注册表入参校验与 provider tools= 共用同一份）


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    name: str
    ok: bool
    output: str  # 截断 + 引注口径，入 prompt 前沿用 P6 sanitize 纪律
    error: str | None  # 越权与不存在同一文案（契约测试锁定不可区分）


@dataclass(frozen=True)
class TurnResult:
    answer: str
    tool_trace: tuple[tuple[ToolCall, ToolResult], ...]
    steps: int
    usage: dict[str, int]
    warnings: list[str]  # budget_exceeded / history_truncated ...
    status: str  # ok | budget_exceeded | failed


class AgentTool(Protocol):
    spec: ToolSpec
    required_permission: Permission

    async def run(self, arguments: dict, *, access: AccessContext) -> str: ...


class AgentEngine(ABC):
    mode: AgentMode

    @abstractmethod
    async def run_turn(
        self, *, question: str, thread_id: str, access: AccessContext
    ) -> TurnResult: ...
```

**API 只依赖抽象不见 LangGraph**：`interfaces/agent.py` 与 `agent/registry.py` / `agent/tools/` 不导入 langgraph；LangGraph 边界集中在 `agent/graph.py` + `providers/langgraph_adapter.py` 两个文件，可审计、可替换。`access` 入参供工具调用与审计溯源消费；`thread_id` = 会话 id（checkpoint 与 ORM 对齐）。

### 工具清单与三道闸（决策 7）

| 工具 | 上游依赖 | 权限 | 说明 |
|---|---|---|---|
| `search_knowledge` | `SearchEngine.query`（native/local/global） | `query` | access 全程传参；输出截断 + `[chunk_id]` 引注口径 |
| `graph_neighbors` | `GraphStore.neighbors` / `subgraph` | `query` | hops / limit 入参走 schema 校验 |
| `list_entities` | `GraphStore.list_entities` | `query` | visible_to 在 store 侧 |
| `entity_profile` | `ProfileCardStore.get` | `query` | 仅 InMemory 实现现状沿用（P9 改 PG 同批重评） |
| `list_documents` | `VectorStore.list_chunks` 按 doc 聚合 | `query` | 出参截断 |
| `list_communities` | `CommunityStore.list_communities` | `query` | |
| `get_chunk` | `VectorStore.get_chunks_by_ids` | `query` | **接口无 access 过滤，工具层必须自补 `visible_to` 逐条复核**（红线） |
| `reports_list` / `reports_get` | `AnalysisReportStore` 可见语义 | `query` | 不可见返回 `None` → 统一工具错误消息 |
| `run_analysis` | `AnalysisEngine` + `gather_materials` + job 范式 | `analyze` | 返回 `job_id`/`report_id` 指针，不内联明文 |

三道闸：① 权限门——`registry.list_for(access)` 预过滤，无权限工具对模型不可见；② 参数门——按 `ToolSpec.parameters` JSON Schema 校验，拒畸形入参；③ 数据门——store 侧 `visible_to`（`get_chunk` 工具层补偿）。越权 / 不存在同一错误消息 + 每次 `record_audit`。**注入防御不寄托提示词**：prompt 不执行来自工具结果的指令，工具输出截断与引注；注入探针样本断言「工具未被诱导」（零容忍，见 T9/T12）。

### ReAct 状态图（Task 10，手写 StateGraph）

```text
AgentState(messages reducer + budget 计数)
  → model 节点（适配器后端：LiteLLM 真模型 / StubLLM 脚本）
  → should_continue 条件边：有 tool_calls → 工具节点；否则 → END
  → 工具节点（注册表派发 + ToolResult 回写 + 轨迹累计）→ 回 model
  → 预算超限（步数 / token / 挂钟任一）→ 强制收敛节点：输出「部分结果 + 说明」+ warning("budget_exceeded")
```

- **AccessContext 经 config `configurable` 带外传参，不入 checkpoint 状态**（防密级快照序列化漂移）；每回合由 worker 重建。
- 不用已弃用的 `create_react_agent`（LangGraph 2.0 移除），不引 `create_agent` / middleware；`StateGraph` / 节点 / 边原语 1.0 GA 后稳定，手写可控可审计。

### 会话数据模型与 checkpointer（决策 2/4）

| 表 | 关键列 | 说明 |
|---|---|---|
| `AgentSession` | `id` PK · `owner_id` index · `mode` · `label` · 五 access 字段（默认 personal）· `clearance_at_create` / `scope_at_create` 快照 · `created_at` | system of record 之一；`visible_to` 鸭子类型直接生效 |
| `AgentMessage` | `id` PK · `session_id` index · `role` · `content` · `run_id` 可空 · `created_at` | 内容不得含高于会话密级的证据明文（落库前密级断言钩子） |
| `AgentRun` | `id` PK · `session_id` index · `status`（pending/running/succeeded/failed）· `tool_trace` JSON · `usage` JSON · `steps` · `error` · `created_at` | 轨迹供前端折叠展示与评估消费 |

- `db/models_agent.py` 三表，`models.py` 无条件集中注册，`db/migrate.py` 幂等补列挂 `db init`（`@pytest.mark.db` 测试）。
- checkpoint 只承载执行态：离线 `InMemorySaver`；运行态 `AsyncPostgresSaver` + 独立 `psycopg[binary]` `AsyncConnectionPool`（`autocommit=True` + `dict_row`，与 SQLAlchemy engine 分池、指向同一 PG），FastAPI lifespan 内 `setup()` + 保活 + 关闭回收；图调用一律 `ainvoke`（异步 saver 配同步 `invoke` 静默挂死）。
- **读会话复检**（T12）：当前 `clearance ≥ clearance_at_create`（密级不洗白）+ 当前 AccessContext `visible_to` 复检，不通过 404 + 审计；跨用户会话 404 不泄漏存在性。

### API 契约（api/agent.py，prefix="/agent"，根 + /api 双挂）

| 端点 | 请求 | 响应 | 守卫 |
|---|---|---|---|
| `POST /agent/sessions` | `{mode="react", label?}` | `201 SessionOut` | QUERY |
| `GET /agent/sessions?limit=20&offset=0` | — | `{items, total}` | QUERY + visible_to 三维过滤 |
| `POST /agent/sessions/{id}/runs` | `RunRequest{question}` | `202 {job_id, status}` | QUERY + 会话可见（不可见 → 404） |
| `GET /agent/sessions/{id}/messages` | — | 消息列表（含 run 指针 / 轨迹指针） | 不可见 → 404（不泄漏存在性） |
| `GET /jobs/{id}` | —（复用 `api/jobs.py`，过滤 / 鉴权不变） | `JobOut`（`task_type="agent"`，result 最小指针） | job 所属用户 |

错误码一览：401 未认证；403 缺 `query`；404 会话不可见或不存在（同一文案）；400 请求体校验失败 / 未注册 mode；422 pydantic 校验失败；503 模型未配置或缺 key 或 agent extra 缺依赖（`RuntimeError`，同 ingest / analyze 惯例）。

**审计点**（均经 `audit/service.py` `record_audit`）：`agent_session_create`（POST 请求侧）；`agent_run`（worker 终态：成功 / 失败，detail 含 steps / usage / mode）；工具调用审计在注册表派发层逐次记（`agent_tool`，含越权探测记录）。

**worker 进度档**（对齐 job 范式近似推进）：rebuild 10 → graph 50 → persist 90 → done 100。

### 配置项清单（config.py Settings，双同步 .env.example）

| 字段（`CALLIODESMO_` 前缀） | 默认值 | 用途 |
|---|---|---|
| `agent_model` | `""`（空 → 回退 `llm_model`） | Agent 用模型 |
| `agent_max_steps` | `6` | 单回合 ReAct 步数硬上限（超限强制收敛） |
| `agent_token_budget` | `32000` | 单回合 token 预算（usage 逐轮累计） |
| `agent_wall_clock_seconds` | `120` | 单回合挂钟上限 |
| `agent_history_window` | `8` | 历史窗口保留回合数（系统提示恒留 + 截断 warning） |
| `eval_agent_golden_file` | `"config/golden_agent.yaml"` | agent golden 轨迹集路径 |

### 前端数据契约（frontend/src/api/types.ts，与后端逐字段对齐）

```ts
export type AgentMode = "react" | "plan_execute";  // rewoo 预留不渲染
export interface AgentSessionOut {
  id: string; mode: AgentMode; label: string; access_level: string;
  library_scope: string; created_at: string;
}
export interface AgentMessageOut {
  id: string; session_id: string; role: "user" | "assistant";
  content: string; run_id: string | null; created_at: string;
}
export interface AgentRunRequest { question: string; }
// 复用 PERMISSIONS.QUERY 门控（导航项 /app/agent：access.canQuery，克隆分析页隐藏式门控）；
// JobOut 消费侧已含 task_type / report_id（P6 扩展），agent 任务 report_id 恒 null，轨迹经 messages/runs 指针。
```

UI 克隆既有资产，**不新增前端依赖**：① 会话侧栏克隆 `ReportsHistory` 列表 + `useIngest` 轮询范式（`useMutation` POST run → 202 + job_id，`useQuery` 轮询 `refetchInterval` 函数式：非终态 1200ms、终态返回 `false` 停）；② 工具轨迹折叠克隆 `ReportViewer` 证据 chips 展开范式；③ 停止按钮 = 取消标记 + worker 自检（不做硬杀）；④ v1 无流式，消息追加按轮询刷新。

### 纯函数与可测性纪律

`budget` 三重帽判定 / `history` 窗口截断 / `eval/agent_metrics.py` 全部指标 / 注册表 `list_for` 预过滤 / 统一错误文案构造——全部无夹具可单测，保 CI（`-m "not db"`）覆盖；agent 域离线测试（图循环 / 工具契约 / 适配器）**不依赖 db**（InMemorySaver + 内存 stores + StubLLM）；连 PG 的（会话持久化 / AsyncPostgresSaver 集成 / API 全链 / worker）打 `@pytest.mark.db` 走真 PG + `calliodesmo_test` schema 每测 TRUNCATE。维持串行测试（neo4j 夹具全图清空，禁 `pytest -n`）。

## 技术栈（追加式）

| 类别 | 追加 | 说明 |
|:--|:--|:--|
| Agent 编排 | extra `agent`：`langgraph>=1.2,<2`（现 1.2.11，1.0 GA 后原语稳定） | 手写 StateGraph；不用 `create_react_agent`（2.0 移除）/ `create_agent` / middleware；langchain-core 由硬依赖带入，不装 langchain 主体 |
| 状态持久化 | `langgraph-checkpoint-postgres>=3.1.1,<4` + `psycopg[binary]>=3.2,<3.4` + `psycopg-pool>=3.2,<3.4` | 禁裸 psycopg（Windows 无 libpq）与 `psycopg[c]`（无 Windows wheel）；checkpoint-postgres 依赖裸 psycopg 须 `[binary]` 覆盖；orjson / ormsgpack 均有 cp311 win_amd64 wheel |
| 工具调用 | LiteLLM 原生 OpenAI 格式 `tools` / `tool_calls`（钉版 `>=1.85,<1.91` 不动） | 文本协议仅留痕为降级预案；`--real` 预检后端能力 |
| 桩 | StubLLM `[AGENT:*]` 标记脚本化 `tool_calls` 序列 | 与 `[ANALYSIS:*]` 分发同范式；未知标记显式 `ValueError` |
| 评估 | 轨迹指标（工具集匹配 / 轨迹有效 / 边界泄漏=0 / 预算内）+ golden 轨迹集 | 离线只证结构；`--real` 才证质量，口径与 P5/P6 一致 |
| 前端 | 无新依赖（克隆既有模式） | e2e 用既有 devDependency `@playwright/test ^1.49` |
| 依赖纪律 | 无新主依赖 | `uv sync` 默认不装 `agent` extra；CI 后端 job 装（核心能力离线测试进 CI）；懒导入 + 缺依赖友好报错 |

---

## Task 1: 前置批——清 W36/W37 移交操作债 ✅ 必做

**目标：** P7 开工前一次清掉四条移交尾巴（仿 P6 Task 1 前置批范式）：GLM-EYE 截图复跑、`demo_seed` 递归 glob + 缓存失效、移动端折叠侧栏、logout 方法不匹配 + cookie 失效。`demo_seed` 修复直接恢复 `serve --seed-demo`，是 P7 preview 闭环与 e2e 的硬前置。

**Files:** 改 `src/calliodesmo/ecl/demo_seed.py`（`_list_demo_files` 改 `rglob` + seed-cache 失效标记）· 改 `frontend/src/features/auth/AuthContext.tsx`（logout 改 `api.post`）· 改 `frontend/src/App.tsx`（`<nav className="flex w-56 shrink-0 ...">` 固定宽改 `<md` 折叠 / 抽屉）· 改 `docs/verification/P6-verification.md`（GLM-EYE 复跑勾除 / 留痕）。

- [x] **Step 1:** 写失败测试：`demo_seed` 嵌套语料递归发现（`_list_demo_files` 改 `rglob`）+ seed-cache 失效标记（记 team_id / demo_dir 哈希，漂移即重建，旧 `.stale` 缓存迁移）。
- [x] **Step 2:** 跑确认失败 → 实现 → 跑绿（db 夹具 + `serve --seed-demo` 冒烟不再 FileNotFoundError）。
- [x] **Step 3:** logout 修复：前端 `api.del("/auth/logout")` 改 `api.post`（后端 `api/app.py:103` 为 `POST`）+ 同验 httpOnly cookie 失效（登出后持旧 cookie 过 `/auth/me` 401）。
- [x] **Step 4:** 前端移动端侧栏：`App.tsx` 固定 `w-56` nav 改 `<md` 折叠 / 抽屉导航 → 三件套绿 + `preview_resize` mobile 视口验收（全站页面同症一并解除）。
- [x] **Step 5:** 截图识图归档；**2026-08-31 用户指令：GLM-EYE 停用，全用原生视觉**（原 W38 复跑锚点注销）。
- [x] **Step 6:** 提交（分提交）：`fix(ecl): demo_seed 递归与缓存失效` / `fix(auth): logout 方法与 cookie 失效对齐` / `feat(frontend): 移动端折叠侧栏`。

---

## Task 2: 依赖引入与钉版验证——extra agent（langgraph 家族）+ CI 接线 ✅ 必做

**目标：** 风险前置：langgraph 家族进 extra `agent` 并钉版，验证 Windows wheel 与 uv 解析，CI 挂 agent 离线测试——把最可能翻车的依赖未知数最早拆掉。

**Files:** 改 `pyproject.toml`（extra `agent`）· 改 `.github/workflows/ci.yml`（后端 job `uv sync --frozen --extra agent`）· 新 `tests/test_agent_deps.py`。

- [x] **Step 1:** 查证（tavily）：`langgraph` / `langgraph-checkpoint-postgres` / `psycopg[binary]` 稳定版与 cp311 win_amd64 wheel 矩阵，理由落本计划文档。
- [x] **Step 2:** 写失败测试：agent extra 懒导入守卫（缺依赖友好报错；装齐后 `import langgraph` / `AsyncPostgresSaver` 成功 + 版本断言）。
- [x] **Step 3:** 跑确认失败 → 改 `pyproject.toml`：`agent = ["langgraph>=1.2,<2", "langgraph-checkpoint-postgres>=3.1.1,<4", "psycopg[binary]>=3.2,<3.4", "psycopg-pool>=3.2,<3.4"]`（下限 3.1.1 = CVE-2026-71433 修复版，见 T2 调研证据；注释写明不装 langchain 主体；禁裸 psycopg 与 `psycopg[c]`）。
- [x] **Step 4:** `uv lock` + `uv sync --extra agent`：确认 orjson / ormsgpack / psycopg 全 wheel 安装、无源码编译；审 httpx / requests / pydantic 与 litellm 解析无冲突。
- [x] **Step 5:** CI 后端 job 改 `uv sync --frozen --extra agent`（保持 `pytest -m "not db"`）→ 跑绿：ruff + pytest 双绿。
- [x] **Step 6:** 提交：`chore(deps): 引入 agent extra 并钉版（langgraph>=1.2,<2，P7 Agent 模式）`。

> [!note] T2 调研证据（2026-08-31 依赖调研工作流：PyPI JSON/文件列表 + 官方文档对抗性核对）
> - `langgraph` 现稳定 1.2.x（调研时点 1.2.11，本机 lock 解析 1.2.9），纯 Python wheel；`>=1.2,<2` 成立；`create_react_agent` 弃用属实（1.0 起每次调用发 DeprecationWarning，2.0 移除）——手写 StateGraph 决策不变。
> - `langgraph-checkpoint-postgres` 现稳定 3.1.2；**下限抬至 >=3.1.1**：CVE-2026-71433 / GHSA-47pj-3jcm-6whg（namespace 前缀越段读取，多租户/scope 隔离实质影响），3.1.1 为修复版。
> - `psycopg[binary]` 3.3.4 有 cp311 win_amd64 wheel 且与 psycopg 同版锁定；`psycopg-pool` 3.3.1；均加 `<3.4` 上限。该包自身依赖**裸 psycopg**，extra 须以 `[binary]` 覆盖（本机 lock 已验：psycopg-binary==psycopg==3.3.4）。
> - 依赖树 C 扩展（xxhash / uuid-utils / ormsgpack / orjson / pydantic-core）全有 cp311 win_amd64 wheel，零源码编译；与 litellm（lock 1.90.6，钉版区间内）/ pydantic / httpx 解析零冲突。
> - AsyncPostgresSaver 内部 `asyncio.Lock` 串行化为源码级事实（单用户规模接受，留痕锚点 2026-W49 压测批，与风险表一致）。

---

## Task 3: LLMProvider 原生工具调用契约扩展 ✅ 必做

**目标：** `complete()` 以可选参数方式扩展原生 function calling 契约，纯文本路径零变化，全量回归不低于 1015 passed。

**Files:** 改 `src/calliodesmo/interfaces/llm.py`（`ToolSpec` / `ToolCall` frozen dataclass + `LLMMessage` 可选 `tool_calls` / `tool_call_id` + `LLMResponse` 可选 `tool_calls` + `complete(..., tools=None)`）· 改 `src/calliodesmo/providers/litellm_provider.py`（`acompletion(tools=…)` 透传与解析）· 测试扩展。

- [x] **Step 1:** 写失败测试：`ToolSpec(name/description/parameters)` 与 `ToolCall(id/name/arguments)` frozen 结构 + `complete(messages, tools=None)` 契约 + 后端不支持时的友好语义。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现：interfaces 数据结构与签名扩展（默认 `None` 保旧调用面零变化）；`LiteLLMProvider` OpenAI 格式透传并解析回 `tool_calls`（usage 口径不变）。
- [x] **Step 4:** 跑绿：`sys.modules` 桩 litellm 断言参数映射与解析；全量回归不低于基线 1015 passed。
- [x] **Step 5:** 提交：`feat(interfaces): LLMProvider 扩展原生工具调用契约`。

---

## Task 4: StubLLM [AGENT:*] 脚本化工具序列分支 ✅ 必做

**目标：** 离线桩具备确定性驱动工具调用循环的能力——全部 agent 测试的地基；口径与 P6 分析分支一致（未知标记显式 `ValueError`，不静默回退）。

**Files:** 改 `src/calliodesmo/providers/stub_llm.py` · 测试 `tests/test_stub_llm.py` 扩展。

- [x] **Step 1:** 写失败测试：`[AGENT:<script>]` 标记分发脚本化 `tool_calls` 序列（第一步调 `search_knowledge`、喂回工具结果后第二步收尾）；按 messages 中已有 tool 结果判定步序（纯函数无状态）；未知标记 `ValueError`。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现：`_AGENT_PAYLOADS` 查表 + 多轮分发逻辑（既有抽取 / 分析分发优先级不动）；三个基线场景：两步检索 / 越权工具探测（脚本化调用未授权工具）/ 证据不足直答。
- [x] **Step 4:** 跑绿：桩单测 + 既有抽取 / 分析桩回归零回归。
- [x] **Step 5:** 提交：`feat(providers): StubLLM 支持 AGENT 标记脚本化工具序列`。

---

## Task 5: 工具契约——interfaces/agent.py 冻结 + 注册表 + 三维权限门控 ✅ 必做

**目标：** 「权限内行动」红线落成代码契约：一次性冻结 agent 域契约（引擎无关可插拔，LangGraph 仅为实现细节）；越权与不存在同一错误语义不泄漏存在性 + 每次调用留审计。

**Files:** 新 `src/calliodesmo/interfaces/agent.py` · `src/calliodesmo/agent/registry.py` · `src/calliodesmo/agent/errors.py` · 测试 `tests/agent/test_registry.py`。

- [x] **Step 1:** 写失败测试：`ToolSpec` / `ToolCall` / `ToolResult` / `TurnResult` frozen 结构 + `AgentTool` 协议 + `ToolRegistry`（`list_for` / `get` / `dispatch`）+ `AgentEngine` ABC + `AgentMode` 枚举（预留 `rewoo` 值）。
- [x] **Step 2:** 写失败测试：越权 dispatch 与不存在工具的错误文本不可区分 + `record_audit` 被调。
- [x] **Step 3:** 跑确认失败 → 实现：`interfaces/agent.py` 契约 + `DefaultToolRegistry`（权限门 `list_for(access)` 预过滤 + 参数 JSON Schema 校验拒畸形入参）+ 审计钩子。
- [x] **Step 4:** 跑绿：权限矩阵参数化（三角色 × 四密级 × 三 scope，对齐 `DEFAULT_ROLE_PERMISSIONS`）+ 越权探测用例。
- [x] **Step 5:** 提交：`feat(agent): 冻结 agent 域契约、工具注册表与三维权限门控`。

---

## Task 6: BaseChatModel 适配器——LLMProvider → LangGraph 桥 ✅ 必做

**目标：** 自有 `LLMProvider` 无缝进入 LangGraph 消息模型（`AIMessage.tool_calls`），LLM 所有权不旁落；StubLLM 作适配器后端即可离线跑通两回合工具循环。

**Files:** 新 `src/calliodesmo/providers/langgraph_adapter.py` · 测试 `tests/test_langgraph_adapter.py`。

- [x] **Step 1:** 写失败测试：适配器 `_agenerate` 委派 `LLMProvider.complete(tools=)`；`bind_tools` 只存 OpenAI schema 并在调用时透传；`LLMResponse` → `AIMessage(tool_calls)` 映射；懒导入缺 extra 友好报错。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现：`BaseChatModel` 子类（仅依赖 langchain-core，不引 langchain 主体）。
- [x] **Step 4:** 跑绿：StubLLM + 适配器 + langgraph `ToolNode` 接线两回合工具循环，断言 id / name / args 映射无损（InMemorySaver）。
- [x] **Step 5:** 提交：`feat(providers): LangGraph BaseChatModel 适配器委派自有 LLMProvider`。

---

## Task 7: 第一批工具——只读检索 / 图谱 / 实体 / 文档 / 社区 ✅ 必做

**目标：** 平台读能力包装成权限内工具，数据一律经 store 侧 `visible_to` 过滤（纵深防御不寄托提示词）；`get_chunk` 显式补偿接口缺口（防跨密级泄漏通道）。

**Files:** 新 `src/calliodesmo/agent/tools/{search,graph,entities,documents,communities}.py` · 测试 `tests/agent/test_tools_read.py`。

- [x] **Step 1:** 写失败测试：`search_knowledge` 委派 `SearchEngine.query`（三模式 + access 全程传参）；`graph_neighbors`（neighbors / subgraph）与 `list_entities` 传 access。
- [x] **Step 2:** 跑确认失败 → 实现检索 / 图谱 / 实体工具（输出截断 + 引注口径）。
- [x] **Step 3:** 写失败测试 → 实现 `get_chunk`（`get_chunks_by_ids` 无 access 过滤，工具层必须自补 `visible_to` 逐条复核）+ `list_documents` + `list_communities`。
- [x] **Step 4:** 跑绿：逐工具输入映射与输出结构断言（契约先于实现保可插拔）+ clearance / scope 过滤矩阵（越权不泄漏存在性）。
- [x] **Step 5:** 提交：`feat(agent): 第一批只读工具（检索/图谱/实体/文档/社区）`。

---

## Task 8: 第二批工具——分析桥（reports + run_analysis）✅ 必做

**目标：** P6 报告契约与任务注册表被 Agent 直接消费、无返工（移交承诺兑现）；`run_analysis` 走异步 job 指针返回，不内联明文。

**Files:** 新 `src/calliodesmo/agent/tools/analysis.py` · 测试 `tests/agent/test_tools_analysis.py`。

- [x] **Step 1:** 写失败测试：`reports_list` / `reports_get` 复用 `AnalysisReportStore` 可见语义（不可见返回 `None` → 统一工具错误消息）。
- [x] **Step 2:** 写失败测试：`run_analysis` 需 `analyze` 权限（无权限路径用自定义无 ANALYZE 的 AccessContext 夹具——三标准角色均含 ANALYZE），产出 `job_id` / `report_id` 指针（`Job.task_type="analyze"` 范式）。
- [x] **Step 3:** 跑确认失败 → 实现：组 `AnalysisSpec` → `gather_materials`（`visible_to` 材料红线）+ `compute_report_access_level` 纯函数复用（经工厂装配，不直调 `api/deps`）。
- [x] **Step 4:** 跑绿：桩 `[ANALYSIS:*]` 标记联动（复用 P6 桩场景）+ P6 离线基线对照零回归。
- [x] **Step 5:** 提交：`feat(agent): 分析桥工具——P6 报告契约直消费`。

---

## Task 9: 评估 harness v1——agent golden 轨迹集 + 指标 + 边界探针（离线）✅ 必做

**目标：** 评估先于实现：离线证据只承诺结构与契约；轨迹指标 + 权限边界探针（泄漏=0 一票否决）+ 注入探针槽位；`--real` 开关口径与 P5/P6 一致；harness 门槛作为图实现（T10）的放行条件。

**Files:** 新 `scripts/eval_agent.py` · `config/golden_agent.yaml` · `src/calliodesmo/eval/agent_metrics.py` · 测试 `tests/test_eval_agent.py`。

- [x] **Step 1:** 写失败测试：golden 轨迹结构解析（问题 → 预期工具集 / 序列 / 步数上限 / 引用结构）与指标纯函数（`tool_set_match` / `tool_sequence_match` / `trajectory_valid` / `no_forbidden_leak` / `budget_within`）。
- [x] **Step 2:** 跑确认失败 → 实现指标 + golden 装载（场景 ≥6 例：单工具 / 多工具 / 无工具直答 / 越权探针 ≥3 例）。
- [x] **Step 3:** 实现注入探针案例槽位（语料内嵌指令诱导越权工具调用，期望零成功）+ `--real` 开关骨架。
- [x] **Step 4:** 跑绿：桩基线离线全过并落盘（CI 可跑口径；明确基线仅结构口径、桩对质量零区分度）。
- [x] **Step 5:** 提交：`feat(eval): agent golden 轨迹评估 harness（离线桩基线）`。

---

## Task 10: ReAct 手写 StateGraph + 三重预算帽 ✅ 必做

**目标：** 单模式一条主链打通多轮循环；成本失控风险以三重预算帽当场拆掉；过 T9 harness 门槛（边界探针零泄漏 + 工具集匹配达标）才放行。

**Files:** 新 `src/calliodesmo/agent/graph.py` · `src/calliodesmo/agent/budget.py` · 改 `src/calliodesmo/config.py` + `.env.example`（6 配置项）· 测试 `tests/agent/test_graph.py`。

- [x] **Step 1:** 写失败测试：StubLLM 脚本驱动两回合工具循环（InMemorySaver + `thread_id` 多轮续接），断言节点轨迹与最终 state。
- [x] **Step 2:** 跑确认失败 → 实现：`AgentState`（messages reducer）→ model 节点（适配器）→ `should_continue` 条件边 → 工具节点（注册表派发 + 轨迹回写）→ 回 model；AccessContext 经 config `configurable` 带外传参、不入 checkpoint 状态。
- [x] **Step 3:** 实现：6 个配置项一次进 Settings（`agent_model` / `agent_max_steps` 默认 6 / `agent_token_budget` / `agent_wall_clock_seconds` / `agent_history_window` / `eval_agent_golden_file`）并双同步 `.env.example`（失败测试覆盖 6 字段前缀加载与默认值）；`budget.py` 三重帽，超限强制收敛节点输出「部分结果 + 说明」+ `warning("budget_exceeded")`。
- [x] **Step 4:** 跑绿：轨迹断言（节点序列 / 消息结构 / usage 累计 / 收敛路径）+ harness 门槛回归、记录指标对比基线。
- [x] **Step 5:** 提交：`feat(agent): 手写 ReAct StateGraph 与三重预算帽`。

---

## Task 11: 会话 ORM 三表 + AsyncPostgresSaver 接线 ✅ 必做

**目标：** 多轮状态落真 PG：ORM 三表为 system of record（可查询 / 可审计 / 可 `visible_to`），AsyncPostgresSaver 只承载执行态；工程坑（setup / 生命周期 / 分池）一次做对。

**Files:** 新 `src/calliodesmo/db/models_agent.py` · 改 `src/calliodesmo/models.py`（集中注册）· 改 `src/calliodesmo/db/migrate.py` · 新 `src/calliodesmo/agent/checkpoint.py` · 改 `src/calliodesmo/api/app.py`（lifespan）· 测试 `tests/agent/test_models.py` / `tests/agent/test_checkpoint.py`。

- [x] **Step 1:** 写失败测试（`@pytest.mark.db`）：`AgentSession`（owner + 五 access 字段默认 personal + 创建时 clearance / scope 快照 + mode）/ `AgentMessage`（内容不含高于会话密级的证据明文）/ `AgentRun`（轨迹 JSON + usage + 状态）建 / 读 + migrate 幂等补列。
- [x] **Step 2:** 跑确认失败 → 实现：`db/models_agent.py` + `models.py` 集中导入注册 + `migrate.py`。
- [x] **Step 3:** 写失败测试：`build_checkpointer` 按 settings 路由 InMemory | PG；同 `thread_id` 两次调用状态互通 + `setup` 幂等（`@pytest.mark.db`，`calliodesmo_test` schema）。
- [x] **Step 4:** 实现：`checkpoint.py` 独立 `psycopg[binary]` `AsyncConnectionPool`（`autocommit=True` + `dict_row`）+ `AsyncPostgresSaver` + lifespan `setup()` 保活关闭回收；懒导入缺 extra 友好报错。
- [x] **Step 5:** 跑绿：db 集成（本地全量真库）+ 既有 job / analysis 回归不破 + CI `-m "not db"` 双绿。
- [x] **Step 6:** 提交：`feat(agent): 会话/消息/执行 ORM 与 PG checkpointer 接线`。

---

## Task 12: 多轮状态 × 三维权限交叉专项 ✅ 必做

**目标：** 最大翻车面（会话跨密级泄漏）作为独立任务拆掉，形成可回归的权限矩阵；历史窗口截断防上下文溢出；「多轮不泄漏」入回归。

**Files:** 新 `src/calliodesmo/agent/access.py` · `src/calliodesmo/agent/history.py` · 改 `config/golden_agent.yaml`（注入探针）· 测试 `tests/agent/test_permission_matrix.py`。

- [x] **Step 1:** 写失败测试：三角色 × 四密级矩阵——密级降级后读旧会话 404（密级不洗白：当前 clearance ≥ 建时）；scope 移除后不可见；跨用户会话 404 不泄漏存在性。
- [x] **Step 2:** 写失败测试：工具结果落库不含高于会话密级的明文（落库前密级断言钩子）+ 降级重验探针。
- [x] **Step 3:** 跑确认失败 → 实现：会话复检 `verify_access`（读路径以当前 AccessContext 判定，不通过即 404 + 审计）+ 落库复核。
- [x] **Step 4:** 实现：`history.py` 滑动窗口截断（保留系统提示 + 最近 `agent_history_window` 回合 + 截断 warning）。
- [x] **Step 5:** 跑绿：注入探针回归（语料内嵌指令诱导越权工具调用，期望零成功）+ 全量回归。
- [x] **Step 6:** 提交：`feat(agent): 多轮状态与三维权限交叉门控＋历史窗口管理`。

---

## Task 13: 回合编排 worker——job 范式 + AccessContext 重建 + 审计 ✅ 必做

**目标：** runs 走 `Job(task_type="agent")` 异步范式，零新范式成本；worker 自建 session 重建 AccessContext；预算超限为优雅失败并保留部分轨迹。

**Files:** 新 `src/calliodesmo/agent/job_worker.py` · `src/calliodesmo/agent/factory.py` · 测试 `tests/agent/test_job_worker.py`。

- [x] **Step 1:** 写失败测试：`run_agent_job(job_id, engine=…, session_factory=…, barrier=…)` 跑完一轮（桩驱动）+ 最终答案落 `AgentMessage` + `Job.result` 最小指针 + barrier 同步。
- [x] **Step 2:** 跑确认失败 → 实现：验 owner → 重建 AccessContext → 图 `ainvoke`（`thread_id` = 会话 id，checkpointer）→ 消息 / 执行落库 → 审计。
- [x] **Step 3:** 写失败测试：预算超限 / 失败语义（`status=failed` + 轨迹保留 + 审计）→ 实现。
- [x] **Step 4:** 跑绿：含 `@pytest.mark.db` + barrier 范式（测试内 `asyncio.Event`、`wait_for` 60s）。
- [x] **Step 5:** 提交：`feat(agent): 回合编排 worker（job 范式＋权限重建＋预算失败语义）`。

---

## Task 14: API 面——/agent sessions / runs / messages（job 范式）✅ 必做

**目标：** 对外面复刻既有 job 范式；审计与 401/403/404 矩阵齐全（不泄漏存在性）；引擎构建缺依赖 503 同 ingest 惯例。

**Files:** 新 `src/calliodesmo/api/agent.py` · 改 `src/calliodesmo/api/app.py`（根 + /api 双挂）· 改 `src/calliodesmo/api/schemas.py` · 测试 `tests/test_agent_api.py`（仿 `tests/test_analysis_api.py` 范式）。

- [x] **Step 1:** 写失败测试：`POST /agent/sessions`（QUERY 权限，无权限 403）；`POST /agent/sessions/{id}/runs` 走 `Job(task_type="agent")` pending→succeeded（barrier 同步）；`GET sessions` / `messages` 越权 404；审计 `agent_run`。
- [x] **Step 2:** 跑确认失败 → 实现路由与出入参（`SessionOut` / `RunRequest` / `RunOut` 含轨迹指针）。
- [x] **Step 3:** 实现：路由根 + `/api` 双挂；`BackgroundTasks` + `run_agent_job` 注入；引擎构建 `RuntimeError` → 503。
- [x] **Step 4:** 跑绿：401/403/404 矩阵 + 断言审计行落库 + 回归。
- [x] **Step 5:** 提交：`feat(api): Agent 会话与执行端点（job 范式＋审计）`。

---

## Task 15: 前端聊天面——会话列表 + 消息流 + 工具轨迹 + 轮询 ✅ 必做

**目标：** 多轮会话用户面落地（`/app/agent` 路由 + QUERY 隐藏式门控）；走 `preview_*` 交互验证闭环与三角色 × 双视口权限矩阵。

**Files:** 新 `frontend/src/features/agent/`（AgentPage / SessionList / ChatView / ToolTrace / api.ts / useAgent.ts + 配套 `*.test.tsx`）· 改 `frontend/src/routes.tsx` · 改 `frontend/src/App.tsx`（NavItem `access.can(PERMISSIONS.QUERY)`）· 改 `frontend/src/api/types.ts`。

- [x] **Step 1:** 写失败测试（vitest）：消息列表渲染 + 会话切换 + 轮询终态停（克隆 `useAnalysisJob` 范式：1200ms + 终态停）+ ToolTrace chip 展开。
- [x] **Step 2:** 跑确认失败 → 实现：types / api / useAgent（`useMutation` run + `useQuery` sessions / messages）+ 会话侧栏（新建 / 切换）+ 消息流 + 工具轨迹折叠展开（复用证据 chip 范式）+ 停止按钮 + 侧栏入口（QUERY 门控）。
- [x] **Step 3:** 跑绿：三件套（lint / test / build）。
- [x] **Step 4:** **preview 闭环**：`preview_start`（frontend-dev）+ 后端 `uv run calliodesmo serve --seed-demo --port 8200`；三角色登录 → 建会话 → 提问 → 轨迹展开 → 停止；`preview_console_logs`(error) + `preview_network`(4xx/5xx) 双查；越权探测（他人会话 404、无 QUERY 不渲染）+ 移动视口（T1 折叠侧栏在此复验）。
- [x] **Step 5:** GLM-EYE 截图识图（不可用则留痕回退，沿用 P6 口径）。
- [x] **Step 6:** 提交：`feat(frontend): Agent 聊天面（多轮会话＋工具轨迹透明）`。

---

## Task 16: e2e 补建——frontend/e2e smoke 套件六组（本地绿，不进 CI）✅ 必做

**目标：** `playwright.config.ts`（`testDir "./e2e"`）从空壳变为可跑链路，覆盖登录 / 问答 / 分析 / 越权 / agent 多轮 / 登出主链；锚点 2026-W47 → 重锚 W44（P6 提前闭合让渡窗口，见重锚说明）。

**Files:** 新 `frontend/e2e/{auth,qa,analysis,admin,agent,logout}.spec.ts` + `frontend/e2e/README.md` · 改 `frontend/playwright.config.ts`（如需）· 清理 git 追踪的编译产物：`playwright.config.js/.d.ts`、`vite.config.js/.d.ts`、`vitest.config.js/.d.ts`、`vitest.setup.js/.d.ts`（`postcss.config.js` 为正式配置不动）。

- [x] **Step 1:** 建 e2e 基础：`/healthz` 等待 + 登录（错误凭据提示 / 正确跳 `/app/qa`）+ qa 三模式与来源标注展开（双视口）。
- [x] **Step 2:** 写分析 spec（提交 → 轮询 → 报告可见）+ admin 越权探测（analyst 直击 `/app/admin/users` 不可达 / 403）。
- [x] **Step 3:** 写 agent spec：建会话 → 两回合 → 工具轨迹可见 + logout cookie 失效断言（登出后旧 cookie 过 `/auth/me` 401）。
- [x] **Step 4:** 跑绿：先起 `serve --seed-demo --port 8200`，再 `npm run e2e` 全过；README 固化启动顺序；明确不进 CI（留痕：锚点 2026-W49 随审计硬化重评）。
- [x] **Step 5:** 回写：更新 P6 计划范围外表与 `docs/verification/P6-verification.md` 未竟清单的 e2e 锚点注记（2026-W47→W44，与提交信息、T17 模板项回写一致）。
- [x] **Step 6:** 删除 git 追踪的配置编译产物副本 + 补 `.gitignore` 防再生。
- [x] **Step 7:** 提交：`test(frontend): 补建 e2e 冒烟链路（重锚 W47→W44）`。

---

## Task 17: 团队级分析模板注册表评估（评估口径先行）✅ 必做

**目标：** P6 移交项「评估」口径落地：先结论后实现，防评估滑向实现；锚点 2026-W47 → 重锚 W44（理由同重锚说明）。

**Files:** 新 `docs/plans/analysis-template-registry-eval.md`（评估备忘录 + 决策记录）· `scripts/probe_template_schema.py`（一次性探针脚本，不进主代码）· 改本计划与 [[docs/plans/phases/P6-llm-analysis-tasks|P6 计划]] 移交锚点注记。

- [x] **Step 1:** 列口径五项（决策 5）：① Agent 消费是否依赖注册表（BUILTIN 9 类已可经 `run_analysis` 消费，借 `config/golden_analysis.yaml` 回归案例量化覆盖缺口）；② `jsonschema` 完整校验与 `sanitize_user_schema` 衔接（拒 `$ref` / 递归 / 超深 / 超大）；③ 持久化形态（纯 YAML 仿 `ExtractionTemplateRegistry` + 每调用点重建、无 ORM，vs 升 ORM + 五 access 字段 + team scope，`ChunkRecordORM` 先例）；④ 与内置九类冲突语义（覆盖 / 禁止）；⑤ 多用户写审计需求。
- [x] **Step 2:** 小原型验证边界（一次性脚本，不进主代码；`jsonschema` 若需要走 extra + 懒加载 + 缺依赖友好报错）。
- [x] **Step 3:** 产出评估备忘录 + 决策记录（结论：直接轻量实现 / 顺延 P9，二选一并给理由）+ 回写 P6 移交锚点注记（逐处点名 P6 侧三处：P6 计划范围外表、P6 计划 Task 22 留痕、`P6-verification.md` 未竟清单）。
- [x] **Step 4:** 提交：`docs(plans): 团队级分析模板注册表评估备忘录（锚点重锚 W47→W44）`。

---

## Task 18（🔁 可选）: 按评估结论实现轻量模板注册表（评估门控）

**启用条件:** T17 结论为「YAML 轻量形态足够」则落地；否则本任务整段取消并留痕顺延（锚点移交 2026-W49）。

**Files:** 新 `src/calliodesmo/analysis/template_registry.py` · `config/analysis_templates.example.yaml` · 改 `src/calliodesmo/agent/tools/analysis.py` · 测试 `tests/test_analysis_template_registry.py`。

- [ ] 写失败测试：注册表 `get` / `get_for_access` / `from_yaml`（缺文件 → 空、重复 team → `ValueError`，仿 `ExtractionTemplateRegistry` 形状）+ `jsonschema` 校验路径。
- [ ] 跑确认失败 → 实现：注册表（依赖口径同 `ExtractionTemplateRegistry`：纯 YAML 无 ORM）+ `jsonschema` 走 extra（懒加载 + 缺依赖友好报错）。
- [ ] 实现：接入 `run_analysis`——custom 优先查团队模板（命中则注入指令 + schema 仍过 sanitize 闸门）+ 与九类内置规格冲突语义测试。
- [ ] 跑绿 + 新增配置字段（如有）双同步 `.env.example`。
- [ ] 提交：`feat(analysis): 团队级自定义分析模板注册表（轻量形态）`。

---

## Task 19: --real 质量补跑与验收 ✅ 必做

**目标：** 双轨验收质量轨：用户本机真模型跑 golden 轨迹，验证工具选择恰当性 / 答案接地 / 预算行为；报告显式声明离线桩对质量零区分度。锚点 2026-W45（就绪可提前；延误顺延 2026-W46 留痕）。

**Files:** 改 `scripts/eval_agent.py`（`--real` 实装）· 新 `docs/verification/P7-verification.md` · `docs/verification/agent-real-<模型名>.json` · 改 `docs/verification/README.md`。

- [x] **Step 1:** 预检 `--real` 环境：`.env` 模型路可用 + 后端支持原生 tool calls（不支持 → 换模型并留痕，不做文本协议降级）。
- [x] **Step 2:** 执行 `eval_agent.py --real`：采集轨迹 / 工具选择 / 引用质量 / 步数与 token 分布 / 循环稳定性。
- [x] **Step 3:** 证据落盘 `agent-real-<模型名>.json` + 三角色 × 四密级 e2e 验收复跑（含越权探测与登出）。
- [x] **Step 4:** 写 P7 验证报告（四要素：测试内容 / 技术栈 / 验证原理 / 验证过程 + Task 闭合矩阵 + 未竟清单带周次）+ 登记 `docs/verification/README.md` 索引（明确离线轨与质量轨口径差，证据文件逐件列名）。
- [x] **Step 5:** 提交：`docs(verification): P7 --real 质量证据与验证报告`。

---

## Task 20（🔁 可选）: Plan-and-Execute 可选模式（批 2，条件启动）

**启用条件:** T19 `--real` 质量证据达标（工具选择恰当、循环稳定、预算内）；不满足则顺延留痕，让位序第二（先砍 T21，再顺延本项，再砍 T18）。

**Files:** 新 `src/calliodesmo/agent/plan_graph.py` · 改 `src/calliodesmo/interfaces/agent.py`（`AgentMode.PLAN_EXECUTE` 启用）· 测试 `tests/agent/test_plan_graph.py`。

- [ ] 写失败测试：planner 出结构化计划（pydantic 模型）→ executor 逐步执行 → replan 条件边（带 `past_steps` 回 planner 或 END）；桩场景 `[AGENT:plan_two_steps]`。
- [ ] 跑确认失败 → 实现 plan-execute StateGraph（复用工具层 / 注册表 / 预算帽）。
- [ ] 跑绿：轨迹节点序断言 + 与 ReAct 对比记录（步数 / LLM 调用次数 / 轨迹可审计性）。
- [ ] API / 前端加 `react` / `plan_execute` 模式选择（沿用 MODES 分段组范式）+ `--real` 第二批证据入库。
- [ ] 提交：`feat(agent): Plan-and-Execute 可选模式（共享状态图基建）`。

---

## Task 21（🔁 可选）: 回合 SSE 流式（可选增强）

**启用条件:** 承诺批次全绿后的机动工时；预算超载时**最先让位**。

**Files:** 改 `src/calliodesmo/api/agent.py` · `src/calliodesmo/agent/job_worker.py` · 改 `frontend/src/features/agent/ChatView.tsx` · 测试。

- [ ] 写失败测试：SSE 事件序列契约（`token` / `tool_start` / `tool_end` / `done`；`tool_start` 先于 `tool_end`，`done` 携带 usage）。
- [ ] 跑确认失败 → 实现图 `astream_events` → SSE 映射（与 job 范式兼容）。
- [ ] 前端 `EventSource` 消费 + 增量渲染 → 三件套绿。
- [ ] preview 闭环验证流式体验 + 提交：`feat(agent): 回合 SSE 流式（可选增强）`。若让位：留痕验证报告未竟清单（锚点 2026-W49，随 P8/P9 清单重评）。

---

## Task 22（⏸ 暂缓）: ReWOO 归宿留痕

**目标：** roadmap 点名的三模式之一必须有明确归宿与重评锚点，不留隐式尾巴。

- [x] 本计划「范围外」表与「暂缓与移交记录」已留痕暂缓理由：`#E` 变量绑定 DAG 基建成本 > 当前收益；执行中无法按观察自适应、计划失误链式失败；分析场景暂无批量并行证据需求。`AgentMode` 枚举预留 `rewoo` 值（契约留门）。
- [x] 标重评锚点 2026-W49（随 P9 模型层清单；前置条件 = 预算控制与轨迹评估成熟）；T23 收尾时同步 roadmap 注记。

---

## Task 23: 收尾——阶段计划勾除 + 路线图 / 月计划同步 + PR ✅ 必做

**目标：** checkbox 勾除、未竟留痕全部带周次、过时表述修正，PR 合入。

**Files:** 本计划 · `docs/plans/roadmap.md` · `docs/plans/monthly/2026-{09,10,11}.md` · `CLAUDE.md` + `AGENTS.md`（当前阶段段 + 项目结构段补 `agent/` 域、`interfaces/agent.py`、`db/models_agent.py`、`features/agent`、`e2e/`、`scripts/eval_agent.py`）· `docs/verification/README.md`。

- [x] **Step 1:** 阶段计划 checkbox 勾除 + 未竟事项留痕（未竟点 + 2026-Www）：ReWOO / SSE 若让位 / e2e CI 门控 / checkpoint 吞吐 / RAG 记忆。
- [x] **Step 2:** roadmap P7 状态更新 + P8 承接项注记（写工具 / 报告生命周期 / 意图路由 / 证据验证）+ 过时表述修正（如进度注记残留）。
- [x] **Step 3:** 月计划三文件滚动修订 + CLAUDE.md / AGENTS.md 同步。
- [x] **Step 4:** 验证报告索引更新；分支 `feat/p7-agent-mode` → PR → main（CI 绿 + 本地全量真库回归证据存档）。
- [x] **Step 5:** 提交：`docs(plans): P7 收尾与路线图/月计划同步`。

---

## 暂缓与移交记录

- **多轮对话状态**（P5 唯一显式移交，「P6 可引入」，P6 暂缓移交）：✅ 本阶段并入本体（T10–T12：LangGraph 状态图 + PG checkpointer + ORM 三表）。**跨会话记忆（RAG 记忆）**显式点名：会话内多轮状态由 checkpointer + 窗口截断承接；跨会话记忆锚点 2026-W49 随 P9 清单一并重评（P5 范围外「RAG 记忆」原未点名去向，此处补齐）。
- **团队级自定义分析模板注册表**（P6 Task 22 留痕，锚点 2026-W47）：重锚 2026-W44——先评估后决定（T17 评估 / T18 实现门控）；结论为缓则整体顺延 P9 留痕。
- **`frontend/e2e` 链路补建**（P6 留痕，锚点 2026-W47 起）：重锚 2026-W44（T16 六组 smoke，本地绿，不进 CI）。
- **ReWOO 模式**：⏸ 暂缓（T22），锚点 2026-W49 随 P9 模型层清单重评；前置 = 预算控制与轨迹评估成熟。
- **回合 SSE 流式**：🔁 可选（T21），让位则留痕未竟清单（锚点 2026-W49，随 P8/P9 清单重评）。
- **Agent 写行动工具**（ingest / push / merge / 社区管理）：⏸ 移交 P8+——需先有 agent 写行动审计模型与复核流；P7 只读压低注入爆炸半径。
- **Agent 会话生命周期完整形态**（删除 / 归档 / 共享范围变更）：移交 P8 候选，随报告生命周期同批评估；P7 仅创建与读取。

## 依赖与风险

| 风险 | 影响 | 防坑动作 | 落点 |
|:--|:--|:--|:--|
| 桩驱动工具调用循环失真：StubLLM 按脚本固定「第一步调 X、第二步收尾」，对真模型的工具选择错误、参数幻觉、循环倾向零区分度 | 离线证据被误读为「agent 质量好」；真模型下工具选错 / 漏调 / 死循环，`--real` 才暴露，返工 | 双轨验收硬性分离：离线只承诺结构与契约；T9 轨迹断言（工具集匹配 / 步数 / 引用结构）+ T19 `--real` 真模型补跑（锚点 2026-W45）；harness 主指标用工具集匹配而非严格序列匹配（稳健、减伪不稳定）；验证报告显式声明「桩对质量零区分度」；步数硬上限独立于模型行为兜底 | T4/T9/T19 |
| langgraph 版本漂移：`create_react_agent` 已弃用（2.0 移除）、`create_agent` 与 middleware 体系仍在演进 | 升级即破坏；误用弃用 API 导致 2.0 不可升 | 钉 `langgraph>=1.2,<2` + `uv.lock` 锁死；手写 StateGraph（原语 1.0 GA 后稳定）；禁用 `create_react_agent`、不引 `create_agent` / middleware；契约层引擎无关（`interfaces/agent.py`），LangGraph 边界集中在 `graph.py` + 适配器可替换；升级前先读迁移指南 + 验 wheel | T2/T10/T20 |
| 多轮状态与三维权限交叉：会话跨密级泄漏——clearance 降级或 scope 移除后，旧会话消息与工具结果缓存泄漏高密内容 | 低密账户经历史线程读到高密材料，违反「权限内行动」红线 | 会话记创建时密级快照；密级不洗白（读需当前 clearance ≥ 建时）；一切读路径以当前 AccessContext 复检（不通过即 404 + 审计）；工具结果先经 `visible_to` 过滤再落库（落库前密级断言钩子）；T12 专项矩阵（三角色 × 四密级 × 降级 / 收权场景）回归；泄漏=0 一票否决 | T11/T12/T14 |
| agent 循环成本失控：ReAct 每步一次 LLM 调用，步数与 token 不可预测 | token 费用与延迟超线性增长、单会话挂死、本地小模型上下文打爆 | 三重预算帽 `agent_max_steps`（默认 6）/ token / 挂钟进 Settings（同步 `.env.example`），超限强制收敛为「部分结果 + 说明」+ warning；usage 逐轮累计入 `AgentRun` 与审计；harness 把步数 / usage 列为回归指标；`--real` 报告步数与 token 分布 | T10/T19 |
| 提示注入经工具放大：语料内容携带注入指令，经工具链扩大攻击面（P6 已有注入防御，但工具调用是新向量） | 只读路径被滥用作信息探测通道；分析任务被注入污染；平台安全面整体升级 | v1 工具只读 + 每调用点三维门控 + 审计；检索结果入 prompt 前沿用 P6 sanitize 纪律；工具输出截断与引注；prompt 不执行来自工具结果的指令；golden 含注入探针样本断言「工具未被诱导」（零容忍），`--real` 批次含注入案例验证 | T5/T7/T9/T12 |
| 越权探测泄漏存在性：差异化错误文案让探测者推断工具 / 文档 / 会话是否存在 | 违反 roadmap 红线「越权工具结果不得泄漏存在性」 | 工具层越权与不存在统一错误消息（断言二者文本不可区分）；API 层 404 不点名；三角色 + 密级矩阵测试含差异化探测用例 | T5/T14 |
| Windows 依赖坑：裸 psycopg 需系统 libpq（Windows 不可用）、`psycopg[c]` 无 Windows wheel 触发源码编译；orjson / ormsgpack 为 Rust 系 | `uv sync` 失败或运行期 ImportError，阶段开局即被卡 | T2 显式装 `psycopg[binary]`，禁裸 psycopg 与 `psycopg[c]`、禁 `--no-binary`；`uv lock` 审解析（httpx / requests 与 litellm 共存）；安装后冒烟 import + 版本断言落验证记录 | T2 |
| AsyncPostgresSaver 工程坑集：忘 `setup()` / `autocommit=True` / `dict_row`、FastAPI 中 `from_conn_string` 上下文提前退出、异步 saver 配同步 `invoke` 静默挂死 | 运行时挂死或检查点静默丢失；高并发吞吐不达预期 | 按调研检查单逐项实现（setup / autocommit / dict_row / lifespan 保活）；独立连接池与 SQLAlchemy 分离；`@pytest.mark.db` 集成覆盖 setup 幂等与跨调用状态互通；图调用一律 `ainvoke`；内部锁串行化单用户规模接受、留痕锚点 2026-W49 压测批 | T11 |
| LLMProvider 接口扩展破坏存量调用面（九类分析 / 检索合成 / OCR / 识图全走 `complete()`） | 现有 1015 passed 回归面受损 | `tools` 参数默认 `None` 保持旧签名；StubLLM 旧分发优先级不动、新标记不命中即走旧路径；T3 后全量回归不低于基线 | T3/T4 |
| 前端多轮复杂度：会话管理 / 轮询 / 中断容易超时膨胀；流式缺失导致体验落差 | 前端返工、体验半成品、既有路由与权限矩阵回归被破坏 | v1 无流式，轮询复刻 `useAnalysisJob` 范式（1200ms + 终态停）；中断 = 取消标记 + worker 自检，不做硬杀；`preview_*` 三角色 × 双视口闭环为验收硬条件；权限门控复用 `useAccess` 不新造轮子 | T15/T21 |
| 范围膨胀：ReWOO、写工具、流式、RAG 记忆、checkpointer 自研都是诱惑 | 13 周窗口（W36–W48）承诺无法兑现，再次产生移交债 | 每周 10-15h 保守负荷 + 周日回顾；溢出规则：可选任务最先让位（T21 → T20 → T18）；W43 轻周 + W48 兜底双缓冲；范围外表逐项点名去向，新想法一律先进表 | 全局 |
| e2e webServer 只起 5173，后端 8200 未启时登录类 spec 全红 | spec 全红造成虚假不稳定，e2e 纪律被弃、移交链断裂 | e2e README 固化启动顺序（先 `serve --seed-demo --port 8200`）；首条 spec 等 `/healthz`；T1 先修 `demo_seed` 稳定种子；不进 CI 规避环境漂移 | T1/T16 |
| 模板注册表评估滑向直接实现 | 隐形实现任务挤占主链 | T17 口径先行（决策 5 五项）且只出备忘录 + 决策记录；实现独立为可选 T18 并排让位序；结论为缓则整体顺延 P9 留痕 | T17/T18 |
| 本地后端原生 `tool_calls` 支持参差（ollama / LM Studio 各异） | `--real` 质量补跑无法执行或结果失真 | LiteLLM 归一 OpenAI 格式；T19 预检后端能力；不支持 → 友好报错 + 换模型并留痕，明确不做 prompt-based 文本协议降级 | T19 |

## 闭合实录与 W49 重评议程

**闭合实录**：P7 于 2026-08-31 提前全闭合（PR #13 合入 main；原节奏建议表 W36–W48
作废为历史计划）。证据：1124 passed / 前端 70 vitest / e2e 12 绿 / 离线+--real 双轨，
见 [[docs/verification/P7-verification|P7 验证]]。

**W49（11/30–12/06）未竟重评议程**（逐条「做 / 暂缓 / 注销」三选一；做则进 P8/P9
阶段计划自 W50 排期；2026-12 月计划层已于 2026-08-31 文档重构撤销，议程改随本附录）：

| # | 事项 | 判据 | 做则排期 |
| --- | --- | --- | --- |
| 1 | ReWOO 模式 | 模型批量规划能力（P9 模型层清单）+ 批量并行证据需求是否出现 | P9 批 W50+ |
| 2 | PlanExecute（门槛已达标） | 多步可审计诉求是否真实出现 | P9 批 W50+（复用共享状态/工具/预算帽） |
| 3 | 回合 SSE 流式 | 轮询体验真实投诉 / 长回合占比 | P8/P9 体验批 |
| 4 | e2e 进 CI + analysis headless 复评 | 审计硬化批给 CI 真库策略；headless 异常根因 | 审计硬化批 |
| 5 | checkpoint 高并发吞吐 | 压测拐点量化 | P9 压测批 |
| 6 | Windows 跨 loop 桥接 | 开发态重启续接需求频率 vs 桥接复杂度 | P9 或维持降级 |
| 7 | worker 自检取消 | 长回合取消真实频率 | 小项可插队 W50 |
| 8 | RAG 记忆（跨会话） | 会话间复用诉求与形态选型 | P9 批 |

P9 承接簇（同周重评，P9 域）：审计硬化 / 合规 / 压测、VectorStore 置换、ProfileCard
改 PG、谓词下推、mmr_dedup、contextual v2、L2 主题摘要、语义切分（门槛
ctx_recall +0.05）、Alembic、Provider 能力探测。

## 依赖与风险

| 风险 | 影响 | 防坑动作 | 落点 |
|:--|:--|:--|:--|
| 桩驱动工具调用循环失真：StubLLM 按脚本固定「第一步调 X、第二步收尾」，对真模型的工具选择错误、参数幻觉、循环倾向零区分度 | 离线证据被误读为「agent 质量好」；真模型下工具选错 / 漏调 / 死循环，`--real` 才暴露，返工 | 双轨验收硬性分离：离线只承诺结构与契约；T9 轨迹断言（工具集匹配 / 步数 / 引用结构）+ T19 `--real` 真模型补跑（锚点 2026-W45）；harness 主指标用工具集匹配而非严格序列匹配（稳健、减伪不稳定）；验证报告显式声明「桩对质量零区分度」；步数硬上限独立于模型行为兜底 | T4/T9/T19 |
| langgraph 版本漂移：`create_react_agent` 已弃用（2.0 移除）、`create_agent` 与 middleware 体系仍在演进 | 升级即破坏；误用弃用 API 导致 2.0 不可升 | 钉 `langgraph>=1.2,<2` + `uv.lock` 锁死；手写 StateGraph（原语 1.0 GA 后稳定）；禁用 `create_react_agent`、不引 `create_agent` / middleware；契约层引擎无关（`interfaces/agent.py`），LangGraph 边界集中在 `graph.py` + 适配器可替换；升级前先读迁移指南 + 验 wheel | T2/T10/T20 |
| 多轮状态与三维权限交叉：会话跨密级泄漏——clearance 降级或 scope 移除后，旧会话消息与工具结果缓存泄漏高密内容 | 低密账户经历史线程读到高密材料，违反「权限内行动」红线 | 会话记创建时密级快照；密级不洗白（读需当前 clearance ≥ 建时）；一切读路径以当前 AccessContext 复检（不通过即 404 + 审计）；工具结果先经 `visible_to` 过滤再落库（落库前密级断言钩子）；T12 专项矩阵（三角色 × 四密级 × 降级 / 收权场景）回归；泄漏=0 一票否决 | T11/T12/T14 |
| agent 循环成本失控：ReAct 每步一次 LLM 调用，步数与 token 不可预测 | token 费用与延迟超线性增长、单会话挂死、本地小模型上下文打爆 | 三重预算帽 `agent_max_steps`（默认 6）/ token / 挂钟进 Settings（同步 `.env.example`），超限强制收敛为「部分结果 + 说明」+ warning；usage 逐轮累计入 `AgentRun` 与审计；harness 把步数 / usage 列为回归指标；`--real` 报告步数与 token 分布 | T10/T19 |
| 提示注入经工具放大：语料内容携带注入指令，经工具链扩大攻击面（P6 已有注入防御，但工具调用是新向量） | 只读路径被滥用作信息探测通道；分析任务被注入污染；平台安全面整体升级 | v1 工具只读 + 每调用点三维门控 + 审计；检索结果入 prompt 前沿用 P6 sanitize 纪律；工具输出截断与引注；prompt 不执行来自工具结果的指令；golden 含注入探针样本断言「工具未被诱导」（零容忍），`--real` 批次含注入案例验证 | T5/T7/T9/T12 |
| 越权探测泄漏存在性：差异化错误文案让探测者推断工具 / 文档 / 会话是否存在 | 违反 roadmap 红线「越权工具结果不得泄漏存在性」 | 工具层越权与不存在统一错误消息（断言二者文本不可区分）；API 层 404 不点名；三角色 + 密级矩阵测试含差异化探测用例 | T5/T14 |
| Windows 依赖坑：裸 psycopg 需系统 libpq（Windows 不可用）、`psycopg[c]` 无 Windows wheel 触发源码编译；orjson / ormsgpack 为 Rust 系 | `uv sync` 失败或运行期 ImportError，阶段开局即被卡 | T2 显式装 `psycopg[binary]`，禁裸 psycopg 与 `psycopg[c]`、禁 `--no-binary`；`uv lock` 审解析（httpx / requests 与 litellm 共存）；安装后冒烟 import + 版本断言落验证记录 | T2 |
| AsyncPostgresSaver 工程坑集：忘 `setup()` / `autocommit=True` / `dict_row`、FastAPI 中 `from_conn_string` 上下文提前退出、异步 saver 配同步 `invoke` 静默挂死 | 运行时挂死或检查点静默丢失；高并发吞吐不达预期 | 按调研检查单逐项实现（setup / autocommit / dict_row / lifespan 保活）；独立连接池与 SQLAlchemy 分离；`@pytest.mark.db` 集成覆盖 setup 幂等与跨调用状态互通；图调用一律 `ainvoke`；内部锁串行化单用户规模接受、留痕锚点 2026-W49 压测批 | T11 |
| LLMProvider 接口扩展破坏存量调用面（九类分析 / 检索合成 / OCR / 识图全走 `complete()`） | 现有 1015 passed 回归面受损 | `tools` 参数默认 `None` 保持旧签名；StubLLM 旧分发优先级不动、新标记不命中即走旧路径；T3 后全量回归不低于基线 | T3/T4 |
| 前端多轮复杂度：会话管理 / 轮询 / 中断容易超时膨胀；流式缺失导致体验落差 | 前端返工、体验半成品、既有路由与权限矩阵回归被破坏 | v1 无流式，轮询复刻 `useAnalysisJob` 范式（1200ms + 终态停）；中断 = 取消标记 + worker 自检，不做硬杀；`preview_*` 三角色 × 双视口闭环为验收硬条件；权限门控复用 `useAccess` 不新造轮子 | T15/T21 |
| 范围膨胀：ReWOO、写工具、流式、RAG 记忆、checkpointer 自研都是诱惑 | 13 周窗口（W36–W48）承诺无法兑现，再次产生移交债 | 每周 10-15h 保守负荷 + 周日回顾；溢出规则：可选任务最先让位（T21 → T20 → T18）；W43 轻周 + W48 兜底双缓冲；范围外表逐项点名去向，新想法一律先进表 | 全局 |
| e2e webServer 只起 5173，后端 8200 未启时登录类 spec 全红 | spec 全红造成虚假不稳定，e2e 纪律被弃、移交链断裂 | e2e README 固化启动顺序（先 `serve --seed-demo --port 8200`）；首条 spec 等 `/healthz`；T1 先修 `demo_seed` 稳定种子；不进 CI 规避环境漂移 | T1/T16 |
| 模板注册表评估滑向直接实现 | 隐形实现任务挤占主链 | T17 口径先行（决策 5 五项）且只出备忘录 + 决策记录；实现独立为可选 T18 并排让位序；结论为缓则整体顺延 P9 留痕 | T17/T18 |
| 本地后端原生 `tool_calls` 支持参差（ollama / LM Studio 各异） | `--real` 质量补跑无法执行或结果失真 | LiteLLM 归一 OpenAI 格式；T19 预检后端能力；不支持 → 友好报错 + 换模型并留痕，明确不做 prompt-based 文本协议降级 | T19 |

## 节奏建议（学生 10-15h/周，2026-08-31 W36 起）

| 周次 | 日期 | Task | 要点 |
|:--|:--|:--|:--|
| 2026-W36 | 08/31–09/06 | #1–#2 | 清尾 + 依赖安全：四条操作债一次清掉（`demo_seed` 修复是 preview 闭环与 e2e 的 `--seed-demo` 硬前置）；Windows wheel 与 uv 解析这两个最便宜的未知数最早拆掉。P7 自 W36 直接开工，移交锚点整体提前重锚 |
| 2026-W37 | 09/07–09/13 | #3–#4 | 契约先于装配、离线先行：LLMProvider 工具调用契约 + StubLLM 脚本化——桩循环能力是全部后续的地基；全量回归不低于 1015 passed 基线 |
| 2026-W38 | 09/14–09/20 | #5–#6 | 集成隔离层 + 红线定型：BaseChatModel 适配器（LLM 所有权不旁落）+ 工具注册表三维门控（越权与不存在同形语义本周钉死） |
| 2026-W39 | 09/21–09/27 | #7–#8 | 工具落地：只读批在前、分析桥在后（消费 P6 报告契约，纯函数复用零改动、P6 基线对照） |
| 2026-W40 | 09/28–10/04 | #9–#10 | 评估先立 + 主链打通：harness 作为图实现门槛（边界探针零泄漏才放行）；ReAct 一条主链离线闭环 + 三重预算帽同步落地 |
| 2026-W41 | 10/05–10/11 | #11–#12 | 最大翻车面专项周：会话持久化落真 PG（ORM + AsyncPostgresSaver 工程坑一次做对）+ 多轮状态 × 三维权限交叉矩阵回归 |
| 2026-W42 | 10/12–10/18 | #13–#14 | worker 与 API 面贯通：job 范式零新范式成本，审计与 401/403/404 矩阵齐全，多轮对话端到端可用（消息 → job → 图执行 → 落库） |
| 2026-W43 | 10/19–10/25 | #15 | 前端聊天面单任务周（前端重、含 `preview_*` 闭环与三角色 × 双视口验收，不并排；隐性缓冲） |
| 2026-W44 | 10/26–11/01 | #16–#17 | e2e 补建 + 模板注册表评估——两项原 2026-W47 锚点此处重锚提前（理由见「重锚说明」） |
| 2026-W45 | 11/02–11/08 | #18（可选）+ #19 | 双轨验收质量轨：`--real` 真模型证据入库（用户本机，就绪可提前）；评估结论驱动的轻量实现（可选，让位序末位） |
| 2026-W46 | 11/09–11/15 | #20（可选）+ #21（可选） | 可选池周：PlanExecute（启动门槛 = #19 质量达标，让位序第二）+ SSE（让位序第一）；超载规则生效——先砍 #21，再顺延 #20，再砍 #18 |
| 2026-W47 | 11/16–11/22 | #22 + #23 | 收尾：ReWOO 归宿留痕（锚点 2026-W49），阶段计划勾除、未竟留痕全部带周次、过时表述修正，PR 合入 |
| 2026-W48 | 11/23–11/29 | 备用缓冲 | 兜底缓冲：吸收任意周溢出；总回归（后端全量真库 + 前端三件套 + e2e）+ PR 合入 + 未竟事项周次复查；本周未动用即阶段提前闭合，不留隐式尾巴 |

**缓冲规则**：任何一周欠账顺延，可选任务（#18、#20、#21）最先让位（让位序 #21 → #20 → #18）；承诺批次（#1–#19、#22–#23）不允许跨入 2026-W48 之后，否则触发范围重审。`--real` 补跑周次随之顺延但必须在验证报告中更新留痕周次。

> [!note] 2026-08-31 文档重构
> 年 / 月 / 周计划层撤销，仅保留 phases 阶段计划；本文历史表述保留原样，废止层链接失效。
