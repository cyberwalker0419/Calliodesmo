---
title: 全链路仿真验证报告
type: verification
tags:
  - verification
  - simulation
  - p4.5
created: 2026-07-31
---

# 全链路仿真验证报告（full-chain simulation）

> [!info] 在 P4.5 持久化基线上，以**真后端（PG+pgvector / Neo4j / 远端 BGE-M3 嵌入）**经
> HTTP 驱动多用户协作全链路（认证→摄入→问答→协作推送→合并→持久化重启→权限隔离），
> 逐请求录制 transcript。仿真过程中**发现并修复 2 处真后端 `/ingest` 路径上的生产 bug**。
> 关联：[[docs/verification/P4-verification|P4 验证报告]] · [[docs/plans/phases/P4.5-persistence-production|P4.5 计划]]

## 一、测试内容

| 维度 | 内容 |
| --- | --- |
| 仿真剧本 | 六幕 22 个 HTTP 请求，按真实用户路径驱动 |
| 后端栈 | PG 16 + pgvector（情景层 / 摘要层）+ Neo4j（语义层）+ 远端 BGE-M3（`/v1/embeddings`）|
| LLM | StubLLM（`test/stub`）——确定性抽取，保证可复现；真 LLM 文本质量属 [[docs/plans/phases/P2-retrieval-rag\|P2 评估 harness]] 范畴 |
| 隔离 | 专用 PG schema `fullchain_sim_<uuid>`（create_all + search_path 绑定）+ Neo4j 全图清空 + 会话级锁定 JWT secret |
| 驱动 | `httpx.ASGITransport`（进程内 HTTP，非 CLI 直连，避免 stores 跨进程不共享）|
| 录制 | `data/sim/fullchain-transcript.{json,log}` + 可读版 `fullchain-transcript-readable.md` |

仿真脚本：`scripts/full_chain_simulation.py`。运行：`uv run python scripts/full_chain_simulation.py`。

## 二、验证原理

- **HTTP 驱动而非服务层直调**：`/ingest` / `/query` / `/collab/*` 均经 FastAPI 路由 + 依赖注入
  完整跑通（鉴权 → AccessContext → SearchEngine/MergeService → 审计），证明"用户真正能走通的路径"。
- **隔离 schema**：与生产 `public`、测试 `calliodesmo_test` 物理隔离，结束 DROP CASCADE + 清 Neo4j，零残留。
- **持久化硬证明（幕 E）**：合并后调 `reset_app_stores()` 重建 stores 单例（模拟进程重启），
  全新实例指向同一 PG/Neo4j 仍读回项目库数据 → 证伪"P4 内存态合并重启全丢"。
- **权限隔离硬证明（幕 F）**：analyst-B 登录后 `/library/communities → []`（看不到 A 个人库）；
  analyst-A 调 `/collab/{id}/approve → 403`（无 approve 权限）；伪造/缺失 token `/auth/me → 401`。

## 三、六幕剧本与结果（22 步全绿，~9.5s）

| 幕 | 步骤 | 关键断言 | 结果 |
| --- | --- | --- | --- |
| A 认证 | `GET /healthz` / `POST /auth/token`(错/对) / `GET /auth/me` | 错误密码 401、正确 200、permissions=[export,ingest,push,query] clearance=SECRET | ✅ |
| B 摄入 | `POST /ingest`（中英 md）→ ECL 全链路落 PG+Neo4j | 201（1.6s）：documents=1 chunks=1 entities=2 relations=1 communities=2；PG 直查 doc_id/chunks/entities/relations/communities 全对齐 | ✅ |
| C 问答 | `POST /query` ×3 模式 | native_rag sources=1（答案含 OpenAI/GPT-4 实体）/ local sources=0 / global sources=1 | ✅ |
| D 协作 | `/collab` create→diff→submit→approve→merge | create 201、diff（new_entities=2 conflicts=2）、submit/approve 200、**A approve → 403**、reviewer merge 200 | ✅ |
| E 持久化重启 | `reset_app_stores()` → `GET /library/communities?scope=project` → `/query` | 重启后 reviewer 可见项目社区=1；项目库检索 sources=1 | ✅ |
| F 权限隔离 | analyst-B `/library/communities`、伪 token `/auth/me` | B 可见社区=0；伪 token/无 token → 401 | ✅ |

完整可读 transcript：[[data/sim/fullchain-transcript-readable|transcript]]。

## 四、发现并修复的 2 处生产 bug

仿真撞到的两个 bug 均**仅在 `/ingest` HTTP 端点 + 真后端 stores 组合下复现**——`serve --seed-demo`
走 `_json_safe` 清洗 + 内存 stores 故未暴露，现有 P4.5 持久化测试用 sanitized metadata 也未覆盖。
属 P4.5"生产化"目标范围内的真实回归。

### Bug 1：metadata JSON 列序列化失败（UUID / 枚举不可序列化）

- **现象**：`POST /ingest` → `TypeError: Object of type UUID is not JSON serializable`（PgVectorStore.upsert_chunks）。
- **根因**：`_DemoAccessLoader`（`/ingest` 端点用）把 `owner_id`(UUID) / `team_id` / `project_id`(UUID) /
  `access_level`(ClearanceLevel) / `library_scope`(LibraryScope) 直接塞进 `doc.metadata` → chunk metadata →
  PgVectorStore 的 `chunks.metadata` JSONB 列用标准 `json` 序列化炸。chunk 的 typed 字段（owner_id 等）
  本就在独立列，metadata 里这份是冗余副本。
- **修复**：新增 shared `src/calliodesmo/utils/json.py::json_safe`（UUID/datetime→str、Enum→.value、dict/list 递归），
  在三处 JSON 写入边界清洗：`PgVectorStore.upsert_chunks`、`PgCommunityStore.upsert_communities`、
  `Neo4jGraphStore._entity_props/_relation_props`（Neo4j 属性 + PG 镜像）。`demo_seed._json_safe` 委托复用（DRY）。
- **回归测试**：`tests/test_json_safe.py`（5 用例，锁契约）。

### Bug 2：DocumentCommunityDeriver 捅 InMemory 内部属性 `_records`

- **现象**：ingest 走到文档社区派生 → `AttributeError: 'PgCommunityStore' object has no attribute '_records'`。
- **根因**：`community_deriver.derive` 做"手动编辑保护"时直接访问 `community_store._records`（InMemory
  store 的内部 dict），PgCommunityStore 无此属性——违反"按接口编程"。
- **修复**：改走 `CommunityStore.list_communities(access=...)` 接口取 `metadata["manual"]` 集合做跳过判定，
  对所有 store 实现统一成立。
- **影响**：真后端 `/ingest` 文档社区派生恢复；InMemory 路径语义不变。

## 五、回归验证

| 项目 | 结果 |
| --- | --- |
| 受影响模块测试（pg_vector / pg_community / neo4j / indexing_engine / serve_seed_demo / persistence_roundtrip / p4_persistence_roundtrip） | ✅ **30 passed** |
| 新增 `tests/test_json_safe.py` | ✅ 5 passed |
| `ruff format .` + `ruff check .` | ✅ 全绿（新增 `per-file-ignores` 豁免仿真脚本的 E402——env 覆盖须在 import calliodesmo 之前）|

## 六、前端可视化录制（snapshot）

> 截图工具在本环境持续超时，改用 `preview_*` 无障碍树 snapshot 文本记录。证据：[[data/sim/frontend-visual|前端视觉记录]]。

| 屏 | 路径 | 录得 |
| --- | --- | --- |
| 登录页 + 错误态 | `/login` | 错误密码 → 后端 401 → "用户名或密码错误" |
| QA 面板 | `/app/qa` | admin/SECRET 顶栏、三模式（Native/Local/Global）+ top_k、提问→渲染答案卡（链路贯通）|
| 知识库浏览 | `/app/library` | 库范围切换（全部/个人/项目/团队）、实体图谱/社区导航双 tab、Canvas 图谱区 |

> 前端 QA/Library 出现"无证据 / 无可见实体"空态：admin 上下文与演示 team 库的访问范围匹配问题，
> 非链路故障——后端全链路仿真（隔离 schema + 正确 access 装配）已证检索命中 sources=1 与项目库持久化可见。

## 七、未竟点

- 前端可视化录制受截图工具超时所限，仅 snapshot 文本；**桌面 + 移动视口栅格截图留待 2026-W32**
  补（环境稳定后用 `preview_screenshot` + GLM-EYE 识图归档）。
- 仿真用 StubLLM 抽取（确定性优先）；**真 LLM（`openai/local-model` @ 192.168.50.97:8081）
  端到端文本质量验证留待 P2 harness 或单独跑**，不属本仿真目标。
