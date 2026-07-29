---
title: P4 Git-like 协作推送实施计划
type: phase-plan
phase: P4
tags:
  - plan/phase
created: 2026-07-29
---
# P4 Git-like 协作推送实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P3-web-ui|P3]] / [[docs/plans/phases/P5-advanced-rag|P5]]。

> [!important] 前置条件（开工前确认）
> - **基线**：P4 分支从 **P3 合并后的 main** 切出（`codex/p4-git-collab`）。P3 的管理/浏览后端、`require_permission` 守卫、`AppStores` 依赖工厂、前端 SPA 已在 main；本阶段在其上叠加协作域，不动既有检索/问答链路。
> - **双轨存储认知（关键）**：**MR 元数据（状态/审核/指派/版本）走 ORM**（SQLAlchemy，与 `auth`/`audit` 同库，事务可持久、可查询）；**被推送的图谱数据（chunk/entity/relation/community）走内存 stores**（`AppStores` 单例，单进程共享）。合并 = 从源库读记录 -> 改写 access 字段到目标 scope -> upsert 回同一 stores。**单进程下 Sync 隐式**：`visible_to` 已跨 scope 聚合，用户查询天然可见自己有权访问的项目/团队库数据，无需显式拉取；分布式 Sync/增量同步留 P9。
> - **并发控制认知（关键，【修订】）**：状态机流转（submit/approve/reject/merge）走 **DB 事务 + 行锁/乐观锁**（`Contribution.version` 字段），防多 reviewer 并发重复审核或 merge double-click 绕过终态检查。多 reviewer 并发审核是 v1 现实场景，**非 v2**。
> - **崩溃一致性认知（【修订】）**：合并跨两轨写（内存 stores + ORM）非原子，中途崩溃可能状态不一致；内存 stores 不持久，重启后数据丢失。v1 接受此限制（演示/单机），可选两阶段（ORM 先 MERGING -> 合并 stores -> MERGED）便于崩溃检测；持久化 stores 留 P9。
> - **MVP 裁剪线**（预先声明，防超时）：Task 7 独立文档聚类用"阈值连通分量"最简实现（标准库，与现有 `ConnectedComponentsDetector` 零依赖风格一致；**不引 scikit-learn**，networkx Louvain 可选 extra）；Task 8 社区分支/回滚 v1 做**版本快照 + append 式回滚**（回滚=用旧版本快照创建新版本，不删历史，非栈式只回滚上一版），不做完整 git DAG 三方合并；Task 9 前端以贡献面板为主，社区版本视图可降级为只读版本列表。
> - **MVP 必做清单**（达标线）：Task 1 + Task 2 + Task 3 + Task 4 + Task 5 + Task 9 Step 5 权限回归。命中即 P4 协作推送核心达标；Task 6（review-gated 沉淀）、Task 7+8（社区选项 B）、Task 9 前端完整版属持续迭代，按周补齐。**社区选项 B 整体为 v1 必交付**（路线图明确"v1 完成"），但允许分步落地、先 API 后 UI。
> - **本计划已对照现有代码与业界方案修订【修订】**：契合度缺口与设计加强以【修订】标注散落各 Task 与「依赖与风险」段；社区检测走 Louvain（非 Leiden），见 Task 7 与 §风险。

**Goal:** 实现 Git-like 协作推送：个人库 -> 项目库 -> 团队库的**贡献/审核/合并状态机**与**图谱合并**（实体按 `(name,type)` 去重、关系并集、来源打标），审核指派到组；**抽取模板 review-gated 沉淀**（团队模板随语料生长、经审核并入）；**文档社区选项 B**（独立嵌入聚类引擎 + 社区版本/分支/合并/回滚）。API+CLI 优先，前端在 P3 SPA 上叠加贡献与社区管理视图。

**Architecture:** 协作域独立为 `collab/` 包。**贡献请求(MR)** 为 ORM 模型（`Contribution` + 状态机 `draft->submitted->approved/rejected->merged/closed`），经 `ContributionService` 驱动流转，全程记审计（`push`/`submit`/`approve`/`reject`/`merge`）。**推送**收集源 scope 记录成**内容清单(manifest)**（按 `doc_ids` 聚合 chunk/entity/relation/community）；**合并**对清单做图谱合并后 upsert 进目标 scope（改写 `library_scope`/`owner_id`/`project_id`/`team_id`，`access_level` 取较严 max），实体按 `(name,type)` 去重（并 `source_chunk_ids`/描述、打 `provenance` 来源标），关系按 `(source,target,type)` 并集去重。权限：`push` 创建/提交、`approve` 审核批准/合并；自审阻断（源用户不能审/合自己）；审核可指派到目标 scope 内持 `approve` 成员。stores 补"按 owner/scope 枚举"能力供推送收集。复用 P3 `require_permission` + `visible_to` + 审计（`audit/service.record_audit(session, *, user_id, action, resource_type, resource_id, detail, source)`，AuditLog action 已含 push/approve/merge）+ 前端 SPA 基座。**【修订】并发**：`Contribution` 加 `version` 乐观锁字段，状态机流转事务内行锁/version 校验。

**Tech Stack（P0-P3 基础上追加）:**
- 后端：FastAPI `/collab/*` + `/admin/community-versions/*` 端点 · Typer CLI `contributions` 子命令 · SQLAlchemy ORM（`Contribution`/`CommunityVersion`）· 内存 stores 扩展（按 owner 枚举 + 图谱合并纯函数）
- 聚类（Task 7）：BGE-M3 文档嵌入（复用 `EmbeddingProvider`）+ 阈值连通分量聚类（networkx 已在用），**不引 scikit-learn**（重依赖/Windows wheel 风险）
- 模板沉淀（Task 6）：YAML 写回（PyYAML 已在用）+ review-gated 状态
- 前端：React 19 + TanStack Query（P3 已立）· 贡献面板 + 社区版本视图（增量叠加）
- 测试：`pytest` + `httpx`（端点 × 角色 × 状态码矩阵）；前端 `vitest` + Playwright（贡献/审核/合并关键流程截图）

---

### Task 1: 贡献请求(MR)数据模型与状态机

**目标：** 立协作域 `collab/` 包，定义贡献请求(MR) ORM 模型与状态机。`Contribution` 记录"谁、把什么、从哪个库、推到哪个库、处于何状态"；状态机 `draft -> submitted -> approved/rejected -> merged`（外加 `closed` 撤销）。状态流转经 `ContributionService`，非法跳转报错。新增 ORM 模型在 `models.py` 集中导入（保证 `Base.metadata` 注册完整）。

**Files:**
- Create: `src/calliodesmo/collab/__init__.py`
- Create: `src/calliodesmo/collab/models.py`（`ContributionStatus` 枚举 + `Contribution` ORM）
- Modify: `src/calliodesmo/models.py`（导入 `Contribution`）
- Create: `src/calliodesmo/collab/service.py`（`ContributionService`：create/submit/approve/reject/merge/close + list/get）
- Test: `tests/test_contribution_models.py`、`tests/test_contribution_service.py`

**数据模型：**

```python
class ContributionStatus(enum.StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    CLOSED = "closed"

class Contribution(Base):
    __tablename__ = "contributions"
    id: UUID pk
    source_user_id: FK("users.id")        # 推送发起人
    source_scope: Enum(LibraryScope)       # personal / project（源库范围）
    target_scope: Enum(LibraryScope)      # project / team（目标库范围，须高于源）
    target_project_id: FK nullable        # target_scope=project 时填
    target_team_id: FK nullable           # target_scope=team 时填
    title: str
    description: Text
    status: ContributionStatus default DRAFT
    doc_ids: JSON                         # 推送的文档 id 列表（内容清单的锚）
    manifest: JSON                        # 差异清单（Task 2 填：各类型 id+计数）
    assignee_id: FK("users.id") nullable  # 审核指派（Task 3）
    reviewed_by: FK nullable / reviewed_at
    merged_at: nullable
    created_at / updated_at
```

- [ ] **Step 1:** `collab/models.py`：`ContributionStatus` + `Contribution` ORM（字段见上，`target_scope` 须 `rank > source_scope`，rank: personal=0/project=1/team=2）；**rank 实现【修订】**：`LibraryScope` 现为 StrEnum 无 rank，给其加 `@property rank`（不改枚举值，不影响序列化）或 collab 层内置 `_SCOPE_RANK` 映射；`models.py` 注册导入；测试建表后表存在 -> 实现跑绿
- [ ] **Step 2:** `ContributionService.create(session, *, source_user, source_scope, target_scope, target_project_id/team_id, title, doc_ids, description)`：校验 target 高于 source、目标 id 与 target_scope 匹配；建 DRAFT 贡献；记审计 `action="push"`（source="api"/"cli"）测试 -> 实现跑绿
- [ ] **Step 3:** 状态机流转：`submit`（draft->submitted）、`approve`（submitted->approved，Task 3 接 `approve` 守卫 + 自审阻断）、`reject`（submitted->rejected）、`close`（draft/submitted->closed）；非法跳转抛 `ValueError`（如 draft 直接 approve）测试 -> 实现跑绿。**【修订】状态机取舍**：v1 至少做 `rejected -> submitted` reopen（保留同一 MR 上下文，作者修改重提，非新建 MR）；`changes_requested`（submitted ↔ changes_requested）可选，v1 不做则在 §风险 注明"rejected 后 reopen 复用 MR，不引入 changes_requested 中间态"
- [ ] **Step 4:** `list_contributions(*, access, status=None, target_scope=None)` / `get_contribution(id, *, access)`：按 AccessContext 过滤可见贡献（源用户本人 或 目标 scope 内有权）；越权返回 None/空列表测试 -> 实现跑绿
- [ ] **Step 5（【修订】并发）:** `Contribution` 加 `version: int`（SQLAlchemy `version_id_col` 乐观锁）；`submit`/`approve`/`reject`/`merge`/`close` 流转在 DB 事务内 `SELECT ... FOR UPDATE` 锁行后校验状态机再写，或依赖 version 校验（影响 0 行则冲突重试/报 409）；防并发重复 approve 与 merge double-click 绕过终态测试 -> 实现跑绿

**验收：** 贡献状态机流转正确（合法通过/非法抛错）；越权贡献不可见；审计有 `push` 记录。

---

### Task 2: 源库枚举与推送差异(Diff)

**目标：** 给 stores 补"按 owner/scope 枚举"能力（推送收集的前提）；`PushService` 收集源 scope 记录成**内容清单(manifest)**并算差异(Diff)：本次推送的 chunk/entity/relation/community 清单与计数 + 与目标库的重叠判定，供审核人审阅。manifest 写回 `Contribution.manifest`。

**Files:**
- Modify: `src/calliodesmo/interfaces/vector_store.py`（`VectorStore` 加 `list_chunks(*, access) -> list[ChunkRecord]`）
- Modify: `src/calliodesmo/interfaces/graph_store.py`（`GraphStore` 加 `list_entities(*, access)` / `list_relations(*, access)`）
- Modify: `src/calliodesmo/providers/in_memory_vector_store.py` / `in_memory_graph_store.py`（实现枚举，按 `visible_to` 过滤）
- Create: `src/calliodesmo/collab/push.py`（`PushService`：collect + build_manifest + diff）
- Test: `tests/test_push_manifest.py`

- [ ] **Step 1:** stores 枚举接口 + 内存实现：`list_chunks`/`list_entities`/`list_relations`（`list_communities` 已有）；全部按 `visible_to` 过滤（personal 仅 owner 可见、project 仅项目成员、team 仅团队成员）测试 -> 实现跑绿。**【修订】接口与 in_memory 实现同 PR 落地**（P3 教训：避免"接口立了实现没跟上"的半切）
- [ ] **Step 2:** `PushService.collect(contribution, *, stores)`：按 `doc_ids` 从源库枚举 chunk（按 `doc_id` 过滤）、entity/relation（按 `source_chunk_ids` 命中这些 chunk）、community（member 命中 entity 或 doc）；越权源库不收集测试 -> 实现跑绿
- [ ] **Step 3:** `build_manifest`：聚合清单（各类型 id 列表 + 计数 + 与目标库的重叠判定：目标已存同名同类型实体数）；写回 `Contribution.manifest`；记审计 `push` 测试 -> 实现跑绿
- [ ] **Step 4:** `diff(contribution)`：返回清单摘要（新增实体 N、关系 M、chunk K、社区 C、冲突/已存实体数 D）供审核展示测试 -> 实现跑绿

**验收：** 推送能枚举源库内容并生成清单；差异摘要可读；越权源库不可枚举。

---

### Task 3: 审核(Review)与指派到组

**目标：** 审核流转 + 指派。`submit` 把 DRAFT 提交为 SUBMITTED 并**指派审核人**（显式指定，或自动指派到目标 scope 内首个持 `approve` 权限成员）。`approve`/`reject` 需 `APPROVE` 权限且**非自审**（源用户不能审自己）。全程审计。

**Files:**
- Modify: `src/calliodesmo/collab/service.py`（`submit(*, assignee_id=None)` 自动指派 / `approve` / `reject` 接 `require_permission` + 自审阻断）
- Test: `tests/test_contribution_review.py`

- [ ] **Step 1:** `submit`：DRAFT->SUBMITTED；`assignee_id` 显式则用之，否则自动指派目标 scope 内首个有 `approve` 权限成员（project->项目成员、team->团队成员）；无可用 reviewer 时置 `assignee_id=None` 并在 manifest 标注"待指派"测试 -> 实现跑绿
- [ ] **Step 2:** `approve`：需 `APPROVE` 权限 + 非自审（`reviewer_id != source_user_id`）；submitted->approved；记 `reviewed_by`/`reviewed_at` + 审计 `approve`；无权 -> 403、自审 -> ValueError 测试 -> 实现跑绿
- [ ] **Step 3:** `reject`：submitted->rejected；记审计 `reject` + 原因（`detail={"reason": ...}`）测试 -> 实现跑绿
- [ ] **Step 4:** 指派到组：目标为 team 时候选=该 team 成员中持 `approve` 者；目标为 project 时候选=该项目成员持 `approve` 者；自动指派确定性取首个（按 user_id 排序）测试 -> 实现跑绿。**【修订】team 查询路径**：`TeamMember` 仅有 `role_in_team` 字符串字段、无 RBAC 角色外键（与 `ProjectMember.role_id` 不同），team 候选 = `TeamMember.team_id == target_team` 且该用户 `UserRole` 全局含 `APPROVE` 权限（**不按 `role_in_team` 字符串匹配**，脆弱）；project 候选走 `ProjectMember.role_id` 关联的 `DEFAULT_ROLE_PERMISSIONS`

**验收：** 审核状态流转 + 权限守卫（approve/reject 需 APPROVE）+ 自审阻断 + 指派到组（显式/自动）。**自审策略【修订】**：draft/submit/close 允许作者自操作；approve/reject/merge 阻断自审（`reviewer_id != source_user_id`）。

---

### Task 4: 图谱合并(Merge)与来源打标

**目标：** `MergeService.merge`：approved 贡献合并进目标 scope。核心是**图谱合并**--实体按 `(name,type)` 去重（目标已存则并 `source_chunk_ids`/描述、`access_level` 取较严 max），关系按 `(source,target,type)` 并集去重，chunk/community upsert 并改写 scope 字段；**来源打标(provenance)**：每条合并记录记 `metadata["provenance"]`（`contribution_id` + `source_user_id` + `merged_at`）。合并后 status->MERGED + `merged_at` + 审计 `merge`。

**Files:**
- Create: `src/calliodesmo/collab/graph_merge.py`（`merge_into_target(source_entities, source_relations, target_store, *, target_access_fields, provenance)` 纯函数式合并）
- Create: `src/calliodesmo/collab/merge.py`（`MergeService.merge(contribution, *, access, stores)`：collect -> 改写 scope -> 图谱合并 -> upsert 目标 -> 状态收尾）
- Test: `tests/test_graph_merge.py`、`tests/test_merge_service.py`

- [ ] **Step 1:** `merge_graph` 实体合并：按 `(name,type)` 去重--目标已存则并 `source_chunk_ids`（去重）、描述拼接（去重换行）、`access_level` 取较严 max、打 provenance；新实体直接加 provenance 写入；`template_conforming` 取或（任一为真则真）测试 -> 实现跑绿。**【修订】同名不同义风险标注**：v1 按 `(name,type)` 精确匹配直接合并（不做 embedding 比对，同名不同义冲突解决留 v2）；合并时在 `metadata["provenance"]` 记 `merge_decision: "exact_name_type"`，为 v2 升级 embedding 三段式阈值（auto-merge≥0.95 / 人工复核 0.85-0.95 / 新节点<0.85 + type blocking）留接口位，无需改数据模型
- [ ] **Step 2:** 关系并集：按 `(source,target,type)` 去重，并 `source_chunk_ids`、打 provenance；chunk 按 `chunk_id` upsert 改写 scope；community 按 `community_id` 去重（member_entity_names 并集、打 provenance）测试 -> 实现跑绿
- [ ] **Step 3:** `MergeService.merge`：仅 approved 可合并；改写记录 `library_scope`/`owner_id`/`project_id`/`team_id` 到目标 scope（personal->project/team），`access_level` 保留源值（不降密）；调 `merge_graph` + store upsert；status->MERGED + `merged_at` + 审计 `merge` 测试 -> 实现跑绿
- [ ] **Step 4:** 合并幂等：已 MERGED 不可再合并（抛 ValueError）；合并后源库记录保留（个人库副本不删，溯源可用）；合并后人查询目标 scope 可见合并后数据测试 -> 实现跑绿

**验收：** 图谱合并实体去重/关系并集/来源打标正确；scope 改写正确（access_level 不降密）；合并幂等；溯源可见。

---

### Task 5: 协作推送 API + CLI

**目标：** FastAPI `/collab/*` 端点（create/list/get/diff/submit/approve/reject/merge）+ Typer `contributions` 子命令。端点守卫 `push`/`approve`，按 AccessContext 过滤。CLI 覆盖 list/show/submit/approve/merge。

**Files:**
- Create: `src/calliodesmo/api/collab.py`（`/collab` 路由）
- Modify: `src/calliodesmo/api/app.py`（`include_router` + `/api` 前缀双挂）
- Modify: `src/calliodesmo/api/schemas.py`（`ContributionCreate`/`ContributionOut`/`DiffOut` Pydantic schema）
- Modify: `src/calliodesmo/cli.py`（`contributions` 子命令组）
- Test: `tests/test_collab_api.py`、`tests/test_collab_cli.py`

- [ ] **Step 1:** `POST /collab`（create draft，`push` 守卫）/ `GET /collab`（list，按 access 过滤）/ `GET /collab/{id}`（越权 404）测试 -> 实现跑绿
- [ ] **Step 2:** `GET /collab/{id}/diff`（清单摘要）/ `POST /collab/{id}/submit`（`push`）/ `POST /collab/{id}/approve`（`approve`，非自审）/ `POST /collab/{id}/reject`（`approve`）测试 -> 实现跑绿
- [ ] **Step 3:** `POST /collab/{id}/merge`（`approve`，仅 approved 可合并；非自审）测试 -> 实现跑绿
- [ ] **Step 4:** 越权矩阵：analyst（有 push 无 approve）/ reviewer（有 push+approve）/ admin（全）三角色 × 各端点 × 期望状态码参数化测试 -> 实现跑绿
- [ ] **Step 5:** CLI `contributions list/show/submit/approve/merge`（系统用户上下文，复用 `_with_session` + `get_app_stores`）测试 -> 实现跑绿

**验收：** API+CLI 全流程（建推送->提交->审核->合并）；权限矩阵前后端一致；越权 403/404。

---

### Task 6: 抽取模板 review-gated 沉淀

**目标：** P1 已捕获模板外实体（`template_conforming=False`）。本 Task 把**发现的新类型**走 review-gated 沉淀进团队模板：收集发现类型 -> reviewer 审核批准 -> 写回团队模板 YAML（`preferred_entity_types` 追加）。团队模板随语料生长、经审核并入。

**Files:**
- Modify: `src/calliodesmo/ecl/extraction_template.py`（`ExtractionTemplateRegistry` 加 `sediment(team, approved_types)` 写回 YAML，保序去重）
- Create: `src/calliodesmo/collab/template_review.py`（收集发现类型 + 候选状态 pending/approved/rejected）
- Modify: `src/calliodesmo/api/collab.py`（`GET /collab/template-types` / `POST /collab/template-types/approve`，`approve` 守卫）
- Test: `tests/test_template_review.py`

- [ ] **Step 1:** 收集发现类型：扫 GraphStore 中 `template_conforming=False` 实体的 `type`，按团队聚合去重成候选清单 + 计数；空类型（None）过滤测试 -> 实现跑绿
- [ ] **Step 2:** `ExtractionTemplateRegistry.sediment(team, approved_types)`：写回 YAML（`preferred_entity_types` 追加已批准类型，去重保序）；写回失败（只读/路径无权）友好报错不崩溃测试 -> 实现跑绿。**【修订】路径复用**：写回路径直接用现有配置 `settings.extraction_template_file`（默认 `config/extraction_templates.yaml`，config.py 已有），无需新增配置项
- [ ] **Step 3:** review-gated 状态：候选类型有 `pending`/`approved`/`rejected`；`approve` 权限者批准 -> 调 `sediment` 写回 + 标 approved；重复批准幂等测试 -> 实现跑绿
- [ ] **Step 4:** API `GET /collab/template-types`（候选清单）/ `POST .../approve`（`approve` 守卫，写回）；CLI `templates review`（列出候选 + 批准）测试 -> 实现跑绿

**验收：** 发现类型可收集、审核、沉淀进团队模板 YAML；审核权限守卫；写回保序去重且幂等。

---

### Task 7: 文档社区选项 B - 独立嵌入聚类引擎

**目标：** 不依赖实体图的**独立文档嵌入聚类**：对文档（按 doc_id 聚合 chunk 取代表）嵌入 -> 阈值连通分量聚类（相似度阈值，**标准库实现**，与现有 `ConnectedComponentsDetector` 零依赖风格一致；**不引 scikit-learn**）-> 产出**文档社区**写入 CommunityStore（标 `metadata["source"]="doc_clustering"`，与实体派生社区并存）。v1 最简：连通分量聚类，不做层次/调参。

**Files:**
- Create: `src/calliodesmo/ecl/doc_community_clusterer.py`（`DocCommunityClusterer`）
- Modify: `src/calliodesmo/ecl/engine.py`（可选接入：ingest 后派生文档社区，开关 `doc_community_clustering`）
- Modify: `src/calliodesmo/config.py`（`doc_cluster_threshold: float = 0.7`、`doc_community_clustering: bool = True`）
- Test: `tests/test_doc_community_clusterer.py`

> [!warning] 路径与前提修正（【修订】，开工前必读）
> - **文件路径**：社区检测实际在 `ecl/cognify.py`（`CommunityDetector`/`ConnectedComponentsDetector`），文档社区派生在 `ecl/community_deriver.py`（选项 A `DocumentCommunityDeriver`）。计划旧写的 `ecl/community.py` **不存在**。
> - **community_id 前缀冲突（最严重）**：选项 A `DocumentCommunityDeriver` 已用 `doc-{doc_id}`（level=1，见 `community_deriver.py:70`）。Task 7 文档聚类社区**必须用不同前缀**（如 `docc-` / `docb-`），否则同 id upsert 覆盖选项 A 社区。
> - **networkx 前提**：实体社区检测默认用连通分量（零依赖），`NetworkxCommunityDetector` 走 `graph-analytics` extra 用 Louvain。**networkx 非默认依赖**，Task 7 阈值连通分量用标准库实现，不依赖 networkx。
> - **level 取值**：实体社区 level=0、选项 A 文档社区 level=1；Task 7 文档聚类社区建议 level=2（或同 level 不同前缀），与选项 A id 空间隔离。

- [ ] **Step 1:** 文档嵌入：按 doc_id 聚合 chunk 取代表（首 chunk 或均值向量），经 `EmbeddingProvider` 嵌入；空库/无 chunk 兜底返回空测试 -> 实现跑绿
- [ ] **Step 2:** 阈值连通分量聚类：相似度矩阵 + 阈值建图（相似度 >= 阈值连边）-> 连通分量即社区；单文档成单成员社区；阈值可配测试 -> 实现跑绿。**【修订】已知限制**：连通分量有 chaining effect（A-B、B-C 过阈值 -> A/B/C 同簇但 A-C 可能不相似）且无噪声点处理；簇内最低相似度写入 `metadata` 作质量信号；v2 可升级层次聚类（agglomerative，标准库可实现，抑制 chaining）或 HDBSCAN（走 extra）
- [ ] **Step 3:** 产出 `CommunityRecord`（`community_id` 用 `docc-` 前缀【修订，避免与选项 A `doc-` 撞 id】、title=首文档名/自动生成、summary=成员文档名摘要、member_entity_names=doc_ids、`metadata["source"]="doc_clustering"`、level=2）写入 CommunityStore；与实体派生社区及选项 A 文档社区并存不覆盖（断言三类 id 不相交）测试 -> 实现跑绿

**验收：** 独立聚类产出文档社区；不依赖实体图；与既有实体派生社区及选项 A 文档社区并存（id 前缀隔离，三类 id 不相交）。

---

### Task 8: 文档社区版本/分支/合并/回滚

**目标：** 社区**版本快照**（手动编辑/合并生成版本）+ **回滚上一版**（v1 不做完整 git DAG 三方合并）+ **merge/split**（P3 裁剪并入本 Task 整块）。`CommunityVersion` ORM 记录快照；`CommunityStore` 扩展 `merge`/`split`/`create_version`/`list_versions`/`rollback`。

**Files:**
- Create: `src/calliodesmo/collab/community_version.py`（`CommunityVersion` ORM + 版本服务）
- Modify: `src/calliodesmo/models.py`（导入 `CommunityVersion`）
- Modify: `src/calliodesmo/interfaces/community_store.py`（`merge`/`split`/`create_version`/`list_versions`/`rollback` 接口）
- Modify: `src/calliodesmo/providers/in_memory_community_store.py`（实现 + 版本快照栈）
- Modify: `src/calliodesmo/api/admin.py`（`/admin/community-versions/*` + merge/split/rollback 端点）
- Test: `tests/test_community_version.py`、`tests/test_community_merge_split.py`

- [ ] **Step 1:** `CommunityVersion` ORM（`community_id`/`version`/`snapshot JSON`/`created_by`/`created_at`）+ `models.py` 注册；建表可见测试 -> 实现跑绿
- [ ] **Step 2:** 手动编辑（rename/set_access/add-doc/remove-doc，P3 已有）自动生成版本快照；`list_versions` 按版本序；`rollback(version)` 恢复到指定版本【修订：append 式】--用 `version` 的快照内容**创建一个新版本**（version 序号自增），不删除任何历史快照（git revert 思路，回滚也是新提交）；支持回滚到任意版本且保留完整审计链（非"栈式只回滚上一版"）测试 -> 实现跑绿
- [ ] **Step 3:** `merge(target, sources)`：合并多社区成其一（member 并集、summary 取首或拼接、access 取较严、生成新版本）；`split(community, doc_groups)`：按 doc 组拆分成多社区测试 -> 实现跑绿
- [ ] **Step 4:** API `/admin/community-versions`（GET 版本列表）/ `/admin/document-communities/{id}/rollback` / merge/split 端点（`manage_community` 守卫）测试 -> 实现跑绿

**验收：** 社区版本快照 + append 式回滚任意版本 + merge/split；`manage_community` 守卫；手动编辑生成版本。**schema 复用【修订】**：merge/split/add-doc/remove-doc 端点复用 `schemas.py` 已预埋的 `CommunityAddDoc`/`RemoveDoc`/`Rename`/`Retag`/`SetAccess`（line 213-235 已定义未接端点）。

---

### Task 9: 前端协作推送 UI + 权限回归

**目标：** P3 SPA 上叠加**贡献面板**（建推送/审阅/合并/差异）与**社区版本视图**（版本列表 + 回滚 + merge/split）。权限驱动渲染（无 `push` 隐藏建推送、无 `approve` 隐藏审核/合并按钮）。三角色权限矩阵回归（含 `push`/`approve`）。

**Files:**
- Create: `frontend/src/features/collab/ContributionsPanel.tsx`（列表/建推送/差异/审核/合并）
- Create: `frontend/src/features/collab/ContributionDetail.tsx`（详情 + 状态机操作）
- Create: `frontend/src/features/admin/CommunityVersions.tsx`（版本列表 + 回滚 + merge/split）
- Modify: `frontend/src/routes.tsx`（`/app/collab` + `/app/admin/community-versions`）
- Modify: `frontend/src/App.tsx`（导航按权限显隐）
- Test: `frontend/src/features/collab/*.test.tsx`、`tests/test_permission_isolation.py`（扩 push/approve 矩阵）

- [x] **Step 1:** 贡献列表 + 建推送表单（选 source/target scope + project/team + doc_ids + 标题）-> `POST /collab`；`push` 守卫显隐建推送入口测试 -> 实现跑绿
- [x] **Step 2:** 贡献详情 + 差异清单展示（manifest 摘要：新增实体/关系/chunk/社区计数 + 冲突数）+ 状态机操作（submit/approve/reject/merge）；`approve` 守卫显隐审核/合并按钮；自审禁用 approve/merge测试 -> 实现跑绿
- [x] **Step 3:** 社区版本视图（版本列表 + 回滚上一版 + merge/split 触发）；`manage_community` 守卫显隐测试 -> 实现跑绿
- [x] **Step 4:** 权限驱动渲染：无 `push` 隐藏贡献入口、无 `approve` 隐藏审核/合并操作；前后端一致（后端守卫全覆盖，前端隐藏仅 UX）测试 -> 实现跑绿
- [x] **Step 5:** **权限矩阵回归**：analyst/reviewer/admin 三角色跑 建推送/提交/审核/合并 + 社区版本全流程，断言可见与可操作集合对齐 `DEFAULT_ROLE_PERMISSIONS`（含 `push`/`approve`）；**前端验证走 `preview_*` 交互闭环**（CLAUDE.md，非 Playwright）关键流程截图（桌面 + 移动视口），`npm run e2e` Playwright 套件补充测试 -> 实现跑绿

**验收：** 贡献面板 + 社区版本 UI；权限矩阵三角色一致（含 push/approve）；关键流程截图（桌面+移动）。

> [!note] 实现状态（2026-07-29，PR #5；A1/A2 闭合 2026-07-29）
> - ✅ Step 1（贡献列表 + 建推送表单 -> `POST /collab`，`ContributionsPanel`）
> - ✅ Step 2（`ContributionDetail` 详情 Dialog 消费 `GET /collab/{id}/diff`：5 计数卡片 + 实体/关系/chunk/社区明细 Tabs + 冲突警告；状态机操作仍内联列表行）
> - ✅ Step 3（`CommunityVersionsDialog` 社区版本视图：版本列表 + append 式回滚 + merge/split，从 `DocumentCommunityManage`「版本」按钮触发）
> - ✅ Step 4（权限驱动渲染：`useAccess.canPush/canApprove/hasManageCommunity` + 导航显隐）
> - ✅ Step 5（后端权限矩阵 `test_collab_api.py` + `preview_*` 闭环验证）
>
> A1/A2 闭合 P4 Task 9 前端残留；`DiffOut` 扩展明细字段（entity_names/relation_summaries/chunk_ids/community_ids，冲突明细留 v2）。演示场景 `collect` 在 admin 无 personal scope 时 diff 可能全 0（需源库有对应 doc_id 数据），真实生产用户 personal 库有 ingest 数据后正常。P9 持久化评估：建议进 P9（stores 持久化 + 合并原子性），独立阶段计划。

---

## 前端设计与 UX 前瞻

> [!note] 复用 P3 SPA 设计基调（操作工具风格、克制配色、lucide 图标、segmented control/toggle）。本阶段为增量叠加，不重建设计语言。

- **贡献面板**：列表用表格（标题/源->目标/状态/指派/时间），状态用色标 badge（draft 灰/submitted 蓝/approved 绿/rejected 红/merged 紫）；操作按钮按权限显隐，自审按钮置灰 + tooltip 说明。
- **差异清单**：紧凑卡片（新增实体 N / 关系 M / chunk K / 社区 C / 冲突 D），可展开 id 列表；审核人据此判断是否合并。
- **社区版本视图**：版本时间线（版本号/操作人/时间/快照摘要），回滚按钮带二次确认（破坏性操作）；merge/split 用模态表单。
- **验证**：贡献/审核/合并关键流程用 Playwright 截图（桌面 + 移动），核对状态 badge 正确、越权按钮隐藏/禁用、布局不溢出；权限矩阵三角色各跑一遍。

---

## 依赖与风险（P4 全量）

- **双轨存储**：MR 元数据走 ORM（SQLAlchemy，事务持久），图谱数据走内存 stores（单进程共享）。合并跨两轨：从 stores 读源记录 -> 改写 -> upsert 回 stores，同时 Contribution ORM 状态收尾。**单进程下 Sync 隐式**（`visible_to` 跨 scope 聚合，查询天然可见项目/团队库）；分布式 Sync/增量同步留 P9。测试用内存 SQLite + 内存 stores 隔离（沿用 `tests/conftest.py`）。**【修订】崩溃一致性**：合并跨两轨写非原子，中途崩溃可能状态不一致（stores 已合并但 Contribution 未 MERGED）；内存 stores 不持久，重启后数据丢失。v1 接受此限制（演示/单机），可选两阶段（ORM 先 MERGING -> 合并 stores -> MERGED）便于崩溃检测；持久化 stores 留 P9。
- **stores 枚举能力缺口**：现有 `VectorStore`/`GraphStore` 无"按 owner/scope 枚举"方法，推送收集（Task 2）需补 `list_chunks`/`list_entities`/`list_relations` 接口与内存实现（`list_communities` 已有）。接口扩展须同步 `in_memory_*` 实现 + 测试，避免"接口立了实现没跟上"的半切（P3 教训）。
- **权限**：`push`（analyst/reviewer/admin 有）创建/提交，`approve`（reviewer/admin）审核/合并；**自审阻断**（源用户不能 approve/merge 自己的推送）。审核指派到目标 scope 内持 `approve` 成员（project->项目成员、team->团队成员）。后端为唯一真相，前端隐藏仅 UX。
- **【修订】并发控制**：状态机流转（submit/approve/reject/merge）走 DB 事务 + 行锁/乐观锁（`Contribution.version` 字段），防多 reviewer 并发重复审核、merge double-click 绕过终态检查、多 DRAFT 并发 submit 自动指派竞态。多 reviewer 并发审核是 v1 现实场景，非 v2。
- **图谱合并冲突**：v1 按 `(name,type)` 去重 + 来源打标，**不做同名不同义冲突解决/完整版本/回滚**（v2 精化，见路线图"后续精化"）。`access_level` 合并取较严（max），防降密。源记录合并后保留不删（溯源副本）。
- **来源打标(provenance)**：合并记录 `metadata["provenance"]` 记 `contribution_id`+`source_user_id`+`merged_at`，供溯源（谁贡献了什么）。与 P1 的 `source_chunk_ids` 互补（后者是文本块溯源，前者是贡献溯源）。
- **抽取模板写回**：review-gated 沉淀写回 YAML（Task 6），生产环境模板文件需可写；只读/无权时友好报错不崩溃。写回保序去重、幂等。
- **聚类重依赖【修订】**：Task 7 用**标准库阈值连通分量**（与 `ConnectedComponentsDetector` 零依赖风格一致），**不引 scikit-learn**（重依赖，离线/Windows wheel 风险，沿用 litellm 钉版教训）；networkx 非默认依赖（实体社区检测 `NetworkxCommunityDetector` 走 `graph-analytics` extra 用 Louvain，与 Task 7 文档聚类无关）。嵌入复用 `EmbeddingProvider`（BGE-M3 可选 extra，无则 Hash 降级，测试用 Hash）。阈值可配（`doc_cluster_threshold`）。
- **社区版本存储**：`CommunityVersion` 快照走 ORM（JSON snapshot）；内存 store 维护版本栈。回滚 v1 支持上一版，完整 git DAG 三方合并留 v2。
- **前端**：复用 P3 SPA 基座（React 19 + TanStack Query + 受保护路由）；贡献面板 + 社区版本视图增量叠加，三件套（lint/test/build）+ 视觉验证闭环。前端不进检索精度回归，但权限一致性（push/approve 矩阵）有回归测试。
- **范围外（v2/P9）**：完整图谱合并冲突解决/版本/按调查任务开分支（v2）；分布式 Sync/增量同步（P9）；审计查询 UI（P9 硬化）；refresh token 会话续期；OIDC/SSO（v2）。