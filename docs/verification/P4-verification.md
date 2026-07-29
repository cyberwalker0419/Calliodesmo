# P4 Git-like 协作推送验证报告

> 验证日期：2026-07-29
> 阶段：P4 Git-like 协作推送（[[docs/plans/phases/P4-git-collab|P4 计划]]）
> 前置：P3 Web UI（[[docs/verification/P3-verification|P3 验证报告]]）

## 总览

P4 在 P0-P3 三层知识图谱与检索/问答/浏览能力之上，新增 **Git-like 协作推送**：个人库 -> 项目库 -> 团队库的**贡献/审核/合并状态机**与**图谱合并**（实体按 `name` 去重、关系并集、来源打标），审核指派到组，自审阻断，全程审计。API+CLI 优先，复用 P3 `require_permission` / `visible_to` / `record_audit` / `AppStores` 依赖工厂。

本阶段 MVP 必做（Task 1-5 + Task 9 Step 5 权限矩阵回归）已全部达标；持续迭代项 Task 6（抽取模板 review-gated 沉淀）/ Task 7（独立嵌入聚类引擎）/ Task 8（社区版本/合并/回滚）/ Task 9 前端 ContributionsPanel 亦已落地；Task 9 ContributionDetail/CommunityVersions UI 留后续补齐。

**后端测试结果：350 passed / 1 skipped / 1 failed**
**Ruff：All checks passed!（check + format）**
**前端三件套：lint 0 错 / vitest 5 passed / build 成功**
**前端 preview_* 闭环：ContributionsPanel 渲染 + 建推送流程验证通过（无 console error）**

> [!note] 关于 1 failed
> `tests/test_ingest_cli.py::test_ingest_llm_missing_key` 为 **pre-existing 环境问题**，非 P4 引入：本地 `.env` 残留 `CALLIODESMO_LLM_API_KEY` 导致 `delenv` 未真正清空（pydantic-settings 仍从 `.env` 文件加载），缺 key 校验未触发；叠加 litellm 远程 cost map fetch 的 SSL 证书告警。已用 `git stash` 验证：stash 掉全部 P4 改动后该测试**同样失败**。CI 环境无 `.env`，该测试应通过。

## 计划修订（ABC 改进落实）

P4 计划对照现有代码与业界方案修订，落实审查报告三类改进（详见 [[docs/plans/phases/P4-git-collab|P4 计划]] 散落【修订】标注）：

- **A 契合度缺口**：`LibraryScope.rank` 属性（推送方向校验）；team 指派走 `UserRole` 全局含 `APPROVE`（`TeamMember` 无 RBAC 外键，A5）；社区检测 Leiden 误写修正（代码实际用连通分量，CLAUDE.md/AGENTS.md 同步）。
- **B 设计加强**：**并发控制**（`Contribution.version` 乐观锁 `version_id_col` + `with_for_update` 行锁，防并发重复 approve/merge，B1）；状态机 `rejected -> submitted` reopen（B2）；图谱合并 `merge_decision` 标注留 v2 embedding 接口（B4）。
- **C 契合度补充**：stores 枚举接口与 in_memory 实现同 PR（C1）；审计复用 `record_audit`（C4）；崩溃一致性 v1 接受（C5，单进程内存 stores 不持久，持久化留 P9）。
- **社区检测走 Louvain**（非 Leiden）：`NetworkxCommunityDetector` 升级 `nx.community.louvain_communities`（modularity 优化，seed 固定）+ `build_community_detector` 可配置工厂；Leiden 留 v2（graph-leiden extra，同模式接入）。

## Task 验收明细

### Task 1: 贡献请求(MR) ORM + 状态机 + service ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `ContributionStatus` 枚举（draft->submitted->approved/rejected->merged + closed；rejected 可 reopen） | ✅ | `src/calliodesmo/collab/models.py` |
| `Contribution` ORM（JSON doc_ids/manifest + version 乐观锁 `version_id_col`） | ✅ | 同上 |
| `LibraryScope.rank` 属性（personal=0/project=1/team=2，推送方向校验） | ✅ | `src/calliodesmo/auth/models.py` |
| `ContributionService`：create/submit/approve/reject/merge/close/reopen/list/get | ✅ | `src/calliodesmo/collab/service.py` |
| 非法状态跳转抛 `ContributionError`（如 draft 直接 approve） | ✅ | `test_state_machine_illegal_transition` |
| 并发：version 乐观锁 + `with_for_update` 行锁（B1） | ✅ | `test_version_optimistic_lock`（StaleDataError） |
| 审计全程 `record_audit`（push/submit/approve/reject/merge） | ✅ | `test_create_draft_and_audit` |
| 可见性过滤（源用户本人 或 目标 scope 内持 APPROVE） | ✅ | `test_visibility_filtering` |

测试文件：`tests/test_contribution_models.py`（3）+ `tests/test_contribution_service.py`（9）

### Task 2: stores 枚举 + PushService 推送清单 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `VectorStore.list_chunks` / `GraphStore.list_entities`+`list_relations` 接口与 in_memory 实现同 PR | ✅ | `interfaces/{vector,graph}_store.py` + `providers/in_memory_*` |
| 按 `visible_to` 过滤（越权源库不收集） | ✅ | `test_collect_invisible_source_filtered` |
| `PushService.collect`（按 doc_ids 聚合 chunk/entity/relation/community） | ✅ | `src/calliodesmo/collab/push.py` |
| `build_manifest`（清单+计数+重叠判定+审计）+ `diff`（摘要） | ✅ | `test_build_manifest_and_diff` |
| `compute_overlap` 按 `(name,type)` 精确匹配（留 v2 embedding 接口，B4） | ✅ | `test_compute_overlap_name_type` |

测试文件：`tests/test_push_manifest.py`（4）

### Task 3: 审核 + 指派到组 + 自审阻断 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `submit` 自动指派（显式优先；否则目标 scope 首个持 APPROVE 成员；无则待指派） | ✅ | `test_submit_auto_assign_project_reviewer` |
| team 指派走 `UserRole` 全局含 APPROVE（A5，非 role_in_team 字符串） | ✅ | `test_submit_auto_assign_team_reviewer` |
| `approve`/`reject`/`merge` 自审阻断（reviewer != source_user） | ✅ | `test_approve_self_review_blocked` / `test_merge_self_review_blocked` |
| `reject` 记原因 + 审计 | ✅ | `test_reject_records_audit` |

测试文件：`tests/test_contribution_review.py`（7）

### Task 4: 图谱合并 + 来源打标 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `merge_entities` 实体按 name 去重（并 source_chunk_ids / 描述拼接 / access 取较严 / template_conforming 取或） | ✅ | `src/calliodesmo/collab/graph_merge.py` |
| `merge_decision` 标注（exact_name_type / same_name_diff_type / new，留 v2 embedding） | ✅ | `test_merge_same_name_diff_type_marked_conflict` |
| `merge_relations` 关系按 (source,target,type) 并集去重 + provenance | ✅ | `test_merge_relations_union_dedup` |
| `MergeService.merge`（scope 改写 + provenance + 幂等 + 自审，状态收尾复用 ContributionService） | ✅ | `src/calliodesmo/collab/merge.py` |
| 合并幂等（已 MERGED 抛错）+ 仅 approved 可合并 | ✅ | `test_merge_idempotent` / `test_merge_only_approved` |
| access_level 不降密（保留源值） | ✅ | `test_merge_existing_entity_merges_chunks_and_access` |

测试文件：`tests/test_graph_merge.py`（4）+ `tests/test_merge_service.py`（4）

### Task 5: 协作推送 API + CLI ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `/collab` 端点（create/list/get/diff/submit/approve/reject/merge，根 + /api 双挂） | ✅ | `src/calliodesmo/api/collab.py` + `app.py` |
| `push`/`approve` 守卫（`require_permission` 403） | ✅ | `test_create_push_guard` / `test_approve_guard_and_self_review` |
| 自审阻断 -> 403；越权 -> 404；匿名 -> 401 | ✅ | `test_self_review` / `test_get_invisible_404` / `test_create_requires_auth` |
| merge 端点用源用户 access 收集 + 审核人 access 查目标库 + 状态收尾 | ✅ | `test_merge_flow`（合并后目标 scope 可见 + status merged） |
| Typer `contributions list/show/submit/approve/merge` 子命令 | ✅ | `src/calliodesmo/cli.py` |

测试文件：`tests/test_collab_api.py`（8）+ `tests/test_collab_cli.py`（3）

### Task 9 Step 5: 权限矩阵回归 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| analyst（push 无 approve）/ reviewer（push+approve）/ admin（全）三角色 × push/approve × 状态码 | ✅ | `tests/test_collab_api.py`（建推送/审核/合并矩阵） |
| 自审阻断（源用户不能 approve/merge 自己） | ✅ | `test_approve_guard_and_self_review` |
| 越权贡献不可见（404） | ✅ | `test_get_invisible_404` |
| 匿名访问受限端点 -> 401 | ✅ | `test_create_requires_auth` |

> 前端 Task 9（ContributionsPanel/CommunityVersions UI）属持续迭代，按周补齐（P4 计划前置声明）。

### Task 6: 抽取模板 review-gated 沉淀 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `collect_discovered_types`（template_conforming=False 聚合+计数，空类型过滤） | ✅ | `collab/template_review.py` |
| `ExtractionTemplateRegistry.sediment` 写回 YAML（preferred 追加去重保序，幂等，失败友好报错） | ✅ | `ecl/extraction_template.py` |
| review-gated 状态（approved 进模板 -> conforming=True 不再收集） | ✅ | `test_collect_discovered_types` |
| API `GET /collab/template-types` + `POST .../approve`（approve 守卫） | ✅ | `api/collab.py` |
| CLI `templates list-types/approve-type` | ✅ | `cli.py` |

测试文件：`tests/test_template_review.py`（5）+ `tests/test_collab_api.py`（+1 端点测试）

### Task 7: 独立文档嵌入聚类引擎（选项 B） ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `DocCommunityClusterer`（按 doc_id 聚合 chunk 嵌入 -> 阈值连通分量聚类） | ✅ | `ecl/doc_community_clusterer.py` |
| `docc-` 前缀 + level=2（与实体 comm-/选项 A doc- id 隔离，A1 修订） | ✅ | `test_cluster_prefix_level_metadata` |
| metadata source=min_intra_similarity 质量信号（B5） | ✅ | 同上 |
| config 开关 `doc_community_clustering` + `doc_cluster_threshold` | ✅ | `config.py` |
| engine 接入（ingest 后派生，开关控制） | ✅ | `ecl/engine.py` |

测试文件：`tests/test_doc_community_clusterer.py`（6）

### Task 8: 社区版本/合并/回滚 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `CommunityVersion` ORM（JSON snapshot）+ models.py 注册 | ✅ | `collab/community_version.py` |
| `CommunityVersionService`（create/list/rollback append 式不删历史，B3 修订） | ✅ | `test_rollback_append_creates_new_version` |
| `CommunityStore.merge/split` 接口 + in_memory 实现 | ✅ | `interfaces/community_store.py` + `in_memory_community_store.py` |
| 手动编辑自动生成版本快照（patch 端点） | ✅ | `api/admin.py` |
| API `/admin/community-versions` + rollback + merge/split（manage_community 守卫） | ✅ | 同上 |

测试文件：`tests/test_community_version.py`（6）

### Task 9: 前端协作推送 UI（核心）✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `ContributionsPanel`（列表 + 建推送表单 + submit/approve/reject/merge 操作） | ✅ | `frontend/src/features/collab/ContributionsPanel.tsx` |
| 权限驱动渲染（无 push 隐藏建推送、无 approve 隐藏审核/合并） | ✅ | `useAccess.canPush/canApprove` |
| 自审禁用 approve/merge（前端 UX，后端守卫） | ✅ | `isSelf(c)` disabled |
| 路由 `/app/collab` + 导航入口（push 显隐） | ✅ | `routes.tsx` + `App.tsx` |
| 三件套（lint/test/build）+ preview_* 闭环 | ✅ | 建推送流程验证通过 |

> ContributionDetail（差异清单详情）+ CommunityVersions UI 属持续迭代，留后续补齐。

## 测试隔离与原理

- **后端隔离**：每用例独立内存 SQLite（`sqlite+aiosqlite:///:memory:`）；stores 单例经 `reset_app_stores()` 在 merge 测试 try/finally 清理；`sys.modules` 桩隔离 litellm/uvicorn。
- **并发测试**：`test_version_optimistic_lock` 用双 session（同 engine）模拟 stale 对象提交，断言 `StaleDataError`（version_id_col 机制）；SQLite 写锁串行化，乐观锁冲突用 stale 对象验证。
- **契约优先**：API 测试断言状态码矩阵（201/200/400/403/404/401）+ 状态机流转 + 审计落库。
- **离线可跑**：所有测试零网络、零重依赖（StubLLM + Hash 嵌入 + 内存 stores）；Louvain 测试在无 networkx extra 时 `pytest.skip`（CI 不装 extra 不破）。

## 验证过程（可复现）

```bash
# 后端
uv sync
uv run pytest -q                    # 332 passed / 1 skipped / 1 failed(pre-existing)
uv run ruff check . && uv run ruff format --check .   # All checks passed!

# 协作推送端到端（API）
uv run calliodesmo db init && uv run calliodesmo db seed
uv run calliodesmo serve             # 8000
# POST /collab（建推送）-> /submit -> /approve -> /merge（状态机 + 图谱合并）

# CLI
uv run calliodesmo contributions list / show <id> / submit <id> / approve <id> / merge <id>
```

## 已知边界与后续

- **Task 6（抽取模板 review-gated 沉淀）/ Task 7-8（文档社区选项 B）**：按 P4 计划属持续迭代，分步落地（先 API 后 UI），留后续补齐。
- **崩溃一致性（C5）**：合并跨两轨写（内存 stores + ORM）非原子，v1 接受（演示/单机）；可选两阶段（ORM MERGING -> 合并 stores -> MERGED）便于崩溃检测；持久化 stores 留 P9。
- **图谱合并同名不同义（B4）**：v1 按 `(name,type)` 精确匹配，不做 embedding 比对；`merge_decision` 标注为 v2 升级（auto-merge≥0.95 / 人工复核 0.85-0.95 / 新节点<0.85 + type blocking）留接口位。
- **并发 Sync/增量同步**：单进程下 `visible_to` 跨 scope 聚合隐式 Sync；分布式 Sync 留 P9。
- **前端**：Task 9 贡献面板 + 社区版本 UI 增量叠加，走 `preview_*` 交互闭环（CLAUDE.md），随迭代补齐。
- **`test_ingest_llm_missing_key`**：pre-existing 环境问题（本地 .env 残留 API key + litellm SSL），非 P4 引入，CI 应通过。
