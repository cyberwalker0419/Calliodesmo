# P4 Git-like 协作推送验证报告

> 验证日期：2026-07-29（P4.5 持久化贯通段：2026-07-31 / 复核 2026-08-13）
> 阶段：P4 Git-like 协作推送（[[docs/plans/phases/P4-git-collab|P4 计划]]）· 前置：[[docs/verification/P3-verification|P3 验证报告]]

## 总览

P4 在 P0-P3 之上新增 **Git-like 协作推送**：个人库 -> 项目库 -> 团队库的**贡献/审核/合并状态机**与**图谱合并**（实体按 name 去重、关系并集、来源打标），审核指派到组、自审阻断、全程审计。API+CLI 优先，复用 P3 `require_permission` / `visible_to` / `record_audit`。MVP（Task 1-5 + Task 9 权限矩阵回归）与持续迭代项（Task 6-9）全部落地。

- **后端**：350 passed / 1 skipped / 1 failed(pre-existing) -> **P4.5 复核 407 passed / 1 skipped / 0 failed**
- **Ruff**：All checks passed（check + format）· **前端**：lint 0 错 / vitest 5 passed / build 成功 + preview 闭环

> [!note] 关于 1 failed（已修复）
> `test_ingest_llm_missing_key` 为 pre-existing 环境问题（本地 `.env` 残留 API key），非 P4 引入；叠加 litellm 远端 cost fetch SSL 告警。CI 无 `.env` 应通过。

## 计划修订（ABC 改进落实）

- **A 契合度**：`LibraryScope.rank` 属性；team 指派走 `UserRole` 全局 APPROVE（非 `role_in_team` 字符串）；社区检测实际为 Louvain（非 Leiden）。
- **B 设计加强**：并发控制（`Contribution.version` 乐观锁 + 行锁）；`rejected -> submitted` reopen；`merge_decision` 留 v2 embedding 接口。
- **C 补充**：stores 枚举接口与实现同 PR；审计复用 `record_audit`；崩溃一致性 v1 接受（持久化留 P9）。

## Task 验收明细

### Task 1-5 + 9（核心，全部 ✅）

| Task | 验收要点 | 证据 |
|------|---------|------|
| 1 MR 模型+状态机 | `ContributionStatus`/`Contribution`(JSON+version 乐观锁)/`Service` 全流转/非法跳转报错/并发/审计/可见性 | `test_contribution_models.py`(3) + `service.py`(9) |
| 2 stores 枚举+推送清单 | `list_chunks/entities/relations` 接口与内存实现同 PR；`collect`/`build_manifest`/`diff`；`visible_to` 过滤 | `test_push_manifest.py`(4) |
| 3 审核+指派+自审 | 自动指派（project/team 两路）/ 自审阻断 / reject 记因 | `test_contribution_review.py`(7) |
| 4 图谱合并+打标 | 实体去重并集 / 关系并集 / merge 服务（scope 改写+provenance+幂等+不降密） | `test_graph_merge.py`(4) + `merge_service.py`(4) |
| 5 API+CLI | `/collab` 端点 + `push`/`approve` 守卫 + 401/403/404 + CLI 子命令 | `test_collab_api.py`(8) + `cli.py`(3) |
| 9 权限矩阵 | 三角色 × push/approve 状态码 + 自审 + 越权 404 + 匿名 401 | `test_collab_api.py` |

### Task 6-8 + 9 前端（持续迭代项，全部 ✅）

| Task | 验收要点 | 证据 |
|------|---------|------|
| 6 模板 review-gated | `collect_discovered_types` + `sediment` 写回 YAML + API/CLI | `test_template_review.py`(5) |
| 7 文档独立聚类 | `DocCommunityClusterer`（阈值连通分量）+ `docc-` 前缀 + 开关 | `test_doc_community_clusterer.py`(6) |
| 8 社区版本/合并/回滚 | `CommunityVersion` + append 式回滚（B3）+ merge/split + API | `test_community_version.py`(6) |
| 9 前端 UI | `ContributionsPanel`/`ContributionDetail`/`CommunityVersionsDialog` + 权限渲染 + 路由 | 三件套 + preview 闭环（A1/A2） |

> A1 ContributionDetail + A2 CommunityVersions 已闭合（2026-07-29）。演示场景 `collect` 在 admin 无 personal scope 时 diff 可能全 0（源库需有数据）。

## 测试隔离与原理

- 每用例独立内存 SQLite + `reset_app_stores()` 清理；`sys.modules` 桩隔离 litellm/uvicorn。
- **并发测试**：双 session 模拟 stale 提交，断言 `StaleDataError`（version_id_col）。
- **契约优先**：状态码矩阵 + 状态机流转 + 审计落库。
- **离线可跑**：零网络零重依赖（StubLLM + Hash + 内存 stores）；Louvain 缺 extra 时 `pytest.skip`。

## 验证过程（可复现）

```bash
uv sync
uv run pytest -q                    # 350 passed / 1 skipped / 1 failed(pre-existing)
uv run ruff check . && uv run ruff format --check .
uv run calliodesmo db init && uv run calliodesmo db seed && uv run calliodesmo serve
# POST /collab -> /submit -> /approve -> /merge（状态机 + 图谱合并）
uv run calliodesmo contributions list / show <id> / submit <id> / approve <id> / merge <id>
```

## 已知边界与后续

- **崩溃一致性（C5）**：合并跨两轨写非原子，v1 接受；持久化 stores 留 P9（已在 P4.5 落地）。
- **图谱合并同名不同义（B4）**：v1 精确匹配；`merge_decision` 为 v2 三段式留接口位（P4.5 Task 6 已落地）。
- **分布式 Sync**：单进程隐式；P9。
- **`test_ingest_llm_missing_key`**：pre-existing 环境问题，CI 应通过。

---

## P4.5 持久化贯通验证（Task 4，2026-07-31 / 复核 08-13）

> 证明 P4 在**持久化基线**（真 PG+pgvector+Neo4j + 增量索引）上仍全绿，且**合并真正落库、重启不丢**。衔接 [[docs/plans/phases/P4.5-persistence-production|P4.5 计划]] Task 4。

### 闭合项

| Step | 验收 | 证据 |
|------|------|------|
| 1 | P4 全套持久化基线全绿 | `test_contribution_*`/`test_graph_merge`/`test_merge_service`/`test_community_version`/`test_collab_*` 71 passed |
| 2 | **合并落库贯通**：merge -> 全新 AppStores（模拟重启）-> 数据读回 + 检索命中 | `test_p4_persistence_roundtrip.py`(2) |
| 3 | **rollback 真后端**：重启后状态一致 | `test_community_version.py` +3 PG 用例（共 9） |
| 4 | **双写一致性**：中途失败不留半写 | `test_merge_double_write_consistency.py`(3，TDD) |
| 5 | **权限矩阵** + 前端三件套 | `test_permission_isolation.py` +3 参数化（9）+ lint/vitest/build |

### 后端测试结果

```
uv run pytest -q  => 392 passed / 1 skipped / 1 failed(pre-existing JWT 401 污染，PR #8 已修)
2026-08-13 复核（PR #8 586b40e 后）: 407 passed / 1 skipped / 0 failed（连远端 PG 18.4 + pgvector + Neo4j）
```

**本阶段新增 17 用例全绿**：持久化贯通 2 + 社区 PG 贯通 3 + 双写一致性 3 + collab 权限矩阵 9。

### 关键发现（双写一致性，Step 4）

原顺序 Neo4j-first 会有半写（PG 失败时 Neo4j 已污染）。**修复**：**PG 镜像先写、Neo4j 权威后写**，强制不变式「Neo4j 写成功 ⇒ PG 镜像已写」（PG 是 Neo4j 超集）：PG 失败即抛（Neo4j 不写，不留半写）；Neo4j 失败可检测 + upsert 幂等可重试收敛。TDD：旧顺序红（Neo4j 已污染）-> 新顺序绿，neo4j 契约 7 用例无回归。

### 边界与后续

- **跨 store 三轨原子性**（向量/图/社区 + ORM）：v1 接受，两阶段留 P9。
- **「合并覆盖源 personal 数据」**为 P4 既有语义，非持久化引入。
- **Task 2 Step 5（ProfileCard/BM25 持久化）**：暂缓 2026-W33。
- **Task 3 Step 3/4（字段级合并 + 社区 id 稳定化）**：暂缓归 roadmap P9。

> **Task 4 闭合 -> 承诺批次（Task 1-4）完成，P4 生产可用 + 持久化 + 增量。** Task 5-7 后续接续（P4.5 已全闭合）。
