---
title: P6 LLM 分析任务实施计划
type: phase-plan
phase: P6
tags:
  - plan/phase
created: 2026-08-29
---
# P6 LLM 分析任务实施计划

> 介于 [[docs/plans/phases/P5-advanced-rag|P5 高级 RAG]]（已完成）与 P7 Agent 模式（待启动）之间。P5 在检索层把精度挣完，P6 让平台「会分析」：把三层知识图谱已落库的材料，经「单次提交 → 异步执行 → 单轮结构化输出」加工为 **9 类结构化分析报告**（摘要 / 关键信息 / 时间线 / 实体识别 / 关系映射 / 任务 / 概念 / 问答 / 自定义），每份报告带证据引用（`chunk_id` + `quote`）、置信标注、密级继承与审计留痕。工具调用与多步规划属 P7，跨文档证据核验与幻觉检测属 P8，持久队列与规模化属 P9，本阶段一律不碰。结构化报告契约是 P7 Agent 可直接消费、P8 验证有对象可验的地基。

> **For agentic workers:** 严格按 Task 编号顺序执行（顺序由 [[docs/plans/roadmap|年计划]] 与「为什么是这个顺序」锁定）；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内遵循 TDD 五连（写失败测试 → 跑确认失败 → 实现 → 跑绿 → 提交，可加装配 / 迁移步骤）；不得并行跨 Task 提交，不得跨 Task 顺手扩张范围，发现的额外问题就地留痕（未竟点 + 周次 `2026-Www`）；新 ORM 必须在 `models.py` 集中导入注册；新配置项必须 `config.py` 与 `.env.example` 双同步；DB 依赖测试自动打 `@pytest.mark.db`（CI 以 `-m "not db"` 跳过，本地 `.env` 全量回归留证据）；验收口径双轨——**离线证据只承诺结构与契约，质量证据必须 `--real` 真模型补跑**（见「目标与范围 · 验收口径」）；有视觉表现的前端改动必须走 `preview_*` 交互闭环 + 三角色权限矩阵。

## 目标与范围

**总目标**：用户对选定材料提交分析任务，系统异步执行（1:1 复刻 P4.5 异步 job 范式）并产出带证据引用的结构化报告；报告落库持久化、继承密级、三维权限可见、审计可追溯；配套字段级 / 元组级 P-R-F1 与 G-Eval rubric judge 评估 infra，让 `GoldenCase.expected_answer` 自 P2 以来**首次被指标消费**。

**与 roadmap 边界**（[[docs/plans/roadmap|roadmap]] 定义：P6 LLM 分析任务——9 类分析（摘要/关键信息/时间线/实体识别/关系映射/任务/概念/问答/自定义）结构化报告）：

- 保持「单次提交 → 异步执行 → 单轮结构化输出」；不引工具调用 / 多步规划（P7 Agent 模式：ReAct/ReWOO/PlanExecute + LangGraph + 工具定义）。
- 不做跨文档证据核验 / 幻觉判定 / 意图判别路由（P8）；P6 只做轻量自验证：证据 `quote` 必须为源文子串。
- 不引持久队列 / ANN / 规模化（P9）；P6 复用 `BackgroundTasks` 单进程异步。

**验收口径（双轨，硬性）**：

- **离线证据**（CI 可跑、桩驱动）只承诺：任务状态机正确（pending→running→succeeded/failed）、报告 schema 合法（pydantic 校验通过）、三角色权限矩阵可见 / 可操作集合正确、审计字段齐全、quote 子串校验生效、密级继承规则生效、轮询契约正确。**桩对生成质量零区分度**（P5 golden 基线：ctx_recall 0.4444 / faithfulness 0.4444 / answer_relevance 1.0000，9 例小语料离线桩全配置持平），离线全绿**不得**表述为「分析质量好」。
- **质量证据**（仅 `--real`）：真模型跑 `scripts/eval_p6.py --real`，字段级 / 元组级 P-R-F1 + G-Eval judge 与 golden 对比。补跑锚点 **2026-W45**（用户本机，与 `scripts/eval_p5.py --real` 同批合并执行）；若前序延误顺延至 2026-W46 并在验证报告留痕。证据文件：`p6-regression.json`（离线）与 `p6-real-<模型名>.json`（质量）。

**范围外（逐条点名去向）**：

| 事项 | 去向 |
|:--|:--|
| 多轮对话状态（P5 唯一显式移交，「P6 可引入」） | ⏸ 暂缓 → P7：超出 roadmap 对 P6 的一句话定义，LangGraph 状态图是更自然的宿主（决策 5） |
| L2 全库主题摘要（P2-retrieval-rag.md:119 预留并指派 P6，此处显式改道） | ⏸ 暂缓 → P9，锚点 2026-W49：roadmap 对 P6 的一句话定义不含 L2，L2 依赖定时 / 增量重算基础设施；roadmap.md:54 对 L0/L1 摘要「仅展示层、不进检索链路」的定位表明摘要系展示资产，暂缓 L2 不伤检索质量；Task 23 记入 roadmap P9 段 |
| 跨文档证据核验 / 幻觉判定 / 意图判别路由 | P8（P6 仅 quote 子串自验证） |
| 报告删除 / 版本化 / 复核流 | P8（与证据验证配套） |
| 置信度校准（ECE） | P8（P6 自报置信仅作排序 / 复核标记） |
| Celery+Redis 持久队列 | P9（P6 复用 `BackgroundTasks`） |
| mmr_dedup 运行时接线（P5 遗留） | P9，锚点 2026-W49（随候选向量管线落地一并重评） |
| contextual v2 独立摘要向量列（P5 遗留） | P9，锚点 2026-W49（随 contextual 收益证据一并重评） |
| 语义切分 | 等 contextual 收益证据，2026-W49（P9 启动时）重评 |
| 三 store list 谓词下推（按 `doc_ids` 过滤） | P9（P6 以全量拉取 + `visible_to` 内存过滤 + `analysis_max_chunks` 截断兜底，Task 9 留痕） |
| 逾期 TODO `api/deps.py:89` ProfileCard/BM25 改 PG（2026-W33 逾期） | 显式顺延 P9，锚点改 **2026-W49**（与谓词下推同批；P6 材料路径不依赖 BM25），Task 1 改锚点 |
| 团队级自定义分析模板注册表 | P7 计划评估，锚点 2026-W47（仿 `ecl/extraction_template.py` ExtractionTemplateRegistry 范式，Task 22 留痕） |
| `scripts/eval_p5.py --real` 真实模型补跑（P5 遗留） | 用户本机，锚点 2026-W45（与 P6 `--real` 同批，Task 23 落） |
| `frontend/e2e` 目录不存在（playwright config 指向空） | 随 P7 e2e 链路补建（2026-W47 起），P6 仅留痕不扩面 |
| 引入 instructor / LangChain | 不引入（与 `LLMProvider` 抽象重叠）——吸收 OutputFixingParser / RetryWithErrorOutputParser 模式自实现解析链 |

## 顺序总览

| # | Task | 承诺 | 状态 |
|---|---|---|---|
| 1 | 前置批：闭环 `collab/service.py:18` 时区 TODO + `api/deps.py:89` 锚点顺延 P9 | ✅ 必做 | ✅ 完成 |
| 2 | `Permission.ANALYZE` 全链路 + `seed_default_roles` 回填修复 + 幂等测试 + 前端常量 | ✅ 必做 | ✅ 完成 |
| 3 | `Settings` 分析配置项 + `.env.example` 全量对账补齐 | ✅ 必做 | ✅ 完成 |
| 4 | 报告契约 I：公共信封 + Evidence + quote 子串校验（纯函数） | ✅ 必做 | ✅ 完成 |
| 5 | 报告契约 II：9 类报告 pydantic 模型 + `AnalysisTaskSpec` 注册表 | ✅ 必做 | ✅ 完成 |
| 6 | 提示词模板与构造（第一批 5 类，`config/analysis_prompts/*.txt` 版本化） | ✅ 必做 | ✅ 完成 |
| 7 | 解析回退链 + 回喂重试 + 降级（extra `analysis`：json-repair 懒加载） | ✅ 必做 | ✅ 完成 |
| 8 | StubLLM 9 类分析标记分发 + 逐类型契约测试 | ✅ 必做 | ✅ 完成 |
| 9 | 材料采集器：`visible_to` 红线 + 截断 + 图谱复用读取 | ✅ 必做 | ✅ 完成 |
| 10 | `AnalysisEngine` + `interfaces/analysis.py` 抽象 + factory（第一批接线） | ✅ 必做 | ✅ 完成 |
| 11 | Job 表泛化扩列 + `db/migrate.py` 幂等补列（含 collab 列型回填）+ `JobOut` 扩展与 `api/jobs.py` 透传 | ✅ 必做 | ✅ 完成 |
| 12 | `AnalysisReportORM` + `AnalysisReportStore` + 密级继承落库 | ✅ 必做 | ✅ 完成 |
| 13 | Worker 分析执行路径：进度分段 / 报告落库 / 终态审计 | ✅ 必做 | ✅ 完成 |
| 14 | 分析 API：提交 202 + 历史 / 详情 + 可见文档清单 + 审计 + 双挂 | ✅ 必做 | 未开始 |
| 15 | 报告导出端点（首次消费 `export` 权限） | ✅ 必做 | 未开始 |
| 16 | 评估 I：`config/golden_analysis.yaml` + 字段 / 元组级 P-R-F1（`expected_answer` 落地） | ✅ 必做 | 未开始 |
| 17 | 评估 II：G-Eval judge + harness 扩展 + `scripts/eval_p6.py` + 离线基线 | ✅ 必做 | 未开始 |
| 18 | 前端 I：types / API 客户端 / `useAnalysis` hook + vitest | ✅ 必做 | 未开始 |
| 19 | 前端 II：AnalysisPage 提交侧 + job 轮询（preview 闭环） | ✅ 必做 | 未开始 |
| 20 | 前端 III：ReportViewer + 历史 / 导出 + 三角色矩阵（preview 闭环） | ✅ 必做 | 未开始 |
| 21 | 第二批接线：关系映射 / 任务 / 概念（图谱复用） | ✅ 必做 | 未开始 |
| 22 | 自定义分析：用户 schema sanitize + 动态 spec + 注入防御 | ✅ 必做 | 未开始 |
| 23 | 第二批前端 + 验证报告 + 文档同步 + `--real` 补跑锚点 | ✅ 必做 | 未开始 |
| 24 | `calliodesmo analyze` CLI（仿 `ask`） | 🔁 可选 | 未开始 |
| 25 | provider 原生结构化输出能力探测 | 🔁 可选 | 未开始（锚点 2026-W49，P9 模型层清单） |
| 26 | 多轮对话状态 | ⏸ 暂缓 | 移交 P7 |
| 27 | L2 全库主题摘要 | ⏸ 暂缓 | 移交 P9（2026-W49） |

**为什么是这个顺序**：

1. **风险前置**（最可能翻车的坑最早拆）：Task 1 清逾期尾巴（`collab` 时区是 DB 正确性坑，必须先于新 ORM 落库）；Task 2 把**最危险的坑**（`seed_default_roles` 对已存在角色直接 `continue`，新权限不回填 → 既有部署重跑 `db seed` 全员 403）连修复带幂等测试一起做掉，之后所有端点才有门控可用。
2. **契约先于装配**：Task 4–5 一次性冻结全部 9 类报告模型与注册表（注册表 / 解析 / 评估 / 前端渲染四方共用的锚点；契约完整、交付分批）；解析链（Task 7）是质量生命线，纯函数无夹具、CI 全覆盖，先于引擎装配；StubLLM 契约（Task 8）9 类一次落齐，钉死「关键词写错静默回退抽取输出而测试不红」的坑，避免批次间回改桩。
3. **复刻已验证范式**：Job 泛化 / ORM / worker / API（Task 11–15）按 P4.5 ingest 异步 job 范式 1:1 复刻，风险最低，放中段承接；导出（Task 15）顺势消费前端一直零消费的 `export` 权限。
4. **离线先行、真模型收尾**：评估（Task 16–17）插在第一批后端完成后、第二批开始前——先立质量基线（参考分而非硬门槛），第二批与自定义在基线监督下增量；`--real` 质量补跑落收尾缓冲周（2026-W45）。
5. **UI 在契约冻结后、评估压轴**：前端（Task 18–20）依赖 API 完成后整批推进；第二批与自定义（Task 21–22）契约已冻结，纯增量；文档与验证报告（Task 23）压轴闭环。
6. **批次门槛**：Task 21–22 的启动条件为 Task 17 离线基线落盘全绿 + Task 20 三角色矩阵通过；不满足则第二批顺延，不带病增量。

## 关键决策（7 个决策点已拍板）

1. **权限门控：新增 `Permission.ANALYZE`**，analyst / reviewer / admin 三角色均授予（`admin = set(Permission)` 自动获得）。理由：分析是高 token 成本的派生生产动作，语义独立于 `query`，三维正交模型的「能做什么」维度不借用；审计须与检索分开统计；报告默认 `personal` scope、owner=提交者，不进协作审批流，与 `query`/`export` 对称，故 reviewer 同样授予。**同批修复 `seed_default_roles` 回填缺陷**（现实现对已存在角色直接 `continue`，新权限对既有部署重跑 `db seed` 不生效、全员 403），改差集回填 + 幂等测试。前端 `PERMISSIONS` 常量与 `useAccess` 导航门控同步。
2. **报告持久化：新建 `AnalysisReportORM`**（三维权限五字段，经 `visible_to` 过滤，可审计、可列历史）。理由：报告是派生情报资产一等公民；`Job.result` 无行级访问控制语义（`GET /jobs/{id}` 仅按 `user_id` 过滤），塞全量报告还撑大 jobs 表。`Job.result` 只存 `{report_id, status}` 最小指针。
3. **Job 表：扩列泛化**（`task_type` + `task_payload`），不建新表。理由：单一异步状态机，直接复用既有 `GET /jobs/{id}` 轮询链路（过滤与鉴权逻辑不变；因 `get_job` 逐字段显式构造 `JobOut`，需补 `task_type`/`report_id` 两字段透传，见 Task 11）、进度字段与 `reset_stale_running_jobs()` 清残留。**迁移影响**：SQLAlchemy `create_all` 不给既有表加列 → 新增 `db/migrate.py` 幂等补列工具并挂进 `db init`，带 `@pytest.mark.db` 真 PG 测试；不做手工一次性 ALTER。
4. **报告密级继承：`access_level = max(材料各级, INTERNAL)`**，`library_scope = personal`，`owner = 提交者`。理由：`ClearanceLevel` 有序，`max()` 直接可用；实现为纯函数 `compute_report_access_level` 离线单测锁定；堵住低密账户借分析「洗」高密内容的通道，INTERNAL 下限避免报告默认公开。
5. **多轮对话状态与 L2 全库主题摘要：均暂缓**。理由：本计划将 P6 口径定为「单次提交 → 单轮结构化输出」，与 roadmap 的 9 类结构化报告定义相容，多轮状态不在该定义内；多轮状态归 P7 LangGraph 状态图（现在做是一次性垫层，P6 产出的报告契约与注册表届时可被 Agent 直接消费，无返工）。L2 由 P2 预留指派 P6（P2-retrieval-rag.md:119），因 roadmap 的 P6 定义不含它且依赖定时 / 增量重算基础设施，**此处显式改道**暂缓至 P9（锚点 2026-W49；roadmap.md:54 对 L0/L1「仅展示层、不进检索链路」的定位表明摘要系展示资产，暂缓不伤检索质量）；Task 23 在 roadmap P9 段记改道注记。
6. **结构化输出：v1 统一「prompt 格式指令 + 解析回退链 + ValidationError 回喂重试（预算配置化）+ 部分抢救降级」单路径**，provider 原生约束解码能力探测列 🔁 可选（锚点 2026-W49）。理由：`LLMProvider` 抽象只有 `complete(messages)` 一个口径；LiteLLM 多后端对原生约束解码支持度不一（OpenAI strict 只吃 JSON Schema 子集、拒 Optional/union；Anthropic 仍 beta），能力探测会退化成多后端 if-else 沼泽且桩无法覆盖，破坏离线可测性；解析链行为统一、确定性强、CI 全覆盖，未来叠 provider 原生约束只是链上加分支，不推翻。约束解码只保语法不保语义，pydantic 业务校验叠加为第二道闸。
7. **9 类分两批交付、全部必做**（roadmap 定义是承诺底线）：第一批 5 类（摘要 / 关键信息 / 时间线 / 实体识别 / 问答）跑通主链；第二批 4 类（关系映射 / 任务 / 概念 / 自定义）增量接线。理由：注册表类型无关（加类型 = 加一条 spec + 一份模板，不改引擎），第一批验证引擎 / 解析 / 持久化 / 前端全链路；自定义有独立注入面（用户 schema/指令 sanitize），单独一批控制风险面。

## 前置条件（开工前确认）

- [x] [[docs/plans/phases/P4.5-persistence-production|P4.5]] 与 [[docs/plans/phases/P5-advanced-rag|P5]] 已并入 main，后端真实 PG+pgvector+Neo4j 回归基线绿（记录当前用例数作回归参照）。
- [x] 本地 `.env` 的真实 PG+pgvector+Neo4j 可用；`uv sync --extra persistence` 已装（neo4j>=5.14、pgvector>=0.3，DB 测试必需）。
- [x] litellm 钉版 `>=1.85,<1.91` 保持不变（≥1.93 无 Windows 预编译 wheel），本阶段**不升级**。
- [x] [[docs/model-selection|模型选型]] 预留的「P6 九类分析：质量优先」模型至少一路可用（gpt-4o / claude-3-5-sonnet / qwen-max 任一 API，或本地 `ollama/qwen2.5:72b`）；离线测试走 `test/*` 桩（经 `retrieval/factory.build_llm_provider` 路由）。
- [x] P5 golden 基线数字存档在手：ctx_recall 0.4444 / faithfulness 0.4444 / answer_relevance 1.0000（9 例小语料，离线桩）——作为 P6 评估对照锚点。
- [x] 前端三件套基线绿：`npm run lint && npm run test && npm run build`。
- [x] 两处逾期 TODO 处置已明确（Task 1 执行）：`collab/service.py:18` 时区本阶段闭环；`api/deps.py:89` ProfileCard/BM25 改 PG 顺延 P9（锚点 2026-W49）。
- [x] `data/demo/*.md` 语料文件在本机就位（Task 16 golden 与 `scripts/eval_p6.py` 灌库依赖；`data/` 不入库，缺失时从既有备份恢复或重新准备同 9 例语料，chunk_id 前缀约定不变）。

## 架构

### 域分层总览

```text
src/calliodesmo/
├── interfaces/analysis.py        # 对外契约：AnalysisType / AnalysisMaterial / AnalysisSpec /
│                                 #   EvidenceRef / AnalysisReport / AnalysisEngine(ABC)（新增可插拔抽象）
├── analysis/                     # P6 分析域（新增）
│   ├── schemas.py                # AnalysisStatus 枚举 + 9 类报告 pydantic 模型 + 字段校验器
│   ├── specs.py                  # AnalysisTaskSpec + BUILTIN_ANALYSIS_SPECS 注册表 + build_custom_spec
│   ├── prompts.py                # config/analysis_prompts/*.txt 加载 + {token} 替换 + prompt_version（纯函数）
│   ├── parser.py                 # 解析回退链 + ValidationError 回喂消息构造 + 部分抢救（纯函数）
│   ├── evidence.py               # verify_evidence：quote 子串校验 → 置信封顶 + warning（纯函数）
│   ├── access.py                 # compute_report_access_level = max(材料各级, INTERNAL)（纯函数）
│   ├── materials.py              # gather_materials：三 store 全量 + visible_to + doc_ids 过滤 + 截断 + 图谱复用
│   ├── engine.py                 # DefaultAnalysisEngine：prompt → LLM → 解析 → 回喂重试 → 证据自验 → 信封
│   ├── sanitize.py               # 自定义 schema 清洗（拒 $ref/递归/超深/超大 + 子集裁剪，Task 22）
│   ├── factory.py                # build_analysis_engine：复用 retrieval/factory.build_llm_provider 路由规则
│   ├── report_store.py           # AnalysisReportStore：create / get / list_visible（PG 单后端）
│   └── job_worker.py             # run_analysis_job(job_id, *, engine, session_factory, barrier=None)：状态机 + 进度 + 落库 + 审计
├── api/analysis.py               # /analysis 路由（新增，根 + /api 前缀双挂，同既有路由范式）
├── db/models_job.py              # 扩列：task_type + task_payload（ingest 语义不动）
├── db/models_analysis.py         # AnalysisReportORM（新增，三维权限五字段）
├── db/migrate.py                 # ensure_missing_columns 幂等补列（新增，挂进 cli db init）
└── models.py                     # 集中导入注册新 ORM（漏注册 → 测试 schema 缺表）
config/analysis_prompts/          # 9 份模板（版本化，头部 `# version: N`，{token} 令牌替换，GraphRAG 范式）
config/golden_analysis.yaml       # 分析 golden 集（每类小金标，复用既有 9 例小语料同源材料）
scripts/eval_p6.py                # 三用法：--dump-golden / 默认离线桩落盘 p6-regression.json / --real
frontend/src/features/analysis/   # AnalysisPage / ReportViewer / ReportsHistory / useAnalysis.ts
```

**不新增 AppStores 槽位**：报告持久化走 PG 单后端（循 `collab/service.py` ORM 直用先例）。理由：P4.5 起测试与运行皆真 PG，报告是强持久产物，memory 后端徒增假可用；未来若需 memory 后端再抽象（留痕 2026-W49）。

### interfaces/analysis.py 形状（Task 10 冻结）

```python
class AnalysisType(enum.StrEnum):
    SUMMARY = "summary"  # 摘要
    KEY_INFORMATION = "key_information"  # 关键信息
    TIMELINE = "timeline"  # 时间线
    ENTITY_RECOGNITION = "entity_recognition"  # 实体识别
    RELATION_MAPPING = "relation_mapping"  # 关系映射
    TASKS = "tasks"  # 任务（报告模型名 ActionItemReport，避免与 Job 混淆）
    CONCEPTS = "concepts"  # 概念
    QA = "qa"  # 问答
    CUSTOM = "custom"  # 自定义


@dataclass(frozen=True)
class AnalysisMaterial:
    chunk_id: str
    doc_id: str
    source_label: str  # 文档标题/来源（展示用）
    text: str
    access_level: ClearanceLevel  # 继承自源材料（密级继承计算的输入）
    library_scope: LibraryScope
    owner_id: uuid.UUID | None


@dataclass(frozen=True)
class AnalysisSpec:
    task_type: AnalysisType
    doc_ids: tuple[str, ...] | None  # None = 全可见范围；仅作成员筛选，不豁免可见性校验
    question: str = ""  # qa 必填
    custom_instruction: str = ""  # custom 必填
    custom_schema: dict | None = None
    top_k: int = 10  # qa 用
    model_override: str | None = None


@dataclass(frozen=True)
class EvidenceRef:
    chunk_id: str
    quote: str  # 必填；缺失/失配 → 置信封顶 + warning


@dataclass(frozen=True)
class AnalysisReport:
    task_type: AnalysisType
    status: str  # ok | partial（契约枚举另含 failed；落库规则见「报告落库口径」）
    payload: dict  # 对应类型 pydantic 模型 model_dump()
    model: str
    prompt_version: str
    usage: dict[str, int]
    warnings: list[str]
    source_chunk_ids: list[str]


class AnalysisEngine(ABC):
    @abstractmethod
    async def run(
        self, spec: AnalysisSpec, materials: Sequence[AnalysisMaterial], access: AccessContext
    ) -> AnalysisReport: ...
```

**材料装配不进引擎**：worker 负责 `gather_materials`（含 `visible_to`），引擎只吃已过滤材料——保引擎纯逻辑可测。`access` 入参供 QA 类调 `SearchEngine.query` 与审计溯源消费。

**信封装配**：引擎产出 `AnalysisReport`；worker 落库时补 `generated_at`（UTC now）装配为 API / 前端契约的 `AnalysisEnvelope`（pydantic，见 Task 4），落库后 ORM `created_at` 与之一致，报告详情出参直接取信封。`EvidenceRef` 为 interfaces 的 dataclass 形态（引擎内部流转），`Evidence` 为 `analysis/schemas.py` 的 pydantic 形态（契约层），二者一一对应互转、各随其域命名。

### 注册表与提示词

```python
@dataclass(frozen=True)
class AnalysisTaskSpec:
    type: AnalysisType
    output_cls: type[BaseModel]  # 对应报告模型
    template_name: str  # config/analysis_prompts/<name>.txt
    stub_marker: str  # StubLLM 分发标记（契约测试锁定）
    max_retries: int | None = None  # None = 用全局 analysis_parse_retries
```

- 内置注册表 `BUILTIN_ANALYSIS_SPECS: dict[AnalysisType, AnalysisTaskSpec]`：第一批 5 条（Task 5/6），第二批 +3 条（Task 21），`custom` 经 `build_custom_spec` 动态构造（Task 22）。`get_spec(task_type)` 未注册抛 `KeyError`（API 层转 400）——**未交付类型天然不可提交**，无需额外开关。
- 模板入 `config/analysis_prompts/*.txt` 版本化：首行注释 `# version: 1`，`{materials}` / `{question}` / `{instruction}` / `{schema}` 令牌替换；`prompt_version = "<type>.v<version>"` 落运行记录，评估可按版本切片。
- 提示词构造复用 `ecl/extractor.py` 范式：system 角色声明 + 「严格只输出一个 JSON 对象」+ 输出 schema 示例；**分析类 system 提示统一含 `[ANALYSIS:<type>]` 标记**（StubLLM 分发锚点，见 Task 8）；自定义的 `instruction` 只进 user 消息（与 system 隔离，收敛注入面）。

### 解析回退链与重试（决策 6 的落地形态，Task 7）

```text
LLM 原文 → 剥 ```json 围栏/前后散文（沿用 _parse_json 经验）
        → json.loads
        → 失败且装了 extra analysis：json-repair 修复（运行时懒加载，缺依赖跳过不报硬错）
        → output_cls.model_validate（pydantic 业务校验，第二道闸）
        → 失败：取 ValidationError 摘要 + 原输出截断片段（200 字，仿 _parse_json 惯例）回喂重试
        → 预算 analysis_parse_retries 耗尽：部分抢救可校验字段 → status=partial；抢救不出 → job failed
```

- `json-repair` 走 `optional-dependencies`（extra `analysis`）+ 运行时懒加载 + 缺依赖回退正则花括号抢救路径（两条路径均有测试）。
- **证据自验证**（P6 边界内的轻量自验证，跨文档核验归 P8）：`verify_evidence` 断言每条 `quote` 为对应材料文本子串（去空白后匹配）；失败条目 `confidence` 封顶 0.3 并记 warning；失败占比 >30% → `status=partial`。自报置信仅作排序 / 复核标记，校准（ECE）留痕移交 P8。

### 材料流（全部经 visible_to，两条安全红线）

```text
请求边界（api/analysis.py）：
  require_permission(Permission.ANALYZE) → 可见材料集校验（提交 doc_ids 有不可见者 → 400，
  不泄漏不可见文档的存在性细节）→ build_analysis_engine（RuntimeError→503 / ValueError→400，同 ingest 惯例）
worker（analysis/job_worker.py）：
  gather_materials：三 store list 全量拉取 + visible_to 过滤（提交后权限变化的二次把关）
  → 按 doc_ids 内存过滤（谓词下推留 P9，留痕）→ 按文档序/块序排序
  → 双闸截断（analysis_max_chunks + analysis_max_input_chars）
  → AnalysisMaterial 列表（携带 access_level）
  实体识别/关系映射：另读图数据（graph_store 实体/关系 + visible_to）作图谱上下文，
  LLM 只组织、不重新抽取
  compute_report_access_level(materials) = max(各级, INTERNAL)
  空材料 → failed("无可见材料")
```

- **红线一**：禁止凭客户端传入的 `chunk_id` / `doc_id` 直取材料（枚举越权面）——`doc_ids` 仅作成员筛选，每个 ID 仍过 `visible_to`。
- **红线二**：材料获取不得依赖内存态 `sparse_index` / BM25（跨进程为空，P4.5 遗留，`api/deps.py:89` TODO 顺延 P9）。
- 三 store list 无谓词下推的缺口就地留痕 → P9（Task 9）。

### QA 类复用 SearchEngine

`DefaultAnalysisEngine` 对 `task_type == QA` 分派：经**构造注入的** `SearchEngine` 调 `SearchEngine.query(question, mode, top_k, access)` 得 `Answer`（注入链：`build_analysis_engine` 用与请求侧同一份 settings 经 `build_default_search_engine` 构造，端点经依赖注入传入；**不得在引擎内直调 `api/deps.get_search_engine()`**——该调用绕过测试的 dependency override，离线测试会读到 `.env` 真配置），包装为 `QAReport`（question / answer / sources，来源标注沿用 `answer_synthesizer` 的 `[chunk_id]` 强制引注约定，空候选输出「无可引用证据」）。与 `/app/qa` 全库问答入口的区别：QA 报告入库持久化、可追溯、随报告历史可复查。**已知限制（如实留痕）**：`doc_ids` 范围限定需检索器谓词下推，P6 不可用——QA 检索范围为全可见库，前端文案明示（下推归 P9，2026-W49）。

### Job 扩列与迁移（决策 3）

`db/models_job.py` 追加两列（`filename` / `result` 语义不动，ingest 链路零回归）：

```python
task_type: Mapped[str] = mapped_column(
    String(16), default="ingest", server_default="ingest", index=True
)
task_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- `task_payload` 存 `AnalysisSpec` 序列化（写入前过 `utils/json.py` `json_safe`）；ingest 路径不读不写。
- **迁移**：`create_all` 不给既有表加列 → `db/migrate.py` 提供 `ensure_missing_columns(engine)`（`inspect` 探 `jobs` 表 → 缺列则 `ALTER TABLE ADD COLUMN`），挂进 `cli db init`（`create_all` 之后）；测试建旧结构表 → 跑补齐 → 断言列存在（`@pytest.mark.db`）。全新库由 `create_all` 直出，不走补齐路径。
- `reset_stale_running_jobs()` 按状态机清残留、不分类型，无需改动；`GET /jobs/{id}` 过滤与鉴权逻辑不变，但 `api/jobs.py` 的 `get_job` 逐字段显式构造 `JobOut`，需补 `task_type=job.task_type` 透传，analyze 任务自 `Job.result` 指针解析 `report_id`（Task 11 落）。
- `api/schemas.py` `JobOut` 兼容扩展：`task_type: str = "ingest"`、`report_id: uuid.UUID | None = None`（默认值保既有消费方 `useIngest.ts` 不破坏）。
- **无中央分发器**：循 ingest 范式，`api/analysis.py` 提交端点经 `Depends(get_job_session_factory)` 取工厂，直接 `BackgroundTasks.add_task(run_analysis_job, job_id, engine=engine, session_factory=session_factory)`；`run_analysis_job(job_id, *, engine, session_factory, barrier=None)` 用注入的 `session_factory` 自建会话（测试经 `dependency_overrides[get_job_session_factory]` 指到测试 schema，与 `run_ingest_job` 同机制），spec 自 `Job.task_payload` 读取，`barrier` 供测试同步等待。

### AnalysisReportORM 表结构（决策 2）

`db/models_analysis.py`（不依赖 pgvector，`models.py` 无条件注册，不进 try/except 分支）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `Uuid` PK default uuid4 | 报告 ID |
| `job_id` | `Uuid` 可空 index（不建 FK，同 `Job.user_id` 无 FK 决策：worker 与请求解耦） | 来源 job |
| `user_id` | `Uuid` index | 提交者 |
| `task_type` | `String(32)` index | AnalysisType 值 |
| `status` | `String(16)` | ok / partial（落库规则见下） |
| `subject_label` | `String(512)` | 分析对象描述（文档标题拼接 / 问题） |
| `payload` | `JSON` | 完整信封（写入前必过 `utils/json.py` `json_safe`） |
| `source_doc_ids` | `JSON` | list[str] |
| `source_chunk_count` | `Integer` | 材料块数 |
| `access_level` | `Enum(ClearanceLevel)` index | max(材料各级, INTERNAL) |
| `library_scope` | `Enum(LibraryScope)` default PERSONAL index | 固定 personal |
| `owner_id` | `Uuid` index | = 提交者 |
| `project_id` / `team_id` | `Uuid` 可空 | personal 下为 None |
| `model` `String(128)` · `prompt_version` `String(32)` · `usage_` `JSON` | | 运行记录 |
| `created_at` | server_default now | |

复合索引：`Index("ix_analysis_reports_owner_created", "owner_id", "created_at")`（历史列表主查询）。三维权限五字段齐备 → `stores/visibility.py` `visible_to` 的 `AccessOwned` Protocol 鸭子类型直接生效。

**报告落库口径**：`AnalysisStatus` 契约枚举含 `ok` / `partial` / `failed` 三值（契约完整）；持久化规则为**仅 `ok` / `partial` 落报告行**（用户可见降级原因而非黑洞），解析彻底失败 / LLM 调用异常等完全失败走 `job failed` + `error` 可读 + 审计记 failed，不落空报告。

### API 契约（api/analysis.py，prefix="/analysis"，根 + /api 双挂）

| 端点 | 请求 | 响应 | 守卫 |
|---|---|---|---|
| `POST /analysis/tasks` | `AnalysisJobRequest{task_type, doc_ids=[], question?, custom?{instruction, schema?}, top_k}` | `202 {job_id, status, task_type}` | ANALYZE |
| `GET /jobs/{id}` | —（复用 `api/jobs.py`，过滤/鉴权不变，仅补出参两字段透传） | `JobOut`（扩 `task_type` / `report_id`） | job 所属用户（他人 → 404） |
| `GET /analysis/reports?limit=20&offset=0` | — | `{items: [...], total}` | ANALYZE + visible_to 三维过滤 |
| `GET /analysis/reports/{report_id}` | — | 完整信封 | 不可见 → 404（不泄漏存在性） |
| `GET /analysis/reports/{report_id}/export`（`format=json` 或 `format=md`） | — | 附件下载（Content-Disposition；md 按 JSON 分节渲染，不返回大段自由文本） | EXPORT + 审计 |
| `GET /analysis/documents` | — | `[{doc_id, label, access_level, chunk_count}]`（可见文档清单，前端 MaterialPicker 数据源） | ANALYZE + visible_to 按 doc_id 聚合 |

错误码一览：401 未认证；403 缺 `analyze`（或导出缺 `export`）；400 未注册 task_type / qa 缺 question / custom 缺 instruction 或 schema sanitize 失败 / doc_ids 含不可见项；422 请求体 pydantic 校验失败；503 模型未配置或缺 key（`RuntimeError`）；404 报告不可见或不存在。

**审计点**（均经 `audit/service.py` `record_audit`）：`analyze_submit`（POST 请求侧，`resource_type="job"`）；`analyze`（worker 终态：成功 `resource_type="analysis_report"` + report_id / 失败 `resource_type="job"` + error）；`report_export`（导出端点）。

**worker 进度档**（`progress` + `progress_stage`，对齐 ingest 近似推进风格）：gather 10 → prompt 25 → llm 60 → verify 80 → persist 95 → done 100。

### 配置项清单（config.py Settings，双同步 .env.example）

| 字段（`CALLIODESMO_` 前缀） | 默认值 | 用途 |
|---|---|---|
| `analysis_model` | `""`（空 → 回退 `llm_model`） | 分析用模型；质量优先选型见 [[docs/model-selection|模型选型]] 预留 |
| `analysis_max_chunks` | `40` | 材料块数截断上限 |
| `analysis_max_input_chars` | `24000` | 材料文本总字符预算（结构化输出 token 约 2-3x 的成本闸） |
| `analysis_parse_retries` | `2` | 解析 / 校验回喂重试预算（可降 0 退化单次解析） |
| `analysis_custom_schema_max_bytes` | `4096` | 自定义 schema 序列化字节上限 |
| `analysis_temperature` | `0.2` | 分析采样温度 |
| `eval_analysis_golden_file` | `"config/golden_analysis.yaml"` | 分析金标集路径 |

`.env.example` 同步新增 7 项，并**补齐现存 12 个未进 `.env.example` 的 Settings 字段**（vector_store_backend / graph_store_backend / community_store_backend / llm_disable_thinking / ocr_image_max_bytes / vision_image_max_bytes / embedding_api_base / extraction_template_file / chunk_size / chunk_overlap / doc_community_clustering / doc_cluster_threshold，Task 3 逐项对账，以 `Settings.model_fields` 与 `.env.example` 键集合 diff 为空为准）。

### 前端数据契约（frontend/src/api/types.ts，与后端逐字段对齐）

```ts
export type AnalysisTaskType =
  | "summary" | "key_information" | "timeline" | "entity_recognition"
  | "relation_mapping" | "tasks" | "concepts" | "qa" | "custom";

export interface AnalysisJobRequest {
  task_type: AnalysisTaskType; doc_ids?: string[]; question?: string | null;
  custom?: { instruction: string; schema?: Record<string, unknown> } | null; top_k?: number;
}
export interface AnalysisEnvelope {
  task_type: AnalysisTaskType; status: "ok" | "partial" | "failed";
  generated_at: string; model: string; prompt_version: string;
  usage: Record<string, number>; warnings: string[]; source_chunk_ids: string[];
  payload: Record<string, unknown>;  // 按 task_type 判别，逐类 interface 对齐 analysis/schemas.py
}
export interface ReportListItem {
  id: string; task_type: AnalysisTaskType; status: string; subject_label: string;
  access_level: string; library_scope: string; model: string; created_at: string;
  source_chunk_count: number;
}
// PERMISSIONS 常量追加 ANALYZE: "analyze"；JobOut 消费侧扩 task_type?/report_id?
```

UI 克隆三组既有资产，**不新增前端依赖**：① `features/qa/AskPanel.tsx` 手写分段按钮组（`MODES` 数组 `{value, label, icon}` + `cn()` 高亮）做 9 类选择器；② `features/ingest/IngestPage.tsx` + `useIngest.ts` 异步全套（`useMutation` POST→202+job_id + `useQuery` 轮询 `refetchInterval` 函数式：非终态 1200ms、终态返回 `false` 停、`enabled` 门控 + 进度条 + `STAGE_LABEL` 阶段文案 + 失败重试面板）；③ `features/collab/ContributionDetail.tsx` 的 StatCard + Radix Tabs 分节 + Dialog 懒加载做报告详情。缺 progress / table / accordion / markdown 渲染器处沿用现有手写替代（保持一致）；报告按 JSON 分节渲染，不返回大段 markdown。

### 纯函数与可测性纪律

`prompts.render` / `parser` 全链 / `verify_evidence` / `compute_report_access_level` / `sanitize_schema` / 注册表查询 / 模板加载——全部无夹具可单测，保 CI（`-m "not db"`）覆盖；DB 相关（`db/migrate.py` 补列、报告持久化、材料采集、API 全链、worker）打 `@pytest.mark.db` 走真 PG + `calliodesmo_test` schema 每测 TRUNCATE。维持串行测试（neo4j 夹具全图清空，禁 `pytest -n`）。

## 技术栈（追加式）

| 类别 | 追加 | 说明 |
|:--|:--|:--|
| 报告模型 | pydantic v2（既有） | 9 类各建报告模型 + 公共信封；扁平、键名语义化、有限取值 enum、每字段 description |
| 结构化解析 | extra `analysis`：轻量 json-repair 小库 | 运行时懒加载 + 缺依赖回退正则抢救；不引 instructor / LangChain（吸收模式自实现解析链） |
| 模板 | `config/analysis_prompts/*.txt` + `{token}` 替换（自实现，GraphRAG 范式） | 头部 `# version: N`，运行记录落 `prompt_version` |
| 评估 | 字段 / 元组级 P-R-F1（确定性）+ G-Eval rubric judge（judge 自身走同一解析链） | golden 集 `config/golden_analysis.yaml`；judge 先于完整金标上线，参考分而非硬门槛 |
| 前端 | 无新依赖 | React 19 / TanStack Query / shadcn 拷贝件，克隆既有模式 |
| 依赖纪律 | 无新重依赖 | `uv sync` 默认不装 `analysis` extra，降级路径有测试；与既有 extra 惯例一致 |

---

## Task 1: 前置批——闭环 collab 时区 TODO + deps.py 锚点顺延 ✅ 必做

**目标：** 清偿两处逾期尾巴：`collab/service.py:18` 链路时区缺失（原锚点 2026-W31 逾期）是 DB 时间正确性坑，必须**先于 Task 12 新 ORM 落库**修掉；`api/deps.py:89` ProfileCard/BM25 改 PG（原锚点 2026-W33 逾期）因 P6 材料路径不依赖 BM25，显式顺延 P9 并改锚点为 2026-W49。

**Files:** 改 `src/calliodesmo/collab/models.py` / `collab/service.py`（时间列 `timezone=True`）· 改 `src/calliodesmo/api/deps.py`（:89 TODO 锚点与去向注释）· 测试 `tests/test_collab*.py` 扩展。

- [x] **Step 1:** 写失败测试：collab 时间字段带时区往返断言（存入 tz-aware、读出不丢时区信息）。
- [x] **Step 2:** 跑确认失败（`uv run pytest -v` 相关用例红）。
- [x] **Step 3:** 实现：collab ORM 时间列（`collab/models.py` reviewed_at/merged_at 等）补 `timezone=True`，移除 :18 TODO 标记；`deps.py:89` 锚点改 2026-W49 并注明「与 store list 谓词下推同批（P9）」。**既有库迁移**：`create_all` 不改既有表列型，既有库（含 dev 库）需 `ALTER COLUMN reviewed_at/merged_at TYPE TIMESTAMPTZ USING <col> AT TIME ZONE 'UTC'`——工具实现由 Task 11 `db/migrate.py` 列型回填承接，落地后在 dev 库冒烟一次 approve/merge；窗口期（本 Task → Task 11）内**先跑迁移再合并代码**，否则既有库 contributions 表写 aware datetime 即报错。
- [x] **Step 4:** 跑绿：`uv run ruff format . && uv run ruff check . && uv run pytest -v` 全量回归不红。
- [x] **留痕:** 测试走 `create_all` 全新表（直出 TIMESTAMPTZ）不受影响；既有库迁移缺口由 Task 11 `db/migrate.py` 列型回填（含 `@pytest.mark.db` 测试）与本步 dev 库冒烟承接，不留模糊「评估」。
- [x] **Step 5:** 提交：`fix(db): 闭环协作时区逾期 TODO 并顺延 ProfileCard/BM25 锚点至 P9`。

---

## Task 2: Permission.ANALYZE 全链路 + seed 回填修复 ✅ 必做

**目标：** 新增 `analyze` 权限并门控全部分析端点（Task 14 消费）；**同批修复** `auth/service.py` `seed_default_roles` 对已存在角色直接 `continue` 的回填缺陷——否则既有部署重跑 `db seed` 后新权限不回填、**全员 403**。这是本阶段最危险的坑，修复与权限新增必须同一批次。角色分配：analyst = {ingest, query, export, push, **analyze**}、reviewer = {query, export, push, approve, **analyze**}、admin = `set(Permission)` 自动全集（决策 1）。

**Files:** 改 `src/calliodesmo/auth/models.py`（`Permission.ANALYZE` + `DEFAULT_ROLE_PERMISSIONS`）· 改 `src/calliodesmo/auth/service.py`（`seed_default_roles` 差集回填）· 改 `frontend/src/api/types.ts`（`PERMISSIONS.ANALYZE` 常量）· 改 `frontend/src/auth/useAccess.ts`（如需 `canAnalyze` 便捷方法）· 测试 `tests/test_seed_roles_backfill.py`（新）+ 既有权限矩阵测试扩展。**注意**：本 Task **不**加导航项——`/app/analysis` 路由 Task 19 才落，提前挂导航会出现死链；导航门控与 Task 19 路由注册同批。

- [x] **Step 1:** 写失败测试：回填幂等——先以旧权限集合建角色（无 analyze），重跑种子后权限**并集**含 analyze、不丢旧权限、不重复；二次 seed 权限集不变；三角色权限集合断言。
- [x] **Step 2:** 跑确认失败（现实现 `continue`，必红）。
- [x] **Step 3:** 实现：枚举加 `ANALYZE = "analyze"`、角色映射更新、`seed_default_roles` 改「已存在角色比对 `DEFAULT_ROLE_PERMISSIONS` 补缺失 `RolePermission` 行」；前端常量（导航门控归 Task 19）。
- [x] **Step 4:** 跑绿：后端种子幂等 / 权限矩阵回归 + 前端三件套（含 `analyze` 常量与 `canAnalyze` 单测断言；导航渲染断言归 Task 19）。
- [x] **回滚纪律:** 只 revert 代码，**不回滚已写入数据库的权限数据**（回收权限会把既有部署锁死在 403）；回填逻辑有幂等测试，重复执行安全。
- [x] **Step 5:** 提交：`feat(auth): 新增 analyze 权限并修复种子角色权限回填`。

---

## Task 3: Settings 分析配置项 + .env.example 全量对账 ✅ 必做

**目标：** 新增 7 个分析配置项进 `Settings`（`CALLIODESMO_` 前缀）；借机**补齐现存 12 个 Settings 字段未进 `.env.example` 的欠账**，建立「字段 ↔ 样例」对账纪律。

**Files:** 改 `src/calliodesmo/config.py` · 改 `.env.example` · 测试 config 用例扩展。

- [x] **Step 1:** 写失败测试：7 字段（`analysis_model` / `analysis_max_chunks` / `analysis_max_input_chars` / `analysis_parse_retries` / `analysis_custom_schema_max_bytes` / `analysis_temperature` / `eval_analysis_golden_file`）的前缀加载与默认值。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 7 字段；逐项对账 `Settings` 全部字段补进 `.env.example`（含既有欠账 12 项：vector_store_backend / graph_store_backend / community_store_backend / llm_disable_thinking / ocr_image_max_bytes / vision_image_max_bytes / embedding_api_base / extraction_template_file / chunk_size / chunk_overlap / doc_community_clustering / doc_cluster_threshold，注释说明取值，不改变任何默认值；完成口径 = `Settings.model_fields` 与 `.env.example` 键集合 diff 为空）。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(config): 分析配置项进 Settings 并补齐 .env.example 对账`。

---

## Task 4: 报告契约 I——公共信封与证据校验（纯函数）✅ 必做

**目标：** 冻结所有下游（注册表 / 解析 / 评估 / 前端）共用的信封与证据结构。

**Files:** 新 `src/calliodesmo/analysis/__init__.py` · `src/calliodesmo/analysis/schemas.py`（公共层）· `src/calliodesmo/analysis/evidence.py` · 测试 `tests/test_analysis_schemas.py`。

- [x] **Step 1:** 写失败测试：`AnalysisStatus`（ok/partial/failed，非法值报错）；`Evidence(chunk_id, quote)` 非空校验；`AnalysisEnvelope`（task_type / status / generated_at / model / prompt_version / usage / warnings / source_chunk_ids / payload）；`verify_evidence(envelope, sources)`——quote 去空白后非源文子串的证据置信封顶 0.3 + warning，失败占比 >30% → partial（纯函数，无夹具）。`Evidence` 为本层 pydantic 形态，与 `interfaces/analysis.py` 的 dataclass `EvidenceRef` 一一对应互转（引擎内部流转 `EvidenceRef`、契约层用 `Evidence`，见架构节「信封装配」）。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 `schemas.py` 公共层 + `evidence.py`。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): 报告公共信封与证据子串校验`。

---

## Task 5: 报告契约 II——9 类报告模型与任务注册表（契约先行）✅ 必做

**目标：** **一次性定义全部 9 类报告 pydantic 模型**（契约完整、交付分批）+ `AnalysisTaskSpec` 注册表骨架；第一批 5 类注册，其余 4 类模型先立、接线留 Task 21–22。

**Files:** 改 `src/calliodesmo/analysis/schemas.py`（9 类模型）· 新 `src/calliodesmo/analysis/specs.py` · 测试 `tests/test_analysis_specs.py`。

- [x] **Step 1:** 写失败测试：9 类各一条正例 + 关键反例——`SummaryReport`（summary + key_points）；`KeyInfoReport`（label/value 条目）；`TimelineReport`（date_normalized ISO 8601 + date_raw + granularity exact/approximate/relative）；`EntityRecognitionReport`（name/type/description）；`RelationMappingReport`（head/tail/type/description）；`ActionItemReport`（action/owner_raw/deadline_raw，「任务」类模型名避免与 Job 混淆）；`ConceptReport`（name/definition/related）；`QAReport`（question/answer/citations）；`CustomReport`（fields 开放字典）。每条 item 带 `confidence`（0–1 区间校验）与 `evidence` 列表（缺证据自动降置信的校验器）。注册表按 `task_type` 可取 spec，未注册抛 `KeyError`。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现模型 + `AnalysisTaskSpec`（type / output_cls / template_name / stub_marker / max_retries）+ `BUILTIN_ANALYSIS_SPECS`（本批注册 5 类；`build_custom_spec` 声明留 Task 22）。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): 九类报告模型与任务注册表（契约先行）`。

---

## Task 6: 提示词模板与构造（第一批 5 类）✅ 必做

**目标：** 模板入版本化文件 + 纯函数渲染，运行记录可追溯 `prompt_version`。

**Files:** 新 `config/analysis_prompts/{summary,key_information,timeline,entity_recognition,qa}.txt`（头部 `# version: 1`，含 `[ANALYSIS:<type>]` 标记）· 新 `src/calliodesmo/analysis/prompts.py` · 测试 `tests/test_analysis_prompts.py`。

- [x] **Step 1:** 写失败测试：`{materials}` / `{question}` / `{schema}` 令牌替换；双闸截断边界（render 侧预算执行，`analysis_max_chunks` + `analysis_max_input_chars`；采集侧截断见 Task 9）；版本号解析为 `prompt_version = "<type>.v<version>"`；模板遵循 `ecl/extractor.py` 范式断言（系统角色声明 + 「严格只输出一个 JSON 对象」+ 输出 schema 示例）；时间线模板含 ISO 8601 归一化 + 锚点换算 + 模糊时间落 `relative` 不得臆造精确日期的指引。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 5 份模板 + `render_prompt` 纯函数。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): 第一批五类提示词模板与渲染函数`。

---

## Task 7: 解析回退链（质量生命线）✅ 必做

**目标：** 统一解析回退链，任何 provider 输出走同一条路：剥围栏 / 散文包裹 → `json.loads` → json-repair（extra 懒加载）→ pydantic validate → ValidationError 回喂消息构造 → 预算耗尽部分抢救 + 降级。全部纯函数、无夹具、CI 可覆盖。

**Files:** 新 `src/calliodesmo/analysis/parser.py` · 改 `pyproject.toml`（新 extra `analysis`：轻量 json-repair 小库）· 测试 `tests/test_analysis_parser.py`。

- [x] **Step 1:** 写失败测试：围栏剥离；散文夹 JSON 提取；非法 JSON 抛 `AnalysisParseError` 带 200 字片段（仿 `_parse_json` 惯例）；无 extra 时降级正则花括号抢救且友好报错；pydantic 失败时回喂消息含错误定位 + 原输出截断片段；重试预算耗尽 → 部分抢救可校验字段（partial）/ 抢救不出（失败信号）；预算可经配置降 0。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 `parser.py`；`pyproject.toml` 挂 extra（运行时懒加载，缺依赖回退不报硬错）。
- [x] **Step 4:** 跑绿（含不装 extra 的降级路径）。
- [x] **Step 5:** 提交：`feat(analysis): 结构化解析链与回喂重试机制`。

---

## Task 8: StubLLM 分析标记分发（9 类一次落齐）✅ 必做

**目标：** 桩按系统提示中的 `[ANALYSIS:<type>]` 标记分发固定 JSON（不用裸词，避免与既有抽取关键词冲突）；**每类型一条关键词契约测试**，钉死「标记写错 → 静默回退抽取输出而测试不红」的坑。9 类一次落齐，避免批次间回改桩。

**Files:** 改 `src/calliodesmo/providers/stub_llm.py` · 测试 `tests/test_stub_llm_analysis.py`。

- [x] **Step 1:** 写失败测试：9 类各一条——桩输出能被 Task 5 对应报告模型 `model_validate` 通过（含时间线 ISO 日期、枚举取值）；未知 `[ANALYSIS:*]` 标记显式报错（不静默回退抽取输出）；既有抽取 / 检索桩行为零回归。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 9 类标记分发（仅分析标记分支显式报错，非分析提示词保留既有回退行为）。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(providers): StubLLM 九类分析标记分发与契约测试`。

---

## Task 9: 材料采集器（安全红线）✅ 必做

**目标：** 把「提交参数 → 可见材料 + 源文映射 + 可选图谱上下文」收敛为一个可单测的采集器，封死枚举越权面（红线一），不依赖内存态 BM25（红线二）。

**Files:** 新 `src/calliodesmo/analysis/materials.py` · `src/calliodesmo/analysis/access.py` · 测试 `tests/test_analysis_materials.py`（`@pytest.mark.db`）。

- [x] **Step 1:** 写失败测试：全量拉取 + `visible_to` 过滤（`stores/visibility.py` 谓词）；**越权红线**——`doc_ids` 仅作成员筛选且逐条复核可见性，不可见 ID 静默剔除（防枚举探测），断言材料集合；双闸截断；返回 `chunk_id → 源文` 映射供证据校验；实体 / 关系类附带 `graph_store` 相关实体与关系（经 `visible_to`，不重新抽取）；断言不触碰内存态 `sparse_index`；`compute_report_access_level` 边界（全 public 材料 → INTERNAL；含 secret 材料 → SECRET）。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 `gather_materials` + `compute_report_access_level`（纯函数）。
- [x] **留痕:** 三 store list 无谓词下推，大规模优化 → P9（2026-W49）。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): 材料采集器（可见性红线 + 截断 + 图谱复用 + 密级继承纯函数）`。

---

## Task 10: AnalysisEngine + interfaces/analysis.py + factory ✅ 必做

**目标：** 冻结 `interfaces/analysis.py` 全部形状；第一批 5 类端到端离线可跑；引擎可插拔（接口抽象 + factory），问答类走 `SearchEngine`、实体类读图。

**Files:** 新 `src/calliodesmo/interfaces/analysis.py` · `src/calliodesmo/analysis/engine.py` · `src/calliodesmo/analysis/factory.py` · 测试 `tests/test_analysis_engine.py`。

- [x] **Step 1:** 写失败测试：`build_analysis_engine` 复用 `retrieval/factory.build_llm_provider` 路由规则（`test/*` → 桩；localhost / `ollama/` / `lm-studio/` 豁免 key；缺 key `RuntimeError` 带配置指引）；5 类各一条离线端到端（材料 → prompt → 桩 → 解析 → 证据自验 → 信封 status=ok 且 prompt_version/usage 落位）；问答类经构造注入的 `SearchEngine`（离线用例注入内存 stores + test/stub 装配的实例，**不经 `api/deps.get_search_engine()`**）`.query` 包成 `QAReport`（来源标注沿用 `[chunk_id]` 约定）；回喂重试回路（注入假 provider 首次坏 JSON、二次正常）；预算耗尽 → 失败信号可读。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现接口（dataclass 全 frozen）+ `DefaultAnalysisEngine` + factory。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): 分析引擎与 factory（第一批五类接线）`。

---

## Task 11: Job 表泛化扩列 + db/migrate.py + JobOut 扩展 ✅ 必做

**目标：** Job ORM 扩列泛化为通用异步任务（复用轮询 / 进度状态机 / `reset_stale_running_jobs()`，不建第二套 worker 机械）；`create_all` 不给既有表加列 → 新增幂等补列工具；`JobOut` 兼容扩展。

**Files:** 改 `src/calliodesmo/db/models_job.py`（`task_type` / `task_payload`）· 新 `src/calliodesmo/db/migrate.py`（幂等补列 + 列型回填）· 改 `src/calliodesmo/cli.py`（`db init` 挂补齐）· 改 `src/calliodesmo/api/schemas.py`（`JobOut` 扩 `task_type` / `report_id` 带默认值）· 改 `src/calliodesmo/api/jobs.py`（`get_job` 透传 `task_type`，analyze 任务自 `Job.result` 指针解析 `report_id`）· 测试 `tests/test_db_migrate.py`（`@pytest.mark.db`）+ `tests/test_ingest_job_api.py` 全回归。

- [x] **Step 1:** 写失败测试：Job 携带 `task_type`（默认 `ingest`）+ `task_payload` JSON（写入前过 `json_safe`）；补列工具——建旧结构表 → `ensure_missing_columns` → 断言新列存在，全新库直出无需补齐；**列型回填**——建 contributions 旧型时间列（TIMESTAMP WITHOUT TZ）→ 补齐 → 断言 TIMESTAMPTZ（承接 Task 1 留痕的既有库迁移）；`GET /jobs/{id}` 对 analyze 返回 `task_type` 与自 result 指针解析的 `report_id`，对 ingest 恒 `task_type="ingest"` 且 `report_id=null`（防透传破坏旧消费方）；`reset_stale_running_jobs()` 对 analyze 任务同样生效（按状态不分类型）；`JobOut` 默认值保旧响应消费方不破坏。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现扩列 + `db/migrate.py`（补列 + 列型回填）+ `cli db init` 装配（`create_all` 之后）+ `api/jobs.py` 两字段透传；落地后对既有 dev 库重跑一次 `calliodesmo db init`（serve 不自动触发）。
- [x] **Step 4:** 跑绿（ingest job API 全回归零红）。
- [x] **回滚方式:** 新列中 `task_payload` 可空；`task_type` 为 NOT NULL + server_default `'ingest'`（存量行经默认值回填，旧代码不读不写新列，回滚后 INSERT 亦不受约束影响），ingest 主链路不受影响。
- [x] **Step 5:** 提交：`refactor(jobs): Job 表泛化支持 analyze 任务类型与幂等补列`。

---

## Task 12: AnalysisReportORM + ReportStore + 密级继承落库 ✅ 必做

**目标：** 报告持久化为三维权限一等公民（决策 2/4）；落库口径：仅 `ok` / `partial` 落行，完全失败走 job failed。

**Files:** 新 `src/calliodesmo/db/models_analysis.py` · 改 `src/calliodesmo/models.py`（集中导入注册）· 新 `src/calliodesmo/analysis/report_store.py` · 测试 `tests/test_analysis_report_store.py`（`@pytest.mark.db`）。

- [x] **Step 1:** 写失败测试：ORM 建表 + 五字段默认值 + `visible_to` 谓词联动（personal 报告他人不可见、低 `clearance` 看不到高密报告）+ `json_safe` 写入往返；ReportStore create / get / `list_visible`（clearance + scope + owner 三维过滤，分页 limit/offset）；`import calliodesmo.models` 覆盖新表（漏注册即红）。
- [x] **Step 2:** 跑确认失败（表不存在）。
- [x] **Step 3:** 实现 ORM（表结构见架构节 + 复合索引）+ `models.py` 注册 + ReportStore（PG 单后端）。
- [x] **Step 4:** 跑绿（真实 PG，`calliodesmo_test` schema 每测 TRUNCATE）。
- [x] **回滚方式:** 新表独立，drop 即退。
- [x] **Step 5:** 提交：`feat(analysis): 报告 ORM 与可见性存储（密级继承）`。

---

## Task 13: Worker 分析执行路径 ✅ 必做

**目标：** `task_type="analyze"` 执行体落地：进度分段、报告落库、终态审计、失败留痕；循 `ecl/job_worker.py` `run_ingest_job` 注入范式（`session_factory` / `engine` 经端点注入，测试可 override），无中央分发器。

**Files:** 新 `src/calliodesmo/analysis/job_worker.py` · 测试 `tests/test_analysis_job_worker.py`（`@pytest.mark.db`，barrier 同步等待）。

- [x] **Step 1:** 写失败测试：状态机 pending→running→succeeded/failed；进度分段 gather 10 / prompt 25 / llm 60 / verify 80 / persist 95 / done 100（带 `progress_stage`）；成功路径断言：AnalysisReport 落库（密级继承正确、scope=personal、owner=提交者）+ `Job.result={report_id, status}` + 终态审计 `analyze`（detail 含 status / model / prompt_version）；partial 路径：报告如实落库 + job succeeded；失败路径：`Job.error` 可读 + 审计 failed + 不落空报告；空材料 → failed("无可见材料")。
- [x] **Step 2:** 跑确认失败。
- [x] **Step 3:** 实现 `run_analysis_job(job_id, *, engine, session_factory, barrier=None)`（对齐 `run_ingest_job` 注入范式：用注入的 `session_factory` 自建会话，spec 自 `Job.task_payload` 读取；测试直接以 `_pg_engine` 构造的 `async_sessionmaker` 传入，或经端点依赖覆盖走 Task 14 范式）。
- [x] **Step 4:** 跑绿。
- [x] **Step 5:** 提交：`feat(analysis): worker 分析执行路径（进度 / 落库 / 审计）`。

---

## Task 14: 分析 API——提交 202 + 历史 / 详情 + 可见文档清单 + 双挂 ✅ 必做

**目标：** `/analysis` 路由上线，提交侧 1:1 复刻 ingest 范式（门控 → 请求边界校验 → Job(pending, task_type="analyze", task_payload) → `record_audit(analyze_submit)` → commit → `BackgroundTasks.add_task(run_analysis_job, ...)` → 202）。

**Files:** 新 `src/calliodesmo/api/analysis.py` · 改 `src/calliodesmo/api/app.py`（根 + `/api` 前缀双挂）· 改 `src/calliodesmo/api/schemas.py`（`AnalysisJobRequest` / `AnalysisAcceptedOut` / 报告出参）· 测试 `tests/test_analysis_api.py`（仿 `tests/test_ingest_job_api.py` 范式：`_test_settings()` 离线配置 + `get_job_session_factory` dependency_overrides + `_seed_actor` 自定义角色）。

- [ ] **Step 1:** 写失败测试：`POST /analysis/tasks` 无 analyze 权限 → 403；合法提交 → 202 + job_id + 审计 `analyze_submit`；未注册 task_type / qa 缺 question / doc_ids 含不可见项 → 400（不泄漏不可见文档存在性细节）；模型缺 key → 503（请求边界建引擎 RuntimeError→503 / ValueError→400 惯例）；`GET /analysis/reports` 三维过滤 + 分页；`GET /analysis/reports/{id}` 他人不可见 / 低 clearance → 404（不暴露存在性）；`GET /analysis/documents` 聚合可见文档（list_chunks + visible_to 按 doc_id 聚合，出参 `{doc_id, label, access_level, chunk_count}`，label 取 metadata 标题或回退 doc_id；三维可见性断言——这是 Task 19 MaterialPicker 的数据源）；端到端：POST → worker(barrier) → `GET /jobs/{id}` 见 `task_type`/`report_id` → 报告详情可见。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现路由 + 双挂。
- [ ] **回滚方式:** 摘除 `create_app` 中 router 挂载即整体下线，零数据影响。
- [ ] **Step 4:** 跑绿（三角色提交 / 读取矩阵断言全绿）。
- [ ] **Step 5:** 提交：`feat(api): 分析任务提交与报告查询端点`。

---

## Task 15: 报告导出端点（export 权限消费）✅ 必做

**目标：** `GET /analysis/reports/{id}/export` 上线，顺势消费前端一直零消费的 `export` 权限；默认 JSON 附件，`?format=md` 按 JSON 分节渲染（不返回大段自由文本）。

**Files:** 改 `src/calliodesmo/api/analysis.py` · 测试 `tests/test_analysis_api.py`（扩展）。

- [ ] **Step 1:** 写失败测试：无 export 权限 → 403；不可见报告 → 404；200 时 Content-Disposition 带文件名、内容与报告一致（md 分节含证据引用标注）；审计 `report_export`。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现端点。
- [ ] **Step 4:** 跑绿。
- [ ] **Step 5:** 提交：`feat(api): 报告导出端点（export 权限首次消费）`。

---

## Task 16: 评估 I——golden 集与确定性指标（expected_answer 落地）✅ 必做

**目标：** `GoldenCase.expected_answer` 首次被指标消费；字段 / 元组级 P-R-F1 为确定性硬指标（离线可跑、CI 友好）。

**Files:** 新 `config/golden_analysis.yaml` · 新 `src/calliodesmo/eval/golden_analysis.py` · `src/calliodesmo/eval/metrics_analysis.py` · 测试 `tests/test_eval_analysis_metrics.py`。

- [ ] **Step 1:** 写失败测试：golden 加载（第一批 5 类 × 每类 2 例小金标，复用既有 9 例小语料同源材料；QA 类含 `expected_answer`）；`field_f1`（条目级关键字段匹配）与 `tuple_f1`（实体/关系 (类型, 头, 尾) 元组对齐，双向匹配）的 P/R/F1 手算样例（空预测 / 全命中 / 部分命中边界）；`expected_answer` 为空跳过该指标。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现加载器 + 两指标（纯函数）；QA 类 `expected_answer` 参与字段比对。
- [ ] **Step 4:** 跑绿。
- [ ] **Step 5:** 提交：`feat(eval): 分析 golden 集与字段/元组级 F1`。

---

## Task 17: 评估 II——G-Eval judge + harness + eval_p6.py ✅ 必做

**目标：** rubric judge 上线（judge 自身走 Task 7 解析链，结构化评分，解析失败降级「无分」而非崩溃）；三用法脚本仿 `scripts/eval_p5.py` 落盘回归证据。

**Files:** 新 `src/calliodesmo/eval/judge_analysis.py` · 改 `src/calliodesmo/eval/harness.py`（扩展 AnalysisEvalHarness，`expected_answer` 消费路径）· 新 `scripts/eval_p6.py` · 测试 `tests/test_eval_analysis_judge.py`。

- [ ] **Step 1:** 写失败测试：judge rubric 四维（完整性 / 证据支撑 / 无编造 / 结构规范）→ 1–5 结构化评分；离线桩固定分（桩对生成质量零区分度——离线证据只承诺结构 / 契约，此断言写入测试注释）；harness 聚合输出含 `field_f1 / tuple_f1 / judge 均值` 与逐例明细。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现 judge + harness 扩展 + `scripts/eval_p6.py`（`--dump-golden` / 默认离线桩落盘 `p6-regression.json`（与 `p5-regression.json` 同级）/ `--real` 缺 key 友好报错）；脚本输出显式打印「离线证据≠质量证据」警示行。
- [ ] **留痕:** `--real` 真实模型补跑 → 用户本机，锚点 2026-W45（连同 `scripts/eval_p5.py --real` 同批），延误顺延 2026-W46。
- [ ] **Step 4:** 跑绿并记录离线基线入证据。
- [ ] **Step 5:** 提交：`feat(eval): G-Eval judge 与 eval_p6 三用法脚本`。

---

## Task 18: 前端 I——types / API 客户端 / useAnalysis hook ✅ 必做

**目标：** 前端数据层先行，vitest 克隆 `features/ingest/useIngest.test.tsx` 模式。

**Files:** 改 `frontend/src/api/types.ts`（ANALYSIS_TASK_TYPES 九类元数据 `{value, label, icon, batch}` + 契约类型；`PERMISSIONS.ANALYZE` 已在 Task 2 加入，勿重复）· 新 `frontend/src/features/analysis/api.ts` · `frontend/src/features/analysis/useAnalysis.ts` · `frontend/src/features/analysis/useAnalysis.test.tsx`。

- [ ] **Step 1:** 写失败测试（`vi.stubGlobal('fetch')` + QueryClientProvider + renderHook）：submit 返回 202 + job_id；轮询克隆 `useIngest.ts` 的 `refetchInterval` 函数式——非终态 1200ms、终态返回 `false` 停、`enabled` 门控；报告列表 / 详情 / 导出客户端。
- [ ] **Step 2:** 跑确认失败（`npm run test`）。
- [ ] **Step 3:** 实现 types / client / hook。
- [ ] **Step 4:** 跑绿三件套。
- [ ] **Step 5:** 提交：`feat(frontend): 分析域类型、API 客户端与轮询 hook`。

---

## Task 19: 前端 II——AnalysisPage 提交侧 + 轮询 ✅ 必做

**目标：** `/app/analysis` 提交体验：选类型 → 选材料 → 提交 → 进度可视 → 失败重试；全程走 `preview_*` 交互验证闭环。

**Files:** 改 `frontend/src/routes.tsx`（加一行 `{ path: "analysis", element: <AnalysisPage /> }`）· 改 `frontend/src/App.tsx`（NavItem `access.can(PERMISSIONS.ANALYZE)` 隐藏式门控——与 Task 2 常量在此会合）· 新 `frontend/src/features/analysis/AnalysisPage.tsx`（TaskTypePicker 克隆 AskPanel `MODES` 按钮组 + MaterialPicker 文档多选（消费 Task 14 的 `GET /analysis/documents`，仅可见项）+ qa 问题输入 + **QA 类「范围为全可见库」文案**（与风险表落点对齐）+ Skeleton 等待 + 进度条 + `STAGE_LABEL` 阶段文案 + destructive 错误盒 + 重试面板）· 测试 `frontend/src/features/analysis/AnalysisPage.test.tsx`。

- [ ] **Step 1:** 写失败测试：提交 mutation 参数组装；9 类选择器渲染第一批 5 类、其余灰显「即将上线」；MaterialPicker 消费 `/analysis/documents` 出参；无 `analyze` 权限时提交禁用。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现页面与组件（不引新 UI 依赖，缺件克隆既有手写替代）。
- [ ] **Step 4:** 跑绿三件套 → **preview 闭环**：`preview_start`（frontend-dev）+ 后端 `uv run calliodesmo serve --seed-demo --port 8200`；`preview_snapshot` 取 selector → 选类型 / 选材料 / 提交 → 进度条推进 → 成功；**权限矩阵可执行口径**：种子三角色均持 analyze（决策 1），preview 侧抽查三角色可见可用集合；无 analyze 场景（导航隐藏 / 直访 403）以后端测试的 `_seed_actor` 式自定义无权角色断言为准（Task 2/14 覆盖），或在 admin UI 手工建一个仅 query 权限的自定义角色用户验证（若角色管理 UI 不支持自定义角色，以 vitest/后端断言为准并留痕说明）；`preview_console_logs`(error) + `preview_network`(4xx/5xx) 双查；桌面 + 移动视口截图 + GLM-EYE 分析。
- [ ] **Step 5:** 提交：`feat(frontend): 分析提交页与任务轮询`。

---

## Task 20: 前端 III——ReportViewer + 历史 / 导出 + 三角色矩阵 ✅ 必做

**目标：** 报告按 JSON 分节渲染 + 历史列表 + 导出按钮 + 权限矩阵回归。

**Files:** 新 `frontend/src/features/analysis/ReportViewer.tsx`（Radix Tabs 分节 + StatCard 克隆 + 时间线有序列表（granularity 标注）+ 关系条目 + 证据 chips 展开 quote（克隆 AnswerCard 模式）+ 置信标记 + partial 状态横幅）· `frontend/src/features/analysis/ReportsHistory.tsx` · 组件 vitest。

- [ ] **Step 1:** 写失败测试：各节渲染存在性、证据展开、状态横幅、导出按钮对无 export 权限者禁用。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现组件。
- [ ] **Step 4:** 跑绿三件套 → **preview 闭环**：提交 → 轮询 → 报告分节 / 证据展开 / 导出下载；**三角色矩阵**（analyst 可提交可见自己报告 / reviewer 可提交（决策 1）/ admin 全集），与后端 `DEFAULT_ROLE_PERMISSIONS` 对齐；无权限场景（导航隐藏 / 直访 403 / 导出禁用）按 Task 19 口径——后端自定义角色断言为准，preview 抽查 + 留痕；桌面 + 移动视口截图 + GLM-EYE 归档。
- [ ] **Step 5:** 提交：`feat(frontend): 报告渲染、历史与导出（三角色矩阵通过）`。

---

## Task 21: 第二批接线——关系映射 / 任务 / 概念 ✅ 必做

**目标：** 契约与注册表已立，本批落剩余 3 个模板驱动类型的执行接线；关系映射读三层图数据复用（`graph_store` + `visible_to`，LLM 只组织、不重新抽取）。

**启用条件:** Task 17 离线基线落盘全绿 + Task 20 三角色矩阵通过；不满足则顺延，不带病增量。

**Files:** 新 `config/analysis_prompts/{relation_mapping,tasks,concepts}.txt` · 改 `src/calliodesmo/analysis/specs.py`（注册 3 类）· 测试（引擎离线端到端 ×3 + 桩契约回归——桩标记 Task 8 已落齐，此处仅验证）。

- [ ] **Step 1:** 写失败测试：3 类离线端到端（关系映射经图谱复用路径；`ActionItemReport` / `ConceptReport` 校验通过）。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现模板 + 注册。
- [ ] **Step 4:** 补 golden：关系映射 / 任务 / 概念各补 1–2 例进 `config/golden_analysis.yaml`（复用既有小语料同源材料），纳入 `eval_p6.py` 离线回归；跑绿 + 离线回归不回归。
- [ ] **Step 5:** 提交：`feat(analysis): 第二批接线（关系映射/任务/概念）`。

---

## Task 22: 自定义分析——sanitize + 动态 spec + 注入防御 ✅ 必做

**目标：** 用户指令 + 可选输出 schema 的自定义类型安全落地（用户 schema/指令有注入面，显式防御）；自定义指令只进 user 消息（与 system 隔离）。

**启用条件:** 同 Task 21——Task 17 离线基线落盘全绿 + Task 20 三角色矩阵通过；不满足则顺延，不带病增量。

**Files:** 新 `src/calliodesmo/analysis/sanitize.py` · 改 `src/calliodesmo/analysis/specs.py`（`build_custom_spec` + 注册 `custom`）· 改 `src/calliodesmo/api/analysis.py`（custom 分支）· 测试 `tests/test_analysis_sanitize.py`。

- [ ] **Step 1:** 写失败测试：`sanitize_user_schema` 拒 `$ref` / 递归嵌套 / 深度 >4 / 字段数 >30 / 序列化超 `analysis_custom_schema_max_bytes`；`build_custom_spec(instructions, schema)` 产物可被引擎消费且 provider 发送前裁剪为 JSON Schema 安全子集；指令注入探针——自定义指令试图覆盖 system 约束 / 越权读取材料范围外内容，执行器边界不变（材料仍全经 `visible_to`）；API 层 sanitize 失败 → 400 且错误可读。
- [ ] **Step 2:** 跑确认失败。
- [ ] **Step 3:** 实现 + 注册。
- [ ] **留痕:** 团队级自定义模板注册表（仿 `ecl/extraction_template.py`）→ P7 计划评估，锚点 2026-W47；完整 JSON Schema 校验（引 `jsonschema`）随团队级模板一并评估。custom 类无固定金标，评估口径 = 结构校验（sanitize 通过 + schema 符合）+ judge 参考分，验证报告中注明该口径（Task 23 落）。
- [ ] **Step 4:** 跑绿（第一批 5 类 + 第二批 3 类回归不红）。
- [ ] **Step 5:** 提交：`feat(analysis): 自定义分析（注入防御 + 动态 spec）`。

---

## Task 23: 第二批前端 + 验证报告 + 文档同步 + --real 补跑 ✅ 必做

**目标：** 第二批与自定义的前端渲染 + 双轨证据闭环 + 全量文档收尾。

**Files:** 改 `frontend/src/features/analysis/`（新 4 类选择与 ReportViewer 分节 + 自定义表单：指令 + 可选 schema JSON 输入（客户端 `JSON.parse` 预校验）+ 「指令将发给 LLM，勿含敏感信息」提示 + QA 类「范围为全可见库」文案复核）· 新 `docs/verification/P6-verification.md` · 改 `docs/verification/README.md`（索引登记）· 改 `docs/plans/roadmap.md` · **新建** `docs/plans/monthly/2026-09.md` / `2026-10.md` / `2026-11.md`（三份目前均不存在，按既有月计划 frontmatter（title/type/tags/created）+ wikilink 约定创建，覆盖 2026-W36–W46 的 P6 排期）· 改 `CLAUDE.md` + `AGENTS.md` 项目结构段与当前阶段段。

- [ ] **Step 1:** 写失败测试：第二批类型组件渲染 + 自定义表单校验提示。
- [ ] **Step 2:** 跑确认失败 → 实现 → 跑绿三件套 → preview 闭环（4 类各提交一次 + 自定义 400 提示路径 + 三角色回归抽查）。
- [ ] **Step 3:** 离线轨：`uv run pytest -v` 全量绿 + `python scripts/eval_p6.py` 落盘 `p6-regression.json` 留痕；质量轨（用户本机，锚点 2026-W45）：`python scripts/eval_p6.py --real`（[[docs/model-selection|模型选型]] 清单内至少一个真模型；本地模型走豁免规则），同批合并补跑 `scripts/eval_p5.py --real`；若解析失败率 > 5% 记入验证报告作为解析链调优依据。
- [ ] **Step 4:** 写 `docs/verification/P6-verification.md`（四要素：测试内容 / 技术栈 / 验证原理 / 验证过程 + Task 闭合矩阵 + 未竟清单），明确区分离线 / 质量两轨证据，注明 custom 类评估口径（见 Task 22 留痕）；`docs/verification/README.md` 报告清单表登记一行，**证据文件段登记 `p6-regression.json` 与 `p6-real-<模型名>.json`**（逐件列名，仿 `p5-regression.json` 格式）；`--real` 若延误，留痕顺延 2026-W46。
- [ ] **Step 5:** roadmap P6 状态更新 + 本计划 wikilink；月计划新建 / 对齐（见 Files；验证报告骨架与滚动更新自 W43/W44 随做随记，本步仅收口）；CLAUDE.md / AGENTS.md 项目结构段补 `analysis/` 域、`interfaces/analysis.py`、`db/models_analysis.py`、`db/migrate.py`、`scripts/eval_p6.py`，**当前阶段段（逐阶段 ✅ 列表）补 P6 完成行**；roadmap 移交注记：P7 段记多轮对话状态与团队级自定义模板注册表评估（锚点 2026-W47）及 e2e 链路补建，P8 段记报告生命周期（删除 / 版本化 / 复核流）与置信度校准（ECE）去向，P9 段记 L2 主题摘要（**注明 P2 原指派 P6、此处改道**）与 `api/deps.py:89`、谓词下推去向。
- [ ] **Step 6:** 提交：`feat(frontend): 第二批分析渲染与自定义表单` + `docs(verification): P6 验证报告与文档同步`（拆两笔亦可，均在本 Task 勾除）。

---

## Task 24（🔁 可选）: calliodesmo analyze CLI

**启用条件:** Task 14 完成后视剩余工时启动；非承诺，不做不欠。

**Files:** 改 `src/calliodesmo/cli.py`（子命令仿 `ask`：`--task-type` / `--doc-ids` / `--question` → 提交 + barrier 同步等待 + 打印报告摘要）· 测试（`cli_db` 夹具）。

- [ ] 写失败测试 → 跑确认失败 → 实现 → 跑绿 → 提交 `feat(cli): analyze 子命令`。若不做：留痕于验证报告未竟清单。

---

## Task 25（🔁 可选）: provider 原生结构化输出能力探测

**启用条件:** 承诺批次全绿后的机动工时；锚点不做则顺延 2026-W49（P9 模型层优化清单）。

**Files:** 改 `src/calliodesmo/analysis/factory.py`（探测 litellm 各后端 `response_format` / schema 支持度，支持则启用原生约束解码，不支持回退 Task 7 单路径；探测失败或未知一律回退）· 降级测试。

- [ ] 写失败测试 → 实现 → 跑绿 → 提交。留痕规则：探测不得引入多后端 if-else 沼泽破坏离线可测性（决策 6）。

---

## 暂缓与移交记录

- **多轮对话状态**（P5 唯一显式移交）：⏸ 暂缓 → P7。理由：超出 roadmap 对 P6「单次提交 → 单轮结构化输出」的定义；会话状态机械与工具调用在 P7 Agent 模式（ReAct/ReWOO/PlanExecute + LangGraph）是更自然的宿主；P6 产出的报告契约与任务注册表届时可被 Agent 直接消费，无返工。Task 23 在 roadmap P7 段落留移交注记。
- **L2 全库主题摘要**（P2-retrieval-rag.md:119 预留并指派 P6，此处显式改道）：⏸ 暂缓 → P9，锚点 2026-W49。理由：roadmap 的 P6 定义（9 类分析结构化报告）不含 L2；L2 依赖定时 / 增量重算基础设施；roadmap.md:54 对 L0/L1 分层摘要「仅展示层、不进检索链路」的定位表明摘要系展示资产，暂缓 L2 不伤检索质量。若 P9 重评通过，材料侧复用 `retrieval/global_search` 的社区摘要召回路径。

## 依赖与风险

| 风险 | 影响 | 防坑动作 | 落点 |
|:--|:--|:--|:--|
| `seed_default_roles` 对已存在角色 `continue`，新增权限不回填 → 既有部署全员 403 | 生产事故级 | 权限新增与回填修复**同批**，幂等测试先行（旧角色数据重跑种子后并集含新权限）；回滚只撤代码不撤已写权限 | Task 2 |
| StubLLM 标记写错静默回退抽取 JSON，测试不红 | 评估与契约全失真 | 9 类各一条契约测试（断言输出被对应报告模型 `model_validate` 通过）；未知分析标记显式报错 | Task 8 |
| 离线桩对生成质量零区分度 | 误把结构证据当质量证据 | 双轨验收口径硬性分离；脚本打印警示行；质量结论仅 `--real`（锚点 2026-W45） | Task 16/17/23 |
| 密级洗白：低密借分析接触高密材料 / 报告密级低于材料 | 越权泄露 | `compute_report_access_level = max(材料各级, INTERNAL)` + 材料获取全经 `visible_to`，两条红线测试先行 | Task 9/12 |
| 凭客户端 `doc_ids` 直取材料 → 枚举越权 | 越权泄露 | `doc_ids` 仅成员筛选、逐条复核可见性；不可见报告 404 不暴露存在性 | Task 9/14 |
| 自定义分析用户 schema/指令注入 | 越权 / 提示注入 | `sanitize_user_schema`（拒 `$ref`/递归/超深/超大）+ 指令只进 user 消息 + provider 发送前子集裁剪 | Task 22 |
| Job 扩列破坏既有 ingest 行与轮询 | 主链路回归 | 仅加可空列 + `server_default="ingest"` + `db/migrate.py` 幂等补列；`tests/test_ingest_job_api.py` 全绿作门槛 | Task 11 |
| litellm 多后端结构化输出支持度不一（钉版 `>=1.85,<1.91` 不动） | 解析失败率高 | v1 统一 prompt+解析+回喂重试+降级单路径；能力探测列可选（2026-W49） | Task 7 |
| 结构化输出 token 约 2-3x，成本与时延上升 | 用户体验 | `analysis_max_chunks` + `analysis_max_input_chars` 双闸截断（采集侧实现）+ 重试预算配置化 + 进度阶段展示 | Task 3/9（render 侧预算见 Task 6） |
| QA 类 `doc_ids` 范围限定缺位（谓词下推 P9） | 功能边界 | UI 文案明示「问答范围为全可见库」；留痕 2026-W49 | Task 10/19 |
| `--real` 补跑依赖用户本机与模型额度 | 验收缺质量证据 | 不阻塞发布；验证报告留痕 + 顺延周次（最迟 2026-W46）；与 P5 `--real` 同批 | Task 23 |
| json-repair 引入 | 依赖纪律 | 轻量纯 Python，走 extra + 懒加载 + 缺依赖回退正则抢救（双路径有测试）；引入前 tavily 核对版本与许可 | Task 7 |
| 时间风险（学生 10-15h/周） | 交付顺延 | 两批交付 + 契约先行减少返工 + W45 后半段收口；可选任务最先牺牲 | 节奏建议 |
| 尾部超载：W43–W45 承载前端 + 第二批 + 收尾重任务 | 交付顺延 | 文档同步项（验证报告骨架、roadmap / 月计划滚动更新）W43/W44 随做随记、W45 仅收口；任一周欠账即触发范围重审，可选 #24/#25 最先让位 | 节奏建议 |

## 节奏建议（学生 10-15h/周，2026-09 W36 起）

| 周次 | 日期 | Task | 要点 |
|:--|:--|:--|:--|
| 2026-W36 | 08/31–09/06 | #1–#3 | 前置闭环 + 权限回填修复（高危坑）+ 配置对账，打地基 |
| 2026-W37 | 09/07–09/13 | #4–#5 | 契约冻结：信封 + 九模型 + 注册表（一次性定义，分批交付） |
| 2026-W38 | 09/14–09/20 | #6–#8 | 模板 + 解析链（质量生命线）+ 桩 9 类契约一次落齐 |
| 2026-W39 | 09/21–09/27 | #9–#10 | 材料采集器（安全红线）+ 引擎（第一批离线端到端跑通） |
| 2026-W40 | 09/28–10/04 | #11–#12 | Job 泛化 + 幂等补列（含 collab 列型回填）+ 报告持久化 |
| 2026-W41 | 10/05–10/11 | #13–#14 | worker + 分析 API（后端主链贯通，全阶段最重一周） |
| 2026-W42 | 10/12–10/18 | #15–#17 | 导出 + 评估两件套 + 离线基线落盘（先立质量参照） |
| 2026-W43 | 10/19–10/25 | #18–#19 | 前端数据层 + 提交页（preview 闭环）；文档同步项自本周随做随记 |
| 2026-W44 | 10/26–11/01 | #20–#21 | ReportViewer + 三角色矩阵 + 第二批接线（启用条件：#17 基线绿；#20 同周先行于 #21） |
| 2026-W45 | 11/02–11/08 | #22–#23 | 自定义注入防御 + 第二批前端 + 验证报告 + 文档收口；`--real` 补跑（用户本机，含 P5 `--real`） |
| 2026-W46 | 11/09–11/15 | 缓冲 / #24–#25 机动 | 可选任务消化；未竟项按各自锚点移交；移交 P7（2026-W47 起） |

**缓冲规则**：任何一周欠账顺延，可选任务（#24–#25）最先让位；承诺批次（#1–#23）不允许跨入 2026-W46 之后，否则触发范围重审。`--real` 补跑周次随之顺延但必须在验证报告中更新留痕周次。