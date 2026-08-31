---
title: P4 Git-like 协作推送实施计划
type: phase-plan
phase: P4
tags:
  - plan/phase
created: 2026-07-29
---
# P4 Git-like 协作推送实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/phases/P3-web-ui|P3]] / [[docs/plans/phases/P5-advanced-rag|P5]]。

> [!important] 前置条件（开工前确认）
> - **基线**：P4 分支从 P3 合并后的 main 切出（`codex/p4-git-collab`）。
> - **双轨存储认知（关键）**：MR 元数据（状态/审核/指派/版本）走 ORM（SQLAlchemy，事务持久）；**被推送的图谱数据（chunk/entity/relation/community）走内存 stores**（`AppStores` 单例，单进程共享）。合并 = 从源库读记录 -> 改写 access 字段到目标 scope -> upsert 回同一 stores。**单进程下 Sync 隐式**；分布式 Sync/增量同步留 P9。
> - **并发控制认知（关键）**：状态机流转走 **DB 事务 + 行锁/乐观锁**（`Contribution.version` 字段），防多 reviewer 并发重复审核 / merge double-click 绕过终态。
> - **崩溃一致性认知**：合并跨两轨写非原子，中途崩溃可能状态不一致；内存 stores 不持久。v1 接受（演示/单机）；持久化 stores 留 P9（P4.5 已落地）。
> - **MVP 裁剪线**：Task 7 文档聚类用「阈值连通分量」最简实现（不引 scikit-learn）；Task 8 回滚 v1 做版本快照 + append 式回滚；Task 9 前端以贡献面板为主。
> - **MVP 必做清单**：Task 1-5 + Task 9 Step 5；Task 6/7/8/9 前端完整版可后续补齐。

**Goal:** 实现 Git-like 协作推送：个人库 -> 项目库 -> 团队库的**贡献/审核/合并状态机**与**图谱合并**（实体按 `(name,type)` 去重、关系并集、来源打标），审核指派到组；**抽取模板 review-gated 沉淀**；**文档社区选项 B**（独立聚类 + 社区版本/分支/合并/回滚）。API+CLI 优先，前端在 P3 SPA 上叠加。

**Architecture:** 协作域独立为 `collab/` 包。**贡献请求(MR)** 为 ORM 模型（`Contribution` + 状态机 `draft->submitted->approved/rejected->merged/closed`），经 `ContributionService` 驱动流转，全程记审计。**推送**收集源 scope 记录成清单(manifest)；**合并**做图谱合并后 upsert 目标 scope（`access_level` 取较严 max）。权限：`push` 创建/提交、`approve` 审核批准/合并；**自审阻断**；审核可指派到目标 scope 内持 `approve` 成员。复用 P3 `require_permission` + `visible_to` + 审计。**并发**：`Contribution.version` 乐观锁。

**Tech Stack（P0-P3 基础上追加）:**
- 后端：FastAPI `/collab/*` + `/admin/community-versions/*` · Typer CLI `contributions` · SQLAlchemy ORM（`Contribution`/`CommunityVersion`）· 内存 stores 枚举 + 图谱合并纯函数
- 聚类：BGE-M3 文档嵌入（复用 `EmbeddingProvider`）+ 阈值连通分量聚类，不引 scikit-learn
- 前端：React 19 + TanStack Query · 贡献面板 + 社区版本视图
- 测试：`pytest` + `httpx`（端点 × 角色 × 状态码）；前端 `vitest` + `preview_*` 闭环

---

### Task 1: 贡献请求(MR)数据模型与状态机

**目标：** 立 `collab/` 包，定义 `Contribution` ORM 与状态机 `draft -> submitted -> approved/rejected -> merged`（+`closed`）。

**Files:** `src/calliodesmo/collab/*` · `src/calliodesmo/models.py`（注册）· 测试 `tests/test_contribution_models.py` / `test_contribution_service.py`。

- [ ] **Step 1:** `collab/models.py`：`ContributionStatus` + `Contribution` ORM（`target_scope` 须 `rank > source_scope`）；`LibraryScope` 加 `@property rank`。-> 实现跑绿
- [ ] **Step 2:** `ContributionService.create(...)`：校验 target 高于 source、目标 id 匹配；建 DRAFT；记审计 `push`。-> 实现跑绿
- [ ] **Step 3:** 状态机流转（submit/approve/reject/close），非法跳转抛 `ValueError`；**取舍**：`rejected -> submitted` reopen（复用 MR），不引入 `changes_requested` 中间态。-> 实现跑绿
- [ ] **Step 4:** `list/get_contribution(*, access)` 按 AccessContext 过滤；越权返 None/空。-> 实现跑绿
- [ ] **Step 5（并发）:** `Contribution.version` 乐观锁 + 事务内锁行校验；防并发重复 approve / merge double-click。-> 实现跑绿

**验收：** MR 模型 + 状态机 + 并发控制；审计埋点。

---

### Task 2: 源库枚举与推送差异(Diff)

**目标：** stores 补「按 owner/scope 枚举」能力，供推送收集源库记录成 manifest。

**Files:** stores 接口 + 内存实现（`list_chunks`/`list_entities`/`list_relations`）· `collab/push.py`（collect/build_manifest/diff）· 测试 `tests/test_push_manifest.py`。

- [ ] **Step 1:** stores 枚举接口 + 内存实现，全部按 `visible_to` 过滤。-> 实现跑绿（**接口与实现同 PR 落地**，P3 教训）
- [ ] **Step 2:** `PushService.collect(contribution, *, stores)` 按 `doc_ids` 聚合 chunk/entity/relation/community；越权不收集。-> 实现跑绿
- [ ] **Step 3:** `build_manifest`：聚合清单 + 目标库重叠判定，写回 `Contribution.manifest`；记审计 `push`。-> 实现跑绿
- [ ] **Step 4:** `diff(contribution)`：返回清单摘要（新增 N / 关系 M / chunk K / 社区 C / 冲突 D）供审核展示。-> 实现跑绿

**验收：** 推送清单可枚举、可 diff。

---

### Task 3: 审核(Review)与指派到组

**目标：** 状态机审核流转 + 自动指派到目标 scope 内持 `approve` 成员。

**Files:** Modify `collab/service.py` · 测试 `tests/test_contribution_review.py`。

- [ ] **Step 1:** `submit`：DRAFT->SUBMITTED；`assignee_id` 显式或用则自动指派；无可用 reviewer 标「待指派」。-> 实现跑绿
- [ ] **Step 2:** `approve`：需 `APPROVE` 权限 + 非自审；记录 `reviewed_by/at` + 审计 `approve`；无权 403、自审 ValueError。-> 实现跑绿
- [ ] **Step 3:** `reject`：submitted->rejected；审计 `reject` + 原因。-> 实现跑绿
- [ ] **Step 4（指派到组）:** team 候选 = `TeamMember.team_id == target_team` 且全局含 `APPROVE` 权限（**不按 `role_in_team` 字符串匹配**）；project 候选走 `ProjectMember.role_id`；自动指派确定性取首个。-> 实现跑绿

**验收：** 审核守卫 + 自审阻断 + 指派到组。

---

### Task 4: 图谱合并(Merge)与来源打标

**目标：** 合并源库图谱进目标 scope：实体按 `(name,type)` 去重、关系并集、来源打标（provenance）。

**Files:** `collab/graph_merge.py`（纯函数）+ `collab/merge.py`（MergeService）· 测试 `tests/test_graph_merge.py` / `test_merge_service.py`。

- [ ] **Step 1:** 实体合并：按 `(name,type)` 去重（并 `source_chunk_ids`、描述拼接、`access_level` 取较严、打 provenance）。**同名不同义风险**：v1 精确匹配直接合并，`metadata["provenance"].merge_decision="exact_name_type"`，为 v2 三段式阈值留接口位。-> 实现跑绿
- [ ] **Step 2:** 关系按 `(source,target,type)` 并集去重；chunk 按 id upsert；community 按 id 去重。-> 实现跑绿
- [ ] **Step 3:** `MergeService.merge`：仅 approved 可合并；改写 scope/owner 到目标，`access_level` 保留源值；status->MERGED + 审计 `merge`。-> 实现跑绿
- [ ] **Step 4:** 合并幂等（已 MERGED 报错）；源库记录保留不删（溯源）。-> 实现跑绿

**验收：** 合并去重 + 打标 + 幂等；生产可用（P4.5 验证落库）。

---

### Task 5: 协作推送 API + CLI

**目标：** `/collab` 全套端点 + CLI `contributions` 子命令 + 三角色权限矩阵。

**Files:** `api/collab.py` · `cli.py` · 测试 `tests/test_collab_api.py` / `test_collab_cli.py` / `test_permission_isolation.py`。

- [ ] **Step 1:** `POST /collab`（create，`push`）/ `GET /collab`（list，按 access）/ `GET /collab/{id}`（越权 404）。-> 实现跑绿
- [ ] **Step 2:** `GET /collab/{id}/diff` / `POST .../submit`（`push`）/ `approve`、`reject`（`approve`，非自审）。-> 实现跑绿
- [ ] **Step 3:** `POST /collab/{id}/merge`（`approve`，仅 approved）。-> 实现跑绿
- [ ] **Step 4（越权矩阵）:** analyst（push 无 approve）/ reviewer（push+approve）/ admin × 各端点参数化。-> 实现跑绿
- [ ] **Step 5:** CLI `contributions list/show/submit/approve/merge`（系统用户上下文）。-> 实现跑绿

**验收：** API+CLI 全链路 + 权限矩阵。

---

### Task 6: 抽取模板 review-gated 沉淀

**目标：** 团队抽取模板随语料生长，新类型经审核沉淀。

**Files:** `collab/template_review.py` · `config/extraction_templates.yaml` · 测试 `tests/test_template_review.py`。

- [ ] **Step 1:** 收集发现类型：扫 `template_conforming=False` 实体的 type，按团队聚合去重。-> 实现跑绿
- [ ] **Step 2:** `ExtractionTemplateRegistry.sediment(team, approved_types)` 写回 YAML（append 保序去重）；只读报错友好。**路径复用** `settings.extraction_template_file`。-> 实现跑绿
- [ ] **Step 3:** review-gated 状态（pending/approved/rejected）；`approve` 权限者批准；重复批准幂等。-> 实现跑绿
- [ ] **Step 4:** API `GET /collab/template-types` + `POST .../approve`；CLI `templates review`。-> 实现跑绿

**验收：** 新类型可审核沉淀进团队模板。

---

### Task 7: 文档社区选项 B - 独立嵌入聚类引擎

**目标：** 不依赖实体图，对文档做嵌入聚类产出文档社区（`docc-` 前缀，level=2）。

**Files:** `ecl/doc_community_clusterer.py` · 测试 `tests/test_doc_community_clusterer.py`。

- [ ] **Step 1:** 文档嵌入（按 doc_id 聚合 chunk 取代表）。-> 实现跑绿
- [ ] **Step 2:** 阈值连通分量聚类（相似度 >= 阈值连边）；单文档单成员；阈值可配。**已知限制**：chaining effect、无噪声点处理；簇内最低相似度写 `metadata` 作质量信号；v2 可升级层次聚类/HDBSCAN（extra）。-> 实现跑绿
- [ ] **Step 3:** 产出 `CommunityRecord`（`docc-` 前缀避免撞 `doc-` id、`metadata["source"]="doc_clustering"`）写入 CommunityStore；与实体/选项 A 社区并存不覆盖。-> 实现跑绿

**验收：** 文档聚类社区落库、与既有社区并存。

---

### Task 8: 文档社区版本/分支/合并/回滚

**目标：** 社区手动编辑生成版本快照，支持 append 式回滚与 merge/split。

**Files:** `collab/community_version.py` · `api/admin.py` · 测试 `tests/test_community_version.py` / `test_document_community_manage_api.py`。

- [ ] **Step 1:** `CommunityVersion` ORM（`community_id`/`version`/`snapshot JSON`/`created_by/at`）。-> 实现跑绿
- [ ] **Step 2:** 手动编辑自动生成版本；`list_versions`；`rollback(version)` **append 式**（用旧版本快照新建版本，不删历史，git revert 思路，可回滚任意版本）。-> 实现跑绿
- [ ] **Step 3:** `merge(target, sources)` / `split(community, doc_groups)`。-> 实现跑绿
- [ ] **Step 4:** API `/admin/community-versions` + rollback / merge/split 端点（`manage_community`）。-> 实现跑绿

**验收：** 版本快照 + append 回滚 + merge/split。

---

### Task 9: 前端协作推送 UI + 权限回归

**目标：** P3 SPA 上叠加**贡献面板**（建推送/审阅/合并/差异）与**社区版本视图**；权限驱动渲染。

**Files:** `frontend/src/features/collab/*` + `features/admin/CommunityVersions.tsx` + `routes.tsx` + `App.tsx`。

- [x] **Step 1:** 贡献列表 + 建推送表单（选 source/target scope + doc_ids + 标题）-> `POST /collab`；`push` 守卫显隐。
- [x] **Step 2:** 贡献详情 + 差异清单展示 + 状态机操作；`approve` 守卫显隐审核/合并；自审禁用。
- [x] **Step 3:** 社区版本视图（版本列表 + 回滚 + merge/split）；`manage_community` 守卫。
- [x] **Step 4:** 权限驱动渲染（无 `push` 隐藏入口、无 `approve` 隐藏操作）；前后端一致。
- [x] **Step 5:** **权限矩阵回归**：三角色全流程对齐 `DEFAULT_ROLE_PERMISSIONS`（含 `push`/`approve`）；前端走 `preview_*` 交互闭环 + 关键流程截图。

> [!note] 实现状态（2026-07-29，PR #5；A1/A2 闭合 2026-07-29）
> Step 1-5 全部完成（`ContributionsPanel` + `ContributionDetail` + `CommunityVersionsDialog` + 权限驱动渲染 + 后端矩阵测试）。`DiffOut` 扩展明细字段。演示场景 `collect` 在 admin 无 personal scope 时 diff 可能全 0（需源库有对应 doc_id 数据）。P9 持久化评估：独立阶段计划（已在 P4.5 落地）。

---

## 依赖与风险（P4 全量）

- **双轨存储**：MR 元数据走 ORM，图谱数据走内存 stores；合并非原子、崩溃不一致（v1 接受，P4.5 解决持久化）。
- **stores 枚举缺口**：推送收集需补 `list_chunks`/`list_entities`/`list_relations`（接口与内存实现同步落地）。
- **权限**：`push`（analyst/reviewer/admin）创建/提交，`approve`（reviewer/admin）审核/合并；自审阻断；后端为唯一真相。
- **并发控制**：状态机流转走 DB 事务 + 行锁/乐观锁（`Contribution.version`）。
- **图谱合并冲突**：v1 按 `(name,type)` 去重 + 打标；`access_level` 取较严；不解决同名不同义（v2）。
- **来源打标(provenance)**：`metadata["provenance"]` 记 `contribution_id`+`source_user_id`+`merged_at`。
- **聚类重依赖【修订】**：Task 7 用标准库阈值连通分量，不引 scikit-learn；networkx Louvain 走 `graph-analytics` extra。
- **社区版本存储**：`CommunityVersion` 快照走 ORM；v1 支持任意版本 append 回滚。
- **范围外（v2/P9）**：完整冲突解决/版本/分支（v2）；分布式 Sync（P9）；OIDC/SSO（v2）。
