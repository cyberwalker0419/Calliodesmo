# P3 Web UI 验证报告

> 验证日期：2026-07-27
> 阶段：P3 Web UI（[[docs/plans/phases/P3-web-ui|P3 计划]]）
> 前置：P2 基础检索与 RAG（[[docs/verification/P2-verification|P2 验证报告]]）

## 总览

P3 启动了 Web UI 并补全了管理后端。在 P0/P1/P2 的三层知识图谱与检索能力之上，新增了 `/admin/*` 管理端点、`/library/*` 只读浏览端点、文档社区手动管理后端，并构建了面向情报分析人员的操作工具风格 SPA（React 19 + Vite + TypeScript + Tailwind + shadcn/ui 源码拷贝）。前端经 dev proxy（`/api` 转发 FastAPI）与生产 StaticFiles 同源托管两种模式运行；后端为权限唯一真相，三维正交权限模型（角色 RBAC + clearance + scope）在 UI 与 API 双层一致。

**后端测试结果：289 passed / 0 failed / 0 errors**
**Ruff：All checks passed!（check + format）**
**前端测试结果：vitest 5 passed（API 客户端契约）**
**前端构建：`npm run build` 通过（dist 产物由 FastAPI StaticFiles 托管）**

## Task 验收明细

### Task 1: 管理与浏览后端补全（service + API + CLI） ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `require_permission` 守卫 helper（有权放行/无权 403） | ✅ | `src/calliodesmo/api/deps.py` |
| `/admin/users` list/create/update/deactivate(软删除) + 角色分配 | ✅ | `src/calliodesmo/api/admin.py` |
| `/admin/teams` `/admin/projects` CRUD + 成员增删 | ✅ | 同上 |
| `/library/profile-cards`（visible_to 过滤）/ communities / entities | ✅ | `src/calliodesmo/api/library.py` |
| stores 内存单例工厂（与 get_search_engine 共享同一实例） | ✅ | `src/calliodesmo/api/deps.py` `AppStores` |
| CLI `users list/create/deactivate`、`teams create/add-member` | ✅ | `src/calliodesmo/cli.py` |
| `serve --seed-demo`（进程内灌演示数据 + 落盘缓存二次命中跳过 LLM） | ✅ | `src/calliodesmo/ecl/demo_seed.py` |
| 软删除保留审计可追溯 | ✅ | `deactivate_user` 置 `is_active=False` |
| 管理动作全程记审计（`action="manage_user"`） | ✅ | 每个端点 record_audit |

测试文件：`tests/test_admin_api.py`（11）+ `tests/test_library_api.py`（6）+ `tests/test_admin_cli.py`（4）+ `tests/test_serve_seed_demo.py`（4）

### Task 2: 前端工程脚手架 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| `frontend/` 独立工程可 `npm run dev`（5173）与 `npm run build` | ✅ | `frontend/package.json` + `dist/` 产物 |
| React 19 + Vite 6 + TS + Tailwind + shadcn/ui 源码拷贝 | ✅ | `frontend/src/components/ui/*` |
| react-force-graph-2d React 19 兼容 spike 通过 | ✅ | `frontend/src/features/library/EntityGraph.tsx` |
| API 客户端（cookie 会话 + Bearer 兜底 + 401 拦截 + ApiError） | ✅ | `frontend/src/api/client.ts` |
| Vite dev proxy（`/api` -> 8000 去前缀） | ✅ | `frontend/vite.config.ts` |
| 生产 StaticFiles 同源 SPA 托管 | ✅ | `src/calliodesmo/api/app.py` `SPAStaticFiles` |
| CI 前端 job（npm ci / build / vitest） | ✅ | `.github/workflows/ci.yml` |

测试文件：`frontend/src/api/client.test.ts`（5 tests）

### Task 3: 登录与会话 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| 登录页 -> `POST /auth/token` -> 存 token -> 跳 /app | ✅ | `frontend/src/features/auth/LoginPage.tsx` |
| AuthContext 启动拉 `/auth/me` 注入全局 AccessContext | ✅ | `AuthContext.tsx` |
| RequireAuth 守卫（无 token 跳 /login 记回跳） | ✅ | `RequireAuth.tsx` |
| httpOnly + SameSite=Lax cookie 下发 + `/auth/logout` 清 cookie | ✅ | `src/calliodesmo/api/app.py` |
| `/auth/change-password`（旧密码校验 + Argon2 重哈希 + 审计） | ✅ | `auth/service.change_password` |
| 自注册默认关（开启时 clearance 上限 INTERNAL） | ✅ | `config.allow_self_register` + `/auth/register` |

### Task 4: 问答面板 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| 三模式 segmented control（Native/Local/Global）+ top_k | ✅ | `frontend/src/features/qa/AskPanel.tsx` |
| 来源标注高亮（点击展开 context_chunks 证据） | ✅ | `AnswerCard.tsx` |
| loading/error/empty 状态完备 | ✅ | 同上 |

### Task 5: 知识库浏览（ProfileCard / 社区 / 实体 / 交互子图） ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| ProfileCard 列表/详情（结构化字段 + narrative 人读区区分标注） | ✅ | `frontend/src/features/library/LibraryPage.tsx` |
| 社区导航（level 0/1 tab） | ✅ | 同上 |
| 实体详情 + 邻居子图 | ✅ | 同上 |
| `GraphStore.subgraph` 接口（BFS + limit 截断 + 去重 + visible_to） | ✅ | `src/calliodesmo/interfaces/graph_store.py` |
| `GET /library/subgraph`（多种子/hops/limit） | ✅ | `src/calliodesmo/api/library.py` |
| 交互式子图（展开/折叠/调范围，大库按需拉取不卡） | ✅ | `EntityGraph.tsx` |

测试文件：`tests/test_subgraph_api.py`（6 tests）

### Task 6: 用户与团队/项目管理 UI ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| 用户管理（列表/新建/clearance 下拉/active toggle/软删除） | ✅ | `frontend/src/features/admin/UserManage.tsx` |
| 团队/项目管理（新建 + 成员增删） | ✅ | `TeamProjectManage.tsx` |
| 管理入口仅 manage_users 可见（前端隐藏，后端仍守卫） | ✅ | `App.tsx` 导航 + `useAccess` |

### Task 7: 文档社区手动管理（后端 + UI） ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| CommunityStore 手动操作接口（rename/set_access_level/add/remove_member_doc） | ✅ | `src/calliodesmo/interfaces/community_store.py` |
| 手动操作置 `metadata["manual"]=True` | ✅ | `InMemoryCommunityStore._mark_manual` |
| `/admin/document-communities` 端点（manage_community 守卫 + 审计） | ✅ | `src/calliodesmo/api/admin.py` |
| 自动派生跳过 manual 社区不覆盖手改 | ✅ | `community_deriver.py` |
| DocumentCommunityManage UI（重命名/access_level） | ✅ | `frontend/src/features/admin/DocumentCommunityManage.tsx` |

测试文件：`tests/test_document_community_manage_api.py`（6 tests）

### Task 8: 角色可见性与权限矩阵回归 ✅

| 验收项 | 状态 | 证据 |
|--------|------|------|
| 后端为唯一真相：受限端点守卫全覆盖，越权直击 403 | ✅ | `tests/test_permission_isolation.py` |
| analyst/reviewer/admin 三角色权限矩阵一致（DEFAULT_ROLE_PERMISSIONS 对齐） | ✅ | 参数化矩阵 15 tests |
| clearance 隔离（低 clearance 看不到高 access_level 数据 -> 404） | ✅ | `test_clearance_isolation_in_library` |
| 匿名访问受限端点 -> 401 | ✅ | `test_unauthenticated_all_endpoints_reject` |

测试文件：`tests/test_permission_isolation.py`（18 tests，含参数化矩阵）

## 测试隔离与原理

- **后端隔离**：每用例独立内存 SQLite（`sqlite+aiosqlite:///:memory:`）；stores 单例经 `reset_app_stores()` 在 try/finally 清理；`sys.modules` 桩隔离 litellm/uvicorn。
- **契约优先**：API 客户端测试断言 Bearer 注入、401 拦截、ApiError 结构，保证前后端契约。
- **参数化矩阵**：Task 8 用 `@pytest.mark.parametrize` 覆盖 3 角色 × 5 端点 = 15 组合，断言与 `DEFAULT_ROLE_PERMISSIONS` 完全对齐。
- **离线可跑**：所有测试零网络、零重依赖（StubLLM + Hash 嵌入 + 内存 stores）。

## 验证过程（可复现）

```bash
# 后端
uv sync
uv run pytest -q                    # 289 passed
uv run ruff check . && uv run ruff format --check .   # All checks passed!

# 前端
cd frontend && npm ci
npm run build                       # dist/ 产物（FastAPI StaticFiles 托管）
npm test                            # vitest 5 passed

# 端到端演示（需真实 LLM 或 test/stub）
uv run calliodesmo db init && uv run calliodesmo db seed
uv run calliodesmo serve --seed-demo   # serve 进程内灌演示数据 + 缓存
# 浏览器打开 http://localhost:8000 （生产静态托管）或 dev: cd frontend && npm run dev
```

## 收尾补充：ScopeSwitcher + 远端重排 provider

### ScopeSwitcher（Task 5 Step 10 完整实现）
- **后端**：`/library/profile-cards` `/library/communities` `/library/subgraph` 新增可选 `scope` 查询参（`LibraryScope` 枚举校验，无效值 422），按 `record.library_scope` 后置过滤；权限仍由 `visible_to` 兜底（后端唯一真相不变）。
- **前端**：`frontend/src/features/library/ScopeSwitcher.tsx`——按成员关系判定“有权 scope”（personal 恒有；project 需 `project_ids` 非空；team 需 `team_ids` 非空，与 `visible_to` 一致而非 `library_scopes`，避免角色 scope 与实际可见数据不同步）；无权 scope 禁用不可选；切换后档案卡/社区/子图均随 scope 过滤（`useSubgraph` 透传）。
- **测试**：`tests/test_library_scope_filter.py`（3：profile-cards / communities / subgraph 的 scope 收窄 + 无效值 422）。
- 顺带修复 `LibraryPage.tsx` 一处被 `tsc -b` 增量缓存掩盖的既有 TS1382（`->` 箭头文本改模板字面量）。

### 远端重排 provider（接入已部署的 bge-reranker-v2-m3）
- **新增** `HttpReranker`（`src/calliodesmo/retrieval/http_reranker.py`）：零重依赖（仅 httpx），POST `{api_base}/rerank`，按 `relevance_score` 降序、`index` 映射回候选；兼容 llama.cpp（`relevance_score`）与 Cohere/Jina（`score`）。
- **配置**：`reranker_provider`（none|local|remote）+ `reranker_api_base` + `reranker_api_key`（`config.py` + `.env.example`）；`.env` 指向 `http://rerank-host:8083`（部署的 bge-reranker-v2-m3）。
- **接线**：`build_reranker(settings)` 路由 + `get_search_engine` 注入；默认 `none` 保持 `IdentityReranker` 降级行为不变（向后兼容）。
- **测试**：`tests/test_http_reranker.py`（5 重排契约 + 2 路由）；实调远端 rerank 服务冒烟通过（“张三是谁” 相关 chunk 排序正确）。

> 注：完整 `serve --seed-demo` 端到端演示需 LLM（ECL 抽取/摘要）；本次仅提供重排服务，待接入 LLM 后即可跑通。
## 已知边界与后续

- **merge/split**：按裁剪线并入 P4（依赖社区版本/分支/回滚能力）。
- **Playwright 截图**：配置已就绪（`frontend/playwright.config.ts` 桌面+移动双视口），关键流程截图随后续迭代补齐。
- **ScopeSwitcher**：Task 5 Step 10 已完整实现（详见下方收尾补充）。
- **审计查看 UI**：审计只记不看（查看界面随 P4 或后续阶段）。
- **refresh token**：v1 从简，JWT 过期重登。

## 演示数据梯度

`data/demo/` 文档按文件名前缀拉开 clearance 梯度（`public__*` / `internal__*` / `confidential__*`），供 Task 8 权限矩阵回归与演示可见性隔离。seed 产物落盘缓存 `data/demo/seed-cache.json`，二次 `serve --seed-demo` 命中缓存直接加载、跳过 LLM。

## 待办：实体社区检测改用模块度算法（Louvain/Leiden）

> 状态：暂缓（用户要求最后做）。记录于 2026-07-28。

**问题**：实体社区（level 0）当前两个检测器都是**连通分量**（`ConnectedComponentsDetector` 默认；`NetworkxCommunityDetector` 也只 `nx.connected_components`），**非 Leiden/Louvain 稠密子群**。当实体关系图高度连通时，几乎所有实体塞进一个社区 -> 意义不明。`AGENTS.md` 写的"Leiden 社区检测"与代码不符。

**改法**：
1. `NetworkxCommunityDetector` 从 `nx.connected_components` 改为 `nx.community.louvain_communities`（稠密子群，按模块度划分）。
2. 装网络分析 extra：`uv sync --extra graph-analytics`。
3. `CognifyPipeline` 默认用 `NetworkxCommunityDetector`（或加配置 `community_detector=networkx|connected`）。
4. 社区 `title`/`summary` 由 LLM 据成员实体生成（已有 `LLMCommunitySummarizer`）；改进提示词让 summary 明确说明"为何这些实体归一组"。
5. 重新建图（清缓存 + `serve --seed-demo`）才生效。
6. 更正 `AGENTS.md` 的"Leiden"说法与实现一致。

**影响文件**：`src/calliodesmo/ecl/cognify.py`、`config.py`、`AGENTS.md`、`.env.example`。