---
title: Calliodesmo 实施路线图
type: roadmap
created: 2026-07-26
---
# Calliodesmo 实施路线图

> [!info] 三层知识图谱驱动的智能情报分析平台
> 本文件为**年计划**（日/周/月/年四层之顶），向下 wikilink 到月计划、周计划与阶段任务计划。所有计划文档均以 Obsidian 原生 markdown 存于 `docs/plans/`。

## 摘要

GraphRAG（索引基座）+ LlamaIndex/LangGraph（检索与 Agent 编排）混搭；LLM 与嵌入走可切换抽象接口。多用户采用**混合模型**（团队库 + 项目库 + 个人库，三层），协作借鉴 **Git-like 推送流程**（个人库 -> 项目库 -> 团队库，经审核合并）。文档社区管理 v1 同时完成选项 A（自动派生 + 手动策展）与选项 B（独立聚类/版本/合并/回滚，并入 P4）。API+CLI 优先，Web UI 在 P2 基础问答跑通后启动并随后续阶段迭代。按学生独立开发、适中节奏（10-15h/周）排期。

## 已锁定决策

- 语言：Python 3.11+；uv 管理依赖
- LLM 后端：混合可切换（LiteLLM 统一接口，接 OpenAI/Qwen/DeepSeek/Ollama 本地）
- 嵌入：BGE-M3 本地 + `EmbeddingProvider` 可切换接口
- 索引基座：GraphRAG 作可插拔组件（库形式集成，仅必要时局部 fork 单模块）
- 检索/Agent 编排：LlamaIndex + LangGraph
- 语料语言：中英双语
- 图数据库：Neo4j（语义层）
- 向量+元数据：PostgreSQL 16 + pgvector（v1），`VectorStore` 接口可换 Qdrant/Milvus
- 交付形态：API（FastAPI）+ CLI（Typer）优先；Web UI 在 P2 后启动
- 规模：v1 单机 ≤5k 文档，六个抽象接口保证可扩展到 ≥50万
- 多用户模型：混合（团队库 + 项目库 + 个人库，三层）
- 协作模型：Git-like 推送（个人库 -> 项目库 -> 团队库，审核/合并/图谱合并）
- 认证：v1 本地账号（账号密码 + JWT），预留 OIDC/SSO 接口位
- 文档社区管理：v1 同时完成选项 A + 选项 B（A：自动派生并入 P1、手动策展 UI 并入 P3；B：并入 P4）
- 节奏：学生 10-15h/周，暑期集中、学期适中、考试期降负

## 用户、权限与用户组（三维正交模型）

权限由三个正交维度组合控制，加上用户组做团队组织：

- **角色 RBAC**（控"能做什么"）：`analyst` / `reviewer` / `admin`。细粒度权限：`ingest` / `query` / `export` / `push` / `approve` / `manage_users` / `manage_community`。
  - 表：`users` / `roles` / `role_permissions` / `user_roles(user_id, role_id, scope)`
- **访问等级 clearance**（控"能看什么"）：`public` / `internal` / `confidential` / `secret`。用户有 clearance，文档/社区/实体有 access_level，检索需 `clearance >= access_level` 才可见。
- **库范围 scope**（控"谁的数据"，三层）：`personal`（个人库）/ `project`（项目库，一个项目多人维护、属于一个团队）/ `team`（团队库，一个团队多个项目）。
- **团队与项目**（团队组织 + 项目隔离，取代原 user_groups）：
  - `team`（团队）：一个团队有多个项目；团队库为团队共享情报全貌。
  - `project`（项目）：属于一个团队，由多人维护；项目库为项目协作空间。
  - 用户可被授予**不同 project / team 的不同角色**（如 A 项目 analyst、B 项目 reviewer）；角色 RBAC + clearance + scope 三维组合，按当前操作所在的 project/team 判定。
  - 表：`teams(id, name, desc)` / `projects(id, name, desc, team_id)` / `team_members(user_id, team_id, role_in_team)` / `project_members(user_id, project_id, role_id, role_in_project)`。
- **统一上下文**：`AccessContext(userId, roles, clearance, project_id, team_id, project_role, team_role)` 贯穿请求全生命周期，按当前 project/team 聚合权限，检索器/合成器/Agent 统一接收做过滤。
- **审计日志**：每次访问/导出/推送/合并/审核记录（谁/何时/做了什么/从哪来）。P0 打骨架，P9 硬化（审计查询 UI、留存策略、导出管控、数据溯源）。

> [!example] 权限判定示例
> 分析师 A（clearance=confidential，组"X调查组"）可读组织库中 access_level≤confidential 且组内有权的社区；可 push 但不能 approve；reviewer 可 approve 本组贡献。

## Git-like 协作模型

**混合库结构（三层）**
- 个人库（personal，≈ fork/工作库）：每用户私有空间，自己 ingest/建图/分析，可选私有或共享。
- 项目库（project，≈ 分支协作库）：一个项目多人维护，项目内审核合并；属于一个团队。
- 团队库（team，≈ main/origin）：团队共享情报全貌（多个项目汇总），按 clearance 可读，写只能经审核推送。
- 所有业务表带 `library_scope` / `library_id` / `owner_id` / `project_id` / `team_id` / `access_level`。

**推送流程**
- 推送(Push)：把个人库策划好的内容（文档+抽取实体+社区摘要）提议合并到项目库；项目库可进一步推送到团队库（团队级汇总）。
- 贡献请求(MR)：状态机 `draft -> submitted -> approved/rejected -> merged`。
- 审核(Review)：reviewer/admin 批准，覆盖权限（能推什么、谁能批、access_level 合并时继承）。
- 合并(Merge)：应用到组织库，核心是**图谱合并**（实体按 name+type/embedding 去重、关系并集、来源打标）。
- 差异(Diff)：贡献内容清单。
- 拉取(Sync)：个人库同步组织库最新。
- 回滚(Revert)：撤销已合并贡献（v2 精化）。

**v1 务实范围**：推送=提交一批文档+抽取结果到组织库审核；合并=批量写入+按 name+type 实体去重、关系并集、来源打标；审核=状态机。复杂冲突解决/版本/回滚留 v2。

## 三层图谱与 ECL 管线

**三层存储**
- 情景层：Postgres（原始文本块+元数据）+ pgvector（块向量）。
- 语义层：Neo4j（实体/关系/事件/概念 = 节点与边，带属性与来源指向）。
- 高层摘要层：pgvector（社区摘要向量）+ Postgres（摘要文本+社区层级元数据）。

**ECL 管线**
- Extract：实体/关系/声明/协变量四类全量抽取，各自定制 prompt；**团队抽取模板软引导**（模板外实体保留+打标，不限定死；新类型 review-gated 沉淀 P4）。
- Cognify：实体消解（碎片实体合并，一等公民）+ 图谱构建 + Leiden 社区检测 + 社区摘要。
- Load：三层数据落库，写入个人库。

## 文档社区管理

**选项 A（v1）**
- 自动派生：实体社区经 `MENTIONS` 反查成员文档 -> 自动文档社区。
- 手动策展：分析师建/命名/打标签/设 access_level/合并/拆分/增删文档/把自动社区提升为命名策展社区。
- 自动并入 P1，手动管理 UI 并入 P3。
- 表：`document_communities(id, name, desc, scope, library_id, owner_id, access_level, derived_from_entity_community_id, ...)` + `document_community_members(community_id, document_id, added_by, added_at, note)`。

**选项 B（v1，并入 P4）**
- 独立文档嵌入聚类引擎（不依赖实体图）。
- 社区版本/分支/合并（git-branch 式管理社区）。
- 社区回滚。

## 精度与评估原则

> [!info] 精度不靠切分完美，而在多层补救 + 数据度量（模型选型详见 [[docs/model-selection|模型选型建议]]）。来自架构审视的结论。

- **评估 harness（贯穿项）**：golden 集 + 检索召回/精排命中率/答案忠实度等指标回归，自 P1/P2 起逐步建立；**精度由数据判定，不靠猜**。
- **精度杠杆排序**：①评估 harness ②检索混合+交叉编码器重排 ③实体消解（P1 Task3）④结构感知切分+overlap（P1 Task2，过门槛）⑤切 size 调参。切分属中游杠杆，**精度主要在检索重排与实体消解挣回**。
- **嵌入三输出**：BGE-M3 的 dense+sparse+multi-vec **全用**，不止 dense（sparse 近 BM25、multi-vec 近 ColBERT）。
- **抽取模板（软引导）**：团队级、user 可编辑、配置文件可改；模板外实体保留+打标（`template_conforming`/`discovered_types`），不 reject；新类型 review-gated 沉淀（P4）。
- **切分**：结构感知（标题/代码块/表原子 + 段句兜底 + overlap）过门槛；分层父子 + 上下文富化（contextual retrieval）+ 语义切分**推迟 P5**。
- **L0/L1 分层摘要**：写时为 chunk/社区生成超短摘要供**用户侧展示**（列表预览、导航提示、档案卡叙述字段），**不进入向量检索/rerank/生成链路**（摘要不污染模型判断）。**P1 仅在 Chunk.summary 预留可选字段**（填 None，不写生成逻辑）；P2/P5 按需补生成，仅服务展示层。参考 OpenViking L0/L1/L2 三层，但其为树形目录递归，本项目为图+社区，取其分层理念非目录递归。
- **精度边界**：跨 chunk 关系抽取、别名/指代歧义在 MVP 不完美，靠结构感知切分 + 实体消解 + `source_chunk_ids` 溯源缓解，**P8 证据验证硬化**。

## 阶段计划（P0-P9）

优先级逻辑：先打通"数据进 -> 建图 -> 能问问题"主链路（P0-P2），UI 紧随启动（P3）；Git-like 协作推送作为多用户核心能力紧接（P4）；高级检索/分析/Agent 依次推进；差异化验证放后段；规模化收尾。

- **P0 地基脚手架**：docker-compose(Postgres+pgvector/Neo4j)、配置密钥、三接口(LLMProvider/EmbeddingProvider/DocumentLoader)+默认实现、**用户/角色/权限/用户组表+JWT 认证+AccessContext+审计骨架**、CI+冒烟测试。
- **P1 ECL 管线 MVP（系统心脏）**：**多格式文档解析（txt/md/csv/json/yaml/html 等基础内置，pdf/Office/开放文档/富文本/邮件/笔记本 等可拓展插件，详见 [[docs/plans/phases/P1-ecl-pipeline|P1 计划]] Task 1）**、Extract 四类抽取（团队抽取模板软引导，模板外保留+打标；review-gated 沉淀 P4）、Cognify(实体消解一等公民+图谱+Leiden 社区检测+社区摘要)、Load 三层数据落库(写个人库)、**文档社区自动派生**、CLI `ingest` 建图、**实体档案卡自动生成（ProfileCard：结构化字段从图+Covariate 确定性聚合，可进模型上下文增强可读性；narrative 叙述字段不进检索链路仅供人读；用户编辑归 P4）**。
- **P2 基础检索与 RAG（里程碑）**：NativeRAG(情景层)/LocalSearch(语义层)/GlobalSearch(摘要层)、**混合检索**（稠密 BGE-M3 三输出 + 稀疏 BM25 + 图，RRF 融合）+ **交叉编码器重排**（`bge-reranker-v2-m3`；向量与 rerank 均打原文，不打摘要）、答案标注来源文本块、按 AccessContext 过滤可见语料、FastAPI+CLI 暴露 Q&A。**此为"基础功能完善"节点。**
- **P3 Web UI（启动并持续迭代）**：登录注册、个人/组织库视图、问答面板、**用户/用户组管理 UI（添加/编辑/删除/查询、角色与组成员，受 `manage_users` 保护；service/CLI/API 管理端点同期补全）**、**文档社区手动管理 UI**、角色可见性。用 `frontend-design` skill 构建。
- **P4 Git-like 协作推送**：个人库 -> 项目库 -> 团队库、贡献/审核/合并状态机、图谱合并(实体去重/关系并集/来源打标)、**抽取模板新类型 review-gated 沉淀**（团队模板随语料生长，经审核并入）、推送审核指派到组、**文档社区选项 B（独立文档嵌入聚类引擎 + 社区版本/分支/合并 + 社区回滚，v1 完成）**。
- **P4.5 持久化与生产化（P3/P4 桥接）**：stores 真后端持久化（pgvector/Neo4j/Postgres）、增量索引 MVP（文档指纹 + 受影响子图 delete + 字段级合并）、P4 合并落库贯通与双写一致性修复、前端 ingest UI + 异步 job、embedding 三段式实体对齐 + 人工复核。详见 [[docs/plans/phases/P4.5-persistence-production|P4.5 计划]]。
- **P5 高级 RAG 与智能检索**：MultiQuery / RAGFusion / SubQuestion；Corrective(CRAG) / SelfCheck / Adaptive；**分层切分 + 上下文富化（contextual retrieval）/ 语义切分**（精度精化）；混合检索与重排成熟。
- **P6 LLM 分析任务（9 类）**：摘要、关键信息、时间线、实体识别、关系映射、任务列表、概念解释、问答、自定义提示。输出结构化报告。
- **P7 Agent 模式**：ReAct / ReWOO / PlanExecute（LangGraph）+ 工具定义，权限内行动。
- **P8 证据验证与幻觉检测（差异化）**：答案-证据映射、接地度评分(NLI/LLM-as-judge)、跨文档交叉验证、低接地声明标记疑似幻觉。
- **P9 动态更新与规模化**：用 Qdrant/Milvus 置换验证 VectorStore、Celery+Redis 异步批处理、**审计硬化/合规/多租户压测**、社区规模化增量算法。> [!note] **增量索引 MVP 已剥离到 P4.5**：文档指纹 + 受影响子图 delete + 字段级合并的增量索引 MVP，连同 stores 持久化、摄入 UI、三段式复核，已移至 [[docs/plans/phases/P4.5-persistence-production|P4.5 持久化与生产化]]；P9 仅保留规模化/置换/异步批处理/合规压测 scope。

## Obsidian 计划文档结构

全部存于 `docs/plans/`，markdown + wikilinks，Obsidian 直接可读：

- `roadmap.md`（本文件）- **年计划**：P0-P9 路线图 + 月份里程碑 + 校历节奏。
- `monthly/<YYYY-MM>.md` - **月计划**：当月推进的阶段、周里程碑、验收点。
- `weekly/<YYYY-Www>.md` - **周计划**：含**日计划**表格（每日 checklist 行，约 2h 一个工作块）。
- `phases/P<n>-<slug>.md` - **阶段任务计划**：用 `writing-plans` skill 生成，bite-sized TDD 步骤。

四层关系：年定里程碑 -> 月拆周 -> 周拆日 -> 阶段任务给最细粒度可执行步骤。详见 [[monthly/2026-08|2026-08 月计划]] 与 [[phases/P0-scaffolding|P0 阶段任务]]。

## 时间表（学生 10-15h/周）

- 2026-08（暑假）：P0 地基 + P1 启动
- 2026-09：P1 建图完成 + P2 启动
- 2026-10：P2 基础问答完成 + P3 Web UI 启动
- 2026-11：P3 Web UI MVP + P4 协作推送启动
- 2026-12：P4 推进（期末降负）
- 2027-01（寒假）：P4 完成 + P5 高级检索
- 2027-02：P5 完成 + P6 分析任务
- 2027-03：P6 完成 + P7 Agent
- 2027-04：P7 完成 + P8 证据验证
- 2027-05：P8 完成 + P9 规模化
- 2027-06：稳定、打磨、文档、收尾

整体跨度约 11 个月，与学年节奏对齐。

## .gitignore 范围

Python(`__pycache__/`、`*.pyc`、`.venv/`、`*.egg-info/`、`dist/`、`build/`) · 密钥(`.env`、`.env.local`) · IDE(`.vscode/`、`.idea/`) · 系统(`.DS_Store`、`Thumbs.db`) · 数据日志(`data/`、`logs/`、本地 DB 卷) · Obsidian vault 本地配置(`.obsidian/` 整目录，不上传)。

## 后续精化（v2）

- 图谱合并：同名不同义实体冲突解决、版本/回滚、按调查任务开分支。
- 认证：接入 OIDC/SSO。
- 规模化：大规模分布式索引与检索。

## 第一步实施动作

1. 建仓库骨架：`pyproject.toml`(uv)、`src/calliodesmo/` 包结构、`tests/`、`.gitignore`、`.env.example`、`docker-compose.yml`。
2. 用 `obsidian-markdown` skill 在 `docs/plans/` 生成首月 `monthly/2026-08.md` 与首周 `weekly/2026-W31.md`（含日计划表）。
3. 用 `writing-plans` skill 生成 `phases/P0-scaffolding.md` 阶段任务计划。
4. 按 P0 逐步实现：docker-compose、用户/角色/权限/用户组表+JWT+AccessContext+审计、三接口默认实现、冒烟测试、CI 骨架。

## 假设与默认

- Neo4j 作语义层图库（文档已指定）；Postgres+pgvector 起步，`VectorStore` 接口可换。
- GraphRAG 以库形式集成，仅必要时局部 fork 单模块；检索/Agent 用 LlamaIndex+LangGraph 独立搭建。
- 中英双语：BGE-M3 嵌入 + 双语抽取 prompt；LLM 走 LiteLLM 多后端可切换。
- v1 单机 docker-compose 起步；六个抽象接口（LLMProvider/EmbeddingProvider/VectorStore/GraphStore/DocumentLoader/IndexingEngine）保证可换以支撑 ≥50万 扩展。
- API+CLI 先行；Web UI 在 P2 后启动并随后续阶段迭代。
- 权限三维（角色 RBAC + clearance + 库范围）+ 用户组；认证本地 JWT 起步预留 SSO。
- 用户/用户组管理 CRUD（添加/编辑/删除/查询）延后至 P3 落地；P1/P2 期间仅 `db seed` 建初始管理员，其余靠直接库操作。
- 三层库（个人/项目/团队）取代原 personal/org 两层：需修订 P0 已实现的 `LibraryScope`（`PERSONAL/ORG` -> `PERSONAL/PROJECT/TEAM`）、`UserRole`、`UserGroup`（拆为 `Team`/`Project` 及成员角色表）与 `AccessContext`，并同步迁移测试与 `db seed`。
- 节奏默认 10-15h/周；考试期降负、假期集中，按校历动态调整周计划。
