# P3 Web UI 验证报告

> 验证日期：2026-07-27
> 阶段：P3 Web UI（[[docs/plans/phases/P3-web-ui|P3 计划]]）· 前置：[[docs/verification/P2-verification|P2 验证报告]]

## 总览

P3 启动 Web UI 并补全管理后端：`/admin/*` 管理端点、`/library/*` 只读浏览端点、文档社区手动管理后端，构建**操作工具风格** SPA（React 19 + Vite + TS + Tailwind + shadcn/ui 源码拷贝）。开发期 dev proxy（`/api` 转发），生产 StaticFiles 同源托管；后端为权限唯一真相，三维权限模型在 UI 与 API 双层一致。

- 后端 **289 passed / 0 failed** · Ruff 全绿 · 前端 vitest 5 passed + build 通过

## Task 验收明细（全部 ✅）

| Task | 验收要点 | 测试 |
|------|---------|------|
| 1 管理/浏览后端 | `require_permission` 守卫 · `/admin/users`（list/create/update/deactivate 软删）· `/admin/teams` `/admin/projects` CRUD · `/library/profile-cards/communities/entities`（visible_to）· stores 内存单例工厂 · CLI users/teams · `serve --seed-demo` | `test_admin_api.py`(11)+`library_api.py`(6)+`admin_cli.py`(4)+`serve_seed_demo.py`(4) |
| 2 前端工程 | dev(5173)/build · React 19+Vite6+TS+Tailwind+shadcn 源码拷贝 · react-force-graph-2d React 19 spike · API client（cookie+Bearer+401 拦截）· dev proxy · StaticFiles 托管 · CI job | `client.test.ts`(5) |
| 3 登录与会话 | 登录页 + AuthContext 拉 `/auth/me` + RequireAuth · httpOnly+SameSite=Lax cookie · `/auth/change-password` · 自注册默认关 | — |
| 4 问答面板 | 三模式 segmented control + top_k · 来源高亮展开 context_chunks · loading/error/empty | — |
| 5 知识库浏览 | ProfileCard 列表/详情 · 社区导航 · 实体详情 + 交互子图（`GraphStore.subgraph` BFS + `GET /library/subgraph`，展开/折叠/调范围） | `test_subgraph_api.py`(6) |
| 6 用户/团队/项目管理 UI | `UserManage`（clearance 下拉/active toggle/软删）· `TeamProjectManage` · 管理入口仅 manage_users 可见 | — |
| 7 文档社区手动管理 | CommunityStore 手动操作（rename/set_access/add/remove）置 `manual=True` · `/admin/document-communities`（manage_community 守卫）· 自动派生不覆盖手改 · Manage UI | `test_document_community_manage_api.py`(6) |
| 8 角色可见性+矩阵 | 后端唯真相 · 三角色参数化矩阵对齐 `DEFAULT_ROLE_PERMISSIONS` · clearance 隔离 404 · 匿名 401 | `test_permission_isolation.py`(18) |

**收尾补充**：ScopeSwitcher（`/library/*` 可带 `scope` 参数，前端按成员关系判定有权 scope）；远端重排 `HttpReranker`（`reranker_provider=remote`，兼容 llama.cpp bge-reranker-v2-m3，`test_http_reranker.py`(7)）。

## 测试隔离与原理

- 每用例独立内存 SQLite + `reset_app_stores()` try/finally 清理；`sys.modules` 桩隔离 litellm/uvicorn。
- 契约优先（API client 断言 Bearer/401/ApiError）；参数化矩阵 3 角色 × 5 端点；离线全桩零网络。

## 验证过程（可复现）

```bash
uv sync && uv run ruff check . && uv run pytest -q    # 289 passed
cd frontend && npm ci && npm run build && npm test    # build 通过 + vitest 5 passed
uv run calliodesmo db init && uv run calliodesmo db seed
uv run calliodesmo serve --seed-demo                  # http://localhost:8000
```

## 已知边界与后续

- **merge/split** 按裁剪线并入 P4（社区版本/回滚）。
- **Playwright 截图**（桌面+移动双视口）随后续迭代补齐。
- **审计查看 UI**：审计只记不看，随 P4 或后续。
- **refresh token**：v1 从简，JWT 过期重登。
- **实体社区检测改 Louvain**：P3 记录为待办（当时两个检测器都是连通分量，与 AGENTS.md「Leiden」不符），已在 P4 实现 `NetworkxCommunityDetector` 升级 `nx.community.louvain_communities`（模块度，seed 固定）并更正文档说法。

## 演示数据梯度

`data/demo/` 文档按文件名前缀拉开 clearance 梯度（`public__*`/`internal__*`/`confidential__*`）供权限矩阵回归；seed 产物落盘 `data/demo/seed-cache.json`，二次 `serve --seed-demo` 命中缓存跳过 LLM。
