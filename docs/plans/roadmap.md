---
title: Calliodesmo 实施路线图
type: roadmap
created: 2026-07-26
---
# Calliodesmo 实施路线图

> [!info] 三层知识图谱驱动的智能情报分析平台
> 本文件为**年计划**（日/周/月/年四层之顶），向下 wikilink 到月计划、周计划与阶段任务计划。所有计划文档均以 Obsidian 原生 markdown 存于 `docs/plans/`。

## 摘要

GraphRAG（索引基座）+ LlamaIndex/LangGraph（检索与 Agent 编排）混搭；LLM 与嵌入走可切换抽象接口。多用户采用**混合模型**（共享组织库 + 个人沙箱），协作借鉴 **Git-like 推送流程**（个人库经审核合并到组织库）。文档社区管理 v1 走自动派生 + 手动策展（选项 A），重活列为后续精化（选项 B）。API+CLI 优先，Web UI 在 P2 基础问答跑通后启动并随后续阶段迭代。按学生独立开发、适中节奏（10-15h/周）排期。

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
- 多用户模型：混合（共享组织库 + 个人沙箱）
- 协作模型：Git-like 推送（个人库 -> 组织库，审核/合并/图谱合并）
- 认证：v1 本地账号（账号密码 + JWT），预留 OIDC/SSO 接口位
- 文档社区管理：v1 选项 A（自动派生 + 手动策展）；选项 B 列为后续精化
- 节奏：学生 10-15h/周，暑期集中、学期适中、考试期降负

## 用户、权限与用户组（三维正交模型）

权限由三个正交维度组合控制，加上用户组做团队组织：

- **角色 RBAC**（控"能做什么"）：`analyst` / `reviewer` / `admin`。细粒度权限：`ingest` / `query` / `export` / `push` / `approve` / `manage_users` / `manage_community`。
  - 表：`users` / `roles` / `role_permissions` / `user_roles(user_id, role_id, scope)`
- **访问等级 clearance**（控"能看什么"）：`public` / `internal` / `confidential` / `secret`。用户有 clearance，文档/社区/实体有 access_level，检索需 `clearance >= access_level` 才可见。
- **库范围 scope**（控"谁的数据"）：`personal` / `org`。
- **用户组 user_groups**：把用户组织成调查组/项目组。
  - 组可拥有共享社区/库；组内角色继承（组管理员管成员、指派组内 reviewer）；推送审核可指派到组。
  - 表：`user_groups(id, name, desc, scope)` / `user_group_members(user_id, group_id, role_in_group)`
- **统一上下文**：`AccessContext(userId, roles, clearance, library_scope, group_ids)` 贯穿请求全生命周期，检索器/合成器/Agent 统一接收做过滤。
- **审计日志**：每次访问/导出/推送/合并/审核记录（谁/何时/做了什么/从哪来）。P0 打骨架，P9 硬化（审计查询 UI、留存策略、导出管控、数据溯源）。

> [!example] 权限判定示例
> 分析师 A（clearance=confidential，组"X调查组"）可读组织库中 access_level≤confidential 且组内有权的社区；可 push 但不能 approve；reviewer 可 approve 本组贡献。

## Git-like 协作模型

**混合库结构**
- 个人库（personal，≈ fork/工作库）：每用户私有空间，自己 ingest/建图/分析，可选私有或共享。
- 组织库（org，≈ main/origin）：团队共享情报全貌，按 clearance 可读，写只能经审核推送。
- 所有业务表带 `library_scope` / `library_id` / `owner_id` / `access_level`。

**推送流程**
- 推送(Push)：把个人库策划好的内容（文档+抽取实体+社区摘要）提议合并到组织库。
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
- Extract：实体/关系/**事件**/**概念**四类全量抽取，各自定制 prompt；Schema-Free 默认 + Schema-Constraint 配置项。
- Cognify：图谱构建 + Leiden 社区检测 + 社区摘要。
- Load：三层数据落库，写入个人库。

## 文档社区管理

**选项 A（v1）**
- 自动派生：实体社区经 `MENTIONS` 反查成员文档 -> 自动文档社区。
- 手动策展：分析师建/命名/打标签/设 access_level/合并/拆分/增删文档/把自动社区提升为命名策展社区。
- 自动并入 P1，手动管理 UI 并入 P3。
- 表：`document_communities(id, name, desc, scope, library_id, owner_id, access_level, derived_from_entity_community_id, ...)` + `document_community_members(community_id, document_id, added_by, added_at, note)`。

**选项 B（后续精化 v2）**
- 独立文档嵌入聚类引擎（不依赖实体图）。
- 社区版本/分支/合并（git-branch 式管理社区）。
- 社区回滚。

## 阶段计划（P0-P9）

优先级逻辑：先打通"数据进 -> 建图 -> 能问问题"主链路（P0-P2），UI 紧随启动（P3）；Git-like 协作推送作为多用户核心能力紧接（P4）；高级检索/分析/Agent 依次推进；差异化验证放后段；规模化收尾。

- **P0 地基脚手架**：docker-compose(Postgres+pgvector/Neo4j)、配置密钥、三接口(LLMProvider/EmbeddingProvider/DocumentLoader)+默认实现、**用户/角色/权限/用户组表+JWT 认证+AccessContext+审计骨架**、CI+冒烟测试。
- **P1 ECL 管线 MVP（系统心脏）**：Extract 四类抽取(Schema-Free+Schema-Constraint)、Cognify(图谱+Leiden 社区检测+社区摘要)、Load 三层数据落库(写个人库)、**文档社区自动派生**、CLI `ingest` 建图。
- **P2 基础检索与 RAG（里程碑）**：NativeRAG(情景层)/LocalSearch(语义层)/GlobalSearch(摘要层)、答案标注来源文本块、按 AccessContext 过滤可见语料、FastAPI+CLI 暴露 Q&A。**此为"基础功能完善"节点。**
- **P3 Web UI（启动并持续迭代）**：登录注册、个人/组织库视图、问答面板、**用户/用户组管理 UI（添加/编辑/删除/查询、角色与组成员，受 `manage_users` 保护；service/CLI/API 管理端点同期补全）**、**文档社区手动管理 UI**、角色可见性。用 `frontend-design` skill 构建。
- **P4 Git-like 协作推送**：个人库 -> 组织库、贡献/审核/合并状态机、图谱合并(实体去重/关系并集/来源打标)、推送审核指派到组。
- **P5 高级 RAG 与智能检索**：MultiQuery / RAGFusion / SubQuestion；Corrective(CRAG) / SelfCheck / Adaptive。
- **P6 LLM 分析任务（9 类）**：摘要、关键信息、时间线、实体识别、关系映射、任务列表、概念解释、问答、自定义提示。输出结构化报告。
- **P7 Agent 模式**：ReAct / ReWOO / PlanExecute（LangGraph）+ 工具定义，权限内行动。
- **P8 证据验证与幻觉检测（差异化）**：答案-证据映射、接地度评分(NLI/LLM-as-judge)、跨文档交叉验证、低接地声明标记疑似幻觉。
- **P9 动态更新与规模化**：增量索引(情景层追加+定期重算社区)、用 Qdrant/Milvus 置换验证 VectorStore、Celery+Redis 异步批处理、**审计硬化/合规/多租户压测**。

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

Python(`__pycache__/`、`*.pyc`、`.venv/`、`*.egg-info/`、`dist/`、`build/`) · 密钥(`.env`、`.env.local`) · IDE(`.vscode/`、`.idea/`) · 系统(`.DS_Store`、`Thumbs.db`) · 数据日志(`data/`、`logs/`、本地 DB 卷) · Obsidian 本地缓存(`.obsidian/workspace.json`、`.obsidian/workspace-mobile.json`、`.obsidian/cache`，保留其余共享配置)。

## 后续精化（v2）

- 文档社区选 B：独立文档嵌入聚类引擎、社区版本/分支/合并、社区回滚。
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
- 节奏默认 10-15h/周；考试期降负、假期集中，按校历动态调整周计划。
