---
title: P3 Web UI 实施计划
type: phase-plan
phase: P3
tags:
  - plan/phase
created: 2026-07-27
---
# P3 Web UI 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P2-retrieval-rag|P2]] / [[docs/plans/phases/P4-git-collab|P4]]。

> [!important] 前置条件（开工前确认）
> - **基线**：P3 分支从 **P2 合并后的 main** 切出。`/query`、`get_search_engine`、`retrieval/` 目前在 `codex/p2-retrieval-rag` 分支未合并；Task 1 的 stores 依赖工厂要求与 `get_search_engine` 共享同一实例，未合并开工必冲突。
> - **MVP 裁剪线**（预先声明，防超时）：Task 5 子图可视化可降级为实体邻居列表（表格视图）；Task 7 的 merge/split **整块**（CommunityStore 接口 + `/admin/document-communities` 端点 + UI + Step 5 语义）一律并入 P4，本阶段 Task 7 只做 rename/retag/access_level/增删文档——不出现半切的"接口做了却不验收"。
> - **MVP 必做清单**（达标线）：Task 1 全量 + Task 2 + Task 3 + Task 4 + Task 5 降级版（交互式子图或邻居表二选一）+ Task 8 权限矩阵回归。命中达标线即 P3 MVP 达成；Task 6、Task 7 完整版、Task 5 子图增强属持续迭代，按周补齐。

**Goal:** 启动 Web UI 并持续迭代：登录与会话、个人/组织库浏览、问答面板、用户与团队/项目管理、文档社区手动管理、角色可见性。**后端补全是 UI 的前置**——兑现路线图“用户/用户组管理 CRUD 延后至 P3 落地，service/CLI/API 管理端点同步补全”：补全用户/团队/项目的 list/update/deactivate service 与 `/admin/*` 管理端点、`/library/*` 只读浏览端点，再在其上构建前端。UI 用 `frontend-design` skill 构建，面向情报分析人员的**操作工具风格**（密集有序、可扫描、可比对、可重复操作），而非营销/编辑风。

**Architecture:** 前端为独立 SPA（`frontend/` 目录，与 `src/` 平级），与后端 FastAPI 解耦。开发期 Vite dev server（5173）经 **dev proxy** 将 `/api` 转发 FastAPI（8000），前后端逻辑同源（httpOnly cookie 全程可用，无需 CORS middleware）；生产期前端构建产物由 FastAPI 静态托管（`StaticFiles` 挂 `frontend/dist`），同源免 CORS。后端沿用 P0/P1 的 `AccessContext` 依赖与审计：管理端点 `/admin/*` 需 `manage_users` / `manage_community` 权限守卫（403），浏览端点 `/library/*` 与 P2 `/query` 需 `query` 权限；**后端为权限唯一真相**，前端隐藏/禁用仅 UX。stores 注入：内存 stores 单例经 FastAPI 依赖工厂共享（ingest/query/browse 同进程），prod 持久化随真后端（P9）。

**Tech Stack:**
- 前端：React 19 + Vite + TypeScript · Tailwind CSS · shadcn/ui（源码拷贝而非 npm 依赖，兼容性取决于 Radix primitives + `lucide-react` 图标）· TanStack Query（数据获取/缓存/失效）· React Router（路由 + 受保护路由）
- 构建：Vite（dev）/ 构建产物 FastAPI 静态托管（prod）
- 后端（P0/P1 基础上扩展）：FastAPI `/admin/*` + `/library/*` 端点 · `require_permission` 守卫 helper · stores 依赖工厂
- 测试：后端 `pytest` + `httpx`（端点 + 权限守卫）；前端 `vitest` + `@testing-library/react` + Playwright（关键流程截图）

---

### Task 1: 管理与浏览后端补全（service + API + CLI）

**目标：** 补全路线图延后至 P3 的管理后端：用户/团队/项目的 list/update/deactivate service、`/admin/*` 管理端点（`manage_users` / `manage_community` 守卫）、`/library/*` 只读浏览端点（`query` 守卫，接入 P1 的 ProfileCardStore / CommunityStore / GraphStore）、CLI 管理命令。管理动作全程记审计。

> [!note] 现状（P0/P1）：`auth.service` 仅有 `create_*` / `assign_role` / `add_*_member` / `get_access_context`，缺 list/update/deactivate；API 仅 `/healthz` `/auth/token` `/auth/me`；ProfileCardStore / CommunityStore / GraphStore 无 HTTP 端点。本 Task 是 UI（Task 2-8）的接口地基。

**Files:**
- Modify: `src/calliodesmo/auth/service.py`（新增 `list_users` / `update_user` / `deactivate_user` / `list_teams` / `list_projects` / `remove_team_member` / `remove_project_member`）
- Create: `src/calliodesmo/api/admin.py`（`/admin/users` `/admin/teams` `/admin/projects` 路由，挂载进 app）
- Create: `src/calliodesmo/api/library.py`（`/library/profile-cards` `/library/communities` `/library/entities/{name}` 只读路由）
- Modify: `src/calliodesmo/api/app.py`（`include_router` + `require_permission` 守卫接线）
- Modify: `src/calliodesmo/api/deps.py`（`require_permission(ctx, perm)` helper + `get_profile_card_store` / `get_community_store` / `get_graph_store` 内存单例工厂）
- Modify: `src/calliodesmo/api/schemas.py`（`UserOut` / `UserCreate` / `UserUpdate` / `TeamOut` / `ProjectOut` / `ProfileCardOut` / `CommunityOut` / `EntityOut`）
- Modify: `src/calliodesmo/cli.py`（`users list/create/deactivate`、`teams create/add-member`、`serve --seed-demo`）
- Create: `data/demo/`（2-3 篇样例情报文档，含可演示的实体/关系/社区）
- Test: `tests/test_admin_api.py`、`tests/test_library_api.py`、`tests/test_admin_cli.py`、`tests/test_serve_seed_demo.py`

**权限守卫 helper（`api/deps.py`）：**

```python
def require_permission(ctx: AccessContext, permission: Permission) -> None:
    if not ctx.has_permission(permission):
        raise HTTPException(status_code=403, detail=f"缺少权限：{permission.value}")
```

**管理端点（`api/admin.py`）：**

```python
@router.get("/users", response_model=list[UserOut])
async def list_users(ctx=Depends(get_current_context), session=Depends(get_session)):
    require_permission(ctx, Permission.MANAGE_USERS)  # 缺权限 403
    ...


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(req: UserCreate, ctx=..., session=...):
    require_permission(ctx, Permission.MANAGE_USERS)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "create", "target": req.username},
        source="api",
    )
    ...


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, req: UserUpdate, ctx=..., session=...): ...


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID, ctx=..., session=...
): ...  # 软删除（is_active=False）
```

**浏览端点（`api/library.py`）：**

```python
@router.get("/profile-cards", response_model=list[ProfileCardOut])
async def list_profile_cards(
    ctx=Depends(get_current_context), store=Depends(get_profile_card_store)
):
    require_permission(ctx, Permission.QUERY)
    return [
        ProfileCardOut.from_card(c) for c in await store.list(access=ctx)
    ]  # store 内已 visible_to 过滤


@router.get("/communities", response_model=list[CommunityOut])
async def list_communities(
    *, level: int | None = None, ctx=..., store=Depends(get_community_store)
): ...


@router.get("/entities/{name}", response_model=EntityOut)
async def get_entity(name: str, ctx=..., store=Depends(get_graph_store)): ...  # 实体 + neighbors
```

- [ ] **Step 1:** `require_permission` helper：有权放行、无权 403 测试 -> 实现跑绿
- [ ] **Step 2:** `list_users` / `update_user`（clearance/active）/ `deactivate_user`（软删除 `is_active=False`，保留审计可追溯）service + `/admin/users` 端点；缺 `manage_users` -> 403；管理动作记 `action="manage_user"` 测试 -> 实现跑绿
- [ ] **Step 3:** `/admin/teams` `/admin/projects`（list/create）+ 成员增删端点（`POST /admin/teams/{id}/members` / `DELETE .../members/{user_id}`）；`manage_users` 守卫 + 审计测试 -> 实现跑绿
- [ ] **Step 4:** `/library/profile-cards`（按 `visible_to` 过滤）/ `/library/communities`（按 level 过滤）/ `/library/entities/{name}`（含 neighbors）；`query` 守卫；越权记录不返回测试 -> 实现跑绿
- [ ] **Step 5:** stores 依赖工厂（`get_profile_card_store` 等内存单例，与 `get_search_engine` 共享同一实例）测试 -> 实现跑绿
- [ ] **Step 6:** CLI `users list/create/deactivate`、`teams create/add-member`（`CliRunner` 断言退出码与输出）测试 -> 实现跑绿
- [ ] **Step 7:** 软删除与引用完整性：deactivate 后用户不可登录、其历史审计记录保留；`get_access_context` 对 `is_active=False` 返回 None（沿用 P0 逻辑）测试 -> 实现跑绿
- [ ] **Step 8:** 演示数据：`serve --seed-demo` 启动时对 `data/demo/` 样例文档在 serve 进程内跑 ECL 管线注入内存 stores（解决内存模式 CLI ingest 与 API 跨进程不可见）；**seed 产物落盘缓存**（如 `data/demo/seed-cache.json`，序列化 ProfileCard/Community/Subgraph 结果），二次 `serve` 命中缓存直接加载、跳过 LLM 管线（首次全量跑慢，重跑别再等一轮 LLM）；**`data/demo/` 文档 clearance 故意拉开梯度**（public/internal/confidential 各备样例，供 Task 8 权限矩阵回归与演示可见性隔离）；seed 后 `/library/profile-cards` 非空测试 -> 实现跑绿

**验收：**
- 用户/团队/项目 CRUD + 成员管理齐全，`manage_users` / `manage_community` 守卫，管理动作记审计
- `/library/*` 只读浏览端点按 `visible_to` 过滤、`query` 守卫
- CLI 管理 + 浏览命令可用；软删除保留审计可追溯
- 停用用户的既有内容（ingest 文档/社区/ProfileCard）保留且仍按 clearance 对他人可见，属设计预期（情报连续性不因人离开而断）
- `calliodesmo serve --seed-demo` 后浏览端点返回非空演示数据（UI 演示不面对空库）

---

### Task 2: 前端工程脚手架

**目标：** 初始化 `frontend/` SPA 工程（React + Vite + TS + Tailwind + shadcn/ui），建 API 客户端（同源 cookie 会话 + JWT 注入）、TanStack Query 配置、React Router 骨架；开发期 Vite dev proxy 同源 + 生产静态托管，前端能联通 `/healthz`。

**Files:**
- Create: `frontend/`（`package.json` / `vite.config.ts` / `tsconfig.json` / `tailwind.config.ts` / `postcss.config.js` / `index.html`）
- Create: `frontend/src/api/client.ts`（fetch wrapper：同源 cookie 会话为主 + `Authorization: Bearer` 兼容注入 + 统一错误处理）
- Create: `frontend/src/main.tsx` / `App.tsx`（QueryClientProvider + RouterProvider）
- Create: `frontend/src/routes.tsx`（路由表 + 受保护路由占位）
- Modify: `src/calliodesmo/api/app.py`（`StaticFiles` 挂 `frontend/dist`，生产同源；API 路由双挂 `/api` 前缀，前端 baseURL 固定 `/api`）
- Modify: `src/calliodesmo/config.py`（`allow_self_register: bool = False`；`cors_origins: list[str]` 仅兜底，默认空 = 关闭）
- Modify: `.gitignore`（`frontend/node_modules/` `frontend/dist/`）
- Modify: `frontend/vite.config.ts`（dev proxy：`/api` -> `http://localhost:8000`，rewrite 去前缀）
- Create: `frontend/playwright.config.ts`（桌面 + 移动两视口）
- Modify: `.github/workflows/ci.yml`（前端 job：`npm ci` / `npm run build` / `vitest`）
- Test: `frontend/src/api/client.test.ts`（Vitest）

- [ ] **Step 1:** `frontend/` 初始化（Vite React-TS 模板 + Tailwind + shadcn/ui CLI 接入 + `lucide-react`）；`npm run build` 产出 `dist/` 测试（构建通过）；**图引擎选型 spike（前置）**：脚手架阶段就验证 `react-force-graph`（依赖 three.js）的 React 19 兼容性——最小 demo 渲染几个节点+边能跑通即可，不兼容即定 vis-network 方案。别拖到 Task 5（10 步核心）才试，那时换底层引擎返工损失最大；选型结果回填 Task 5 的图引擎与 `SubgraphResponse` 契约
- [ ] **Step 2:** `api/client.ts`：`fetch` wrapper 注入 Bearer、401 自动跳登录、统一错误对象；TanStack Query `QueryClient` 配置测试 -> 实现跑绿
- [ ] **Step 3:** Vite dev proxy（`/api` -> 8000，rewrite 去前缀，逻辑同源，cookie 方案全程一致）+ 后端 API 双挂 `/api` 前缀 + 生产 `StaticFiles` 挂 `frontend/dist`（SPA fallback 到 `index.html`）；`/healthz` 经 proxy 联通测试 -> 实现跑绿
- [ ] **Step 4:** React Router 骨架（`/login` `/app/*` 占位）+ `RequireAuth` 守卫占位（Task 3 实现）测试 -> 实现跑绿
- [ ] **Step 5:** Playwright 接入（`@playwright/test` + 桌面/移动视口配置 + 登录页冒烟截图用例）；CI 前端 job（`npm ci` / `npm run build` / `vitest`）跑通测试 -> 实现跑绿

**验收：**
- `frontend/` 独立工程可 `npm run dev`（5173）与 `npm run build`
- API 客户端注入 JWT、401 处理；TanStack Query 配置就绪
- 开发期 Vite proxy 同源 + 生产静态托管；`/healthz` 前端可联通
- Playwright 冒烟截图可跑；CI 含前端构建 + 测试 job

---

### Task 3: 登录与会话

**目标：** 登录页（`POST /auth/token`）+ 会话管理（JWT 存 httpOnly cookie 优先）+ `AccessContext` 全局注入（`GET /auth/me`）+ 受保护路由 + 登出。自注册默认关（管理员建用户为主，`CALLIODESMO_ALLOW_SELF_REGISTER` 开关）。

> [!note] JWT 存储：httpOnly + SameSite=Lax cookie（防 XSS 读 token）；开发期经 Vite proxy 同源（Task 2）、生产静态托管同源，cookie 全程无跨源复杂度（跨源 cookie 需 SameSite=None + Secure，本地 http 浏览器拒收——这正是选 proxy 方案的原因）；Bearer 头仅保留给 CLI/脚本，不作前端主路径。**会话策略：无 refresh token，JWT 过期即 401 -> 清会话重登**（v1 从简）。自注册默认关闭，防开放注册滥用。

**Files:**
- Create: `frontend/src/features/auth/LoginPage.tsx` / `AuthContext.tsx` / `RequireAuth.tsx` / `ChangePasswordForm.tsx`
- Modify: `frontend/src/api/client.ts`（token 读写 + 401 拦截）
- Modify: `src/calliodesmo/api/app.py`（`/auth/token` 支持下发 httpOnly cookie；`POST /auth/logout` 清 cookie；`POST /auth/change-password` 自助改密）
- Modify: `src/calliodesmo/auth/service.py`（`change_password`：旧密码校验 + Argon2 重哈希）
- Modify: `src/calliodesmo/config.py`（`allow_self_register`，默认 `False`）
- Test: `frontend/src/features/auth/*.test.tsx`、`tests/test_auth_cookie_api.py`、`tests/test_change_password.py`

- [ ] **Step 1:** 登录页表单 -> `POST /auth/token` -> 存 token；凭证错误显示“用户名或密码错误”；登录后跳 `/app` 测试 -> 实现跑绿
- [ ] **Step 2:** `AuthContext`：启动拉 `/auth/me` 注入全局 `AccessContext`（clearance/permissions/scopes/team_ids/project_ids）；401/失效清会话跳登录测试 -> 实现跑绿
- [ ] **Step 3:** `RequireAuth` 守卫：无 token 跳 `/login` 并记回跳地址；登出清会话测试 -> 实现跑绿
- [ ] **Step 4:** `/auth/token` httpOnly + SameSite=Lax cookie 下发 + `/auth/logout` 清 cookie（开发期经 proxy 同源，无跨源 cookie 复杂度）；Bearer 仅 CLI/脚本用测试 -> 实现跑绿
- [ ] **Step 5:** 自注册：`allow_self_register=False` 时 `/register` 端点 404/403；开启时管理员外可注册（含 clearance 上限 INTERNAL，防越权自提）测试 -> 实现跑绿
- [ ] **Step 6:** 自助改密码：`POST /auth/change-password`（旧密码校验 + Argon2 重哈希 + 记 `action="change_password"` 审计）；设置页改密表单；改密后旧会话失效重登测试 -> 实现跑绿

**验收：**
- 登录/登出/会话失效完整；`AccessContext` 全局可用
- JWT httpOnly cookie（防 XSS）；无 refresh，过期 401 重登路径明确
- 自注册默认关、开启时防越权自提 clearance
- 用户可自助改密码（旧密码校验 + 审计 + 改密后重登）

---

### Task 4: 问答面板

**目标：** 接入 P2 `POST /query` 的问答面板：模式切换（Native/Local/Global）、`top_k` 调节、答案展示 + **来源标注高亮**（点击展开 `context_chunks`）、loading/error/empty 状态。无 `query` 权限时隐藏入口（Task 8）。

**Files:**
- Create: `frontend/src/features/qa/AskPanel.tsx`（模式 segmented control + top_k stepper + 提交）
- Create: `frontend/src/features/qa/AnswerCard.tsx`（答案 + 来源标注列表，可展开 chunk 原文）
- Create: `frontend/src/features/qa/useQuery.ts`（TanStack Query mutation 封装 `/query`）
- Test: `frontend/src/features/qa/*.test.tsx`

- [ ] **Step 1:** 模式切换（Native/Local/Global，segmented control 图标）+ `top_k` stepper；提交走 `/query`；loading 骨架测试 -> 实现跑绿
- [ ] **Step 2:** `AnswerCard`：答案文本 + 来源标注列表（`source_chunk_ids` + `context_chunks`）；点击标注展开对应 chunk 原文（证据溯源）测试 -> 实现跑绿
- [ ] **Step 3:** 状态：error（错误提示）/ empty（候选为空 -> “无可引用证据”提示，对应 P2 不编造约束）/ success 测试 -> 实现跑绿
- [ ] **Step 4:** 端到端（离线）：mock `/query` 返回带来源的答案 -> 面板渲染 + 标注点击展开测试 -> 实现跑绿

**验收：**
- 三模式 + top_k + 来源标注高亮（证据可溯源展开）
- empty 态“无可引用证据”与 P2 不编造约束一致
- loading/error 状态完备

---

### Task 5: 知识库浏览（ProfileCard / 社区导航 / 库视图）

**目标：** 个人/组织库浏览：ProfileCard 列表与详情（结构化字段 + narrative 人读区）、社区导航（level 0 实体社区 / level 1 文档社区 -> 成员实体）、实体详情（邻居子图）。库视图按 `AccessContext` scope 切换（personal/project/team）。

> [!note] ProfileCard 的 `narrative`（叙述）为 P1“仅供人读、不进检索链路”字段，UI 在详情区单独呈现并标注“概览叙述（不参与检索）”，与结构化字段（别名/职务/组织/关联人/时间跨度/证据）区分展示。
>
> [!note] **交互式子图可视化**：`EntityGraph` 非静态全图渲染，而是“从种子实体出发的局部子图，可动态调范围”——点节点展开其邻居（加入画布）、折叠则移除其邻居（保留节点本身）、滑块/步进器调展开跳数与画布节点上限。避免一次性渲染全库（可达数千节点）卡死；按需探索，想看的展开、不想看的折叠。前端图引擎用 `react-force-graph`（Canvas 渲染，百-千节点流畅）或 vis-network（沿用 `graph_html.py` 的 vis.js 生态）；后端 `GET /library/subgraph` 支持按种子+跳数+上限增量拉取。

**Files:**
- Create: `frontend/src/features/library/ProfileCardList.tsx` / `ProfileCardDetail.tsx`
- Create: `frontend/src/features/library/CommunityNav.tsx`（level tab + 成员实体列表）
- Create: `frontend/src/features/library/EntityDetail.tsx`（实体详情面板：结构化字段 + ProfileCard，承载 `EntityGraph`）
- Create: `frontend/src/features/library/EntityGraph.tsx`（交互式子图可视化：展开/折叠/调范围）
- Create: `frontend/src/features/library/useSubgraph.ts`（TanStack Query 封装 `/library/subgraph`，按种子+跳数+上限增量拉取）
- Create: `frontend/src/features/library/ScopeSwitcher.tsx`（库视图切换，按 scope）
- Modify: `src/calliodesmo/api/library.py`（新增 `GET /library/subgraph?seeds=&hops=&limit=`：按 `visible_to` 过滤的增量子图扩展，复用 `GraphStore.neighbors`）
- Modify: `src/calliodesmo/interfaces/graph_store.py`（`GraphStore` 增 `subgraph(seeds, *, hops, limit, access)` 方法，广度优先 + 节点上限截断 + 去重）
- Modify: `src/calliodesmo/providers/in_memory_graph_store.py`（实现 `subgraph`：BFS 从 seeds 出发，按 hops 扩展，累计节点达 limit 截断，返回 `SubgraphView{nodes, edges}`）
- Modify: `src/calliodesmo/api/schemas.py`（`SubgraphResponse`：nodes/edges/expanded_seeds/truncated 标记）
- Test: `frontend/src/features/library/*.test.tsx`、`tests/test_subgraph_api.py`

- [ ] **Step 1:** `ProfileCardList`（`/library/profile-cards`）+ `ProfileCardDetail`：结构化字段表格 + narrative 概览区（标注不进检索）；evidence_chunk_ids 可溯源点击测试 -> 实现跑绿
- [ ] **Step 2:** `CommunityNav`：level 0/1 tab -> 社区列表 -> 成员实体；点击实体进详情测试 -> 实现跑绿
- [ ] **Step 3:** `GraphStore.subgraph` 接口 + `InMemoryGraphStore` 实现：BFS 从 seeds 按 hops 扩展、limit 截断、去重、返回 `SubgraphView`；全程 `visible_to` 过滤（越权邻居不入子图）；`truncated` 标记是否达上限测试 -> 实现跑绿
- [ ] **Step 4:** `GET /library/subgraph?seeds=&hops=&limit=`：多种子逗号分隔、hops 默认 1、limit 默认 50（防拉爆）；`query` 守卫；返回 `SubgraphResponse`（nodes/edges/expanded_seeds/truncated）测试 -> 实现跑绿
- [ ] **Step 5:** `EntityGraph` 基础渲染：从 `EntityDetail` 传入种子实体 -> 拉 `/library/subgraph`（hops=1, limit=50）-> 图引擎渲染节点+边（Canvas，类型着色沿用 `graph_html.py` 的 `_TYPE_COLORS`）；**单击节点**在右侧/底部详情面板展示该实体结构化信息（type/description/ProfileCard/证据 chunk）测试 -> 实现跑绿
- [ ] **Step 6:** **展开（双击）**：双击节点 -> 以该节点为新种子、hops=1 增量拉子图 -> 合并入画布（去重）；被展开节点加“已展开”标记（避免重复展开）测试 -> 实现跑绿
- [ ] **Step 7:** **折叠（双击）**：双击已展开节点 -> 移除其引入的邻居（保留该节点本身 + 其他路径仍可达的节点）；折叠不破坏其他子图连通性；双击未展开节点走展开、双击已展开节点走折叠（状态切换）测试 -> 实现跑绿
- [ ] **Step 8:** **调范围**：跳数滑块（1-3，默认 1）+ 画布节点上限步进器（50/100/200/500，默认 50）；调整后按当前种子重新拉取；达上限时 UI 提示“已截断，提高上限或折叠部分节点查看更多”测试 -> 实现跑绿
- [ ] **Step 9:** `EntityDetail`：结构化字段面板（左侧）+ `EntityGraph` 画布（右侧）；从 `CommunityNav`/`ProfileCard` 点击实体进入；种子可多选（从列表勾选多个实体作为初始 seeds）测试 -> 实现跑绿
- [ ] **Step 10:** `ScopeSwitcher`：按 `AccessContext` 有权 scope 切换（personal/project/team）；无权 scope 不可选；切换后列表与子图均随 scope 过滤（子图拉取带 scope 上下文）测试 -> 实现跑绿

**验收：**
- ProfileCard 浏览含结构化字段 + narrative 人读区（区分标注）
- 社区/实体导航可用；子图按权限过滤
- **交互式子图**：从种子出发、点节点展开邻居、折叠收起、滑块调跳数与节点上限；大库不卡（按需拉取 + limit 截断）
- 库视图按 scope 切换，无权 scope 不可选

---

### Task 6: 用户与团队/项目管理 UI

**目标：** 管理员管理界面（`/admin`）：用户列表/新建/编辑（clearance 下拉、active toggle、角色分配）、团队/项目管理（新建、成员增删、项目内角色）。`manage_users` 守卫显隐入口。

**Files:**
- Create: `frontend/src/features/admin/UserManage.tsx`（列表 + 新建/编辑对话框 + 角色 multi-select）
- Create: `frontend/src/features/admin/TeamManage.tsx` / `ProjectManage.tsx`（成员增删 + 角色）
- Create: `frontend/src/features/admin/AdminNav.tsx`（仅 `manage_users` 可见）
- Test: `frontend/src/features/admin/*.test.tsx`

- [ ] **Step 1:** `AdminNav`：仅 `manage_users` 用户可见入口；无权用户看不到 `/admin` 链接（前端隐藏，后端仍守卫）测试 -> 实现跑绿
- [ ] **Step 2:** `UserManage`：列表 + 新建（`/admin/users`）+ 编辑（clearance 下拉/active toggle/角色分配）；操作后 `invalidateQueries` 刷新；错误提示测试 -> 实现跑绿
- [ ] **Step 3:** `TeamManage` / `ProjectManage`：新建 + 成员增删 + 项目内角色；审计记录由后端记（Task 1）测试 -> 实现跑绿
- [ ] **Step 4:** 越权探测：无 `manage_users` 用户直击 `/admin/users` 前端路由 + 直击后端 `/admin/users` 均 403/拦截测试 -> 实现跑绿

**验收：**
- 用户/团队/项目 CRUD UI 可用，`manage_users` 守卫
- 角色/成员管理操作后缓存失效刷新
- 越权（前端路由 + 后端端点）双重拦截

---

### Task 7: 文档社区手动管理 UI（选项 A 手动部分）

**目标：** 路线图"手动策略 展 并入 P3"的兑现：在 P1 自动派生（选项 A 自动部分）之上，提供文档社区**手动管理**——命名/打标、设 access_level、增删文档。后端扩展 `CommunityStore` 手动操作接口 + `/admin/document-communities` 端点（`manage_community` 守卫），前端构建管理 UI。merge/split 随版本能力并入 P4（见下方说明）。

> [!note] 与 P1 自动派生的关系：自动派生建 level=1 文档社区；本 Task 提供手动编辑能力（分析师命名/打标/调 access_level/增删文档）。手动编辑标记 provenance，自动重派生时不覆盖手改（复用 P1 ProfileCard 的 `locked` 思路）。完整社区版本/分支/回滚为 P4。

> [!note] merge/split 整块移至 P4：合并/拆分依赖社区版本/分支/回滚能力（P4 才落地），无 undo 不安全。本阶段 Task 7 只实现可安全重做的操作（rename/retag/access_level/增删文档）；merge/split 的 CommunityStore 接口、`/admin/document-communities` 对应端点与 UI 随 P4 版本能力一并交付，不在 P3 出现半切实现。

**Files:**
- Modify: `src/calliodesmo/interfaces/community_store.py`（`CommunityStore` 扩展手动操作：`rename` / `retag` / `set_access_level` / `add_member_doc` / `remove_member_doc`）
- Modify: `src/calliodesmo/providers/in_memory_community_store.py`（实现上述操作，手动编辑置 `metadata["manual"]=True`）
- Modify: `src/calliodesmo/ecl/community_deriver.py`（自动派生跳过 `metadata["manual"]=True` 的社区，避免覆盖手改）
- Create: `src/calliodesmo/api/admin.py` 扩展（`/admin/document-communities` GET/POST + `/admin/document-communities/{id}` PATCH 操作：rename/retag/access/add-doc/remove-doc）
- Create: `frontend/src/features/admin/DocumentCommunityManage.tsx`
- Test: `tests/test_document_community_manage_api.py`、`frontend/src/features/admin/DocumentCommunityManage.test.tsx`

**手动操作接口（`interfaces/community_store.py` 扩展）：**

```python
class CommunityStore(ABC):
    # ... 既有 upsert / list ...
    @abstractmethod
    async def rename(self, community_id: str, title: str, *, access: AccessContext) -> None: ...
    @abstractmethod
    async def set_access_level(
        self, community_id: str, level: ClearanceLevel, *, access: AccessContext
    ) -> None: ...
    @abstractmethod
    async def add_member_doc(
        self, community_id: str, doc_id: str, *, access: AccessContext, note: str = ""
    ) -> None: ...
```

- [ ] **Step 1:** `CommunityStore` 手动操作接口 + `InMemoryCommunityStore` 实现：rename/retag/set_access/add_member_doc/remove_member_doc；手动操作置 `metadata["manual"]=True`；`visible_to` 守卫测试 -> 实现跑绿
- [ ] **Step 2:** 自动派生不覆盖手改：`DocumentCommunityDeriver` 跳过 `metadata["manual"]=True` 的社区；手动命名不被重派生覆盖测试 -> 实现跑绿
- [ ] **Step 3:** `/admin/document-communities` 端点（GET 列表 + PATCH 各操作）；`manage_community` 守卫；操作记 `action="manage_community"` 审计测试 -> 实现跑绿
- [ ] **Step 4:** `DocumentCommunityManage` UI：社区命名/打标签/access_level、增删文档；`manage_community` 用户可见测试 -> 实现跑绿

**验收：**
- 文档社区手动命名/打标/access/增删文档齐全，`manage_community` 守卫
- 自动派生不覆盖手动编辑（`manual` 标记）

---

### Task 8: 角色可见性与 UI 隔离

**目标：** 三维权限（角色 RBAC + clearance + scope）在 UI 的体现与**前后端一致性**：权限驱动渲染（无权按钮隐藏/禁用、无 `query` 看不到问答入口）、clearance/scope 隔离（不可见数据不渲染）、后端为唯一真相（前端隐藏 ≠ 后端放行，受限端点全覆盖守卫）。

**Files:**
- Create: `frontend/src/auth/useAccess.ts`（`AccessContext` hook：`can(perm)` / `clearance >= level` / `hasScope`）
- Modify: `frontend/src/App.tsx`（导航按权限显隐：无 `query` 隐藏问答、无 `manage_users` 隐藏管理）
- Test: `frontend/src/auth/useAccess.test.ts`、`tests/test_permission_isolation.py`（后端参数化矩阵：每个受限端点 × analyst/reviewer/admin/匿名 × 期望状态码）

- [ ] **Step 1:** `useAccess` hook：`can(Permission)` / `clearanceAtLeast(level)` / `hasScope(scope)`；权限驱动渲染（无权组件返回 null/disabled）测试 -> 实现跑绿
- [ ] **Step 2:** clearance 隔离：低 clearance 用户浏览/问答看不到高 access_level 数据（后端 `visible_to` 已过滤，前端不渲染不存在的）；UI 无越权数据泄露测试 -> 实现跑绿
- [ ] **Step 3:** scope 隔离：库视图只列有权 scope；personal 库仅本人可见（Task 5 ScopeSwitcher 一致）测试 -> 实现跑绿
- [ ] **Step 4:** 前后端一致性：每个受限端点（`/query` `/admin/*` `/library/*`）后端权限守卫全覆盖；前端隐藏仅 UX；越权直击后端端点 -> 403（无前端 UI 也拦得住）测试 -> 实现跑绿
- [ ] **Step 5:** 权限矩阵回归：用 analyst/reviewer/admin 三角色分别走问答/浏览/管理/社区管理全流程，断言各角色可见与可操作集合符合 `DEFAULT_ROLE_PERMISSIONS` 测试 -> 实现跑绿

**验收：**
- `useAccess` 权限驱动渲染；clearance/scope 隔离在 UI 体现
- 后端为唯一真相：受限端点守卫全覆盖，越权直击 403
- analyst/reviewer/admin 三角色权限矩阵一致（与后端 `DEFAULT_ROLE_PERMISSIONS` 对齐）

---

## 前端设计与 UX 前瞻

> [!note] 用 `frontend-design` skill 构建；面向情报分析人员的操作工具。下列为设计基调，具体实现遵循 Codex 前端设计指引（lucide 图标、克制配色、工具型组件）。

- **设计基调（操作工具风格）**：情报分析平台属 SaaS/操作工具，非营销/编辑风。密集但有序的信息、可扫描可比对可重复操作；避免大 hero、装饰性卡片堆叠、营销式构图。页面以全宽带状/无框布局为主，卡片仅用于重复项/模态/框定工具。
- **配色**：克制的中性（灰阶）+ 单一功能强调色（如用于主要操作/状态）；避免单色族主导（紫/紫蓝渐变、米色/沙色、深蓝/石板、棕/橙），scan 前核对 CSS 配色。
- **图标与控件**：`lucide-react` 图标用于工具按钮（保存/导出/搜索/刷新等），tooltip 标注不熟悉图标；模式切换用 segmented control、二值用 toggle/checkbox、数值用 stepper/slider、选项集用菜单/tab、明确命令用 icon+text 按钮。
- **验证**：关键流程用 Playwright 截图（桌面 + 移动视口），核对非空白、布局不重叠、文本不溢出容器；权限矩阵三角色各跑一遍。
- **移动端**：情报分析以桌面为主，移动端保证基本可用（响应式），不优先移动体验。

---

## 依赖与风险（P3 全量）

- **前端依赖隔离**：`frontend/package.json` 与后端 Python 依赖隔离；CI 前端 job（`npm ci && npm run build && vitest`，Task 2 Step 5 落地），构建产物挂 FastAPI 静态托管。Node 版本锁定（`.nvmrc`）。
- **内存 stores 单进程**：UI 走 API，API 进程需注入内存 stores 单例（ingest/query/browse 共享）；prod 持久化随真后端（P9）。内存模式下 CLI `ingest`（独立进程）灌的数据 API 进程不可见——**演示数据统一走 Task 1 Step 8 的 `serve --seed-demo`（serve 进程内自灌），这是 P3 演示的官方路径**。Task 1 stores 依赖工厂为此预留单例。**seed 性能**：首次 `serve --seed-demo` 跑完整 ECL（含 LLM 调用）较慢，seed 产物落盘缓存（序列化为 `data/demo/seed-cache.json`），二次启动命中缓存直接加载、跳过 LLM；`data/demo/` 文档 clearance 故意拉开梯度（public/internal/confidential 各备样例），Task 8 权限矩阵回归才有覆盖。
- **P3 依赖 P2**：问答面板（Task 4）依赖 P2 `/query`。**开工前置：`codex/p2-retrieval-rag` 先合并入 main，P3 分支从合并后的 main 切出**（见头部前置条件）；UI 演示用同进程内存 stores + `serve --seed-demo`。
- **JWT 存储**：httpOnly + SameSite=Lax cookie（防 XSS 读 token）；开发期 Vite proxy 同源 + 生产静态托管同源，无跨源 cookie/CORS 复杂度。Bearer 仅 CLI/脚本。无 refresh token，过期重登。
- **自注册安全**：默认关（`allow_self_register=False`）；开启时自注册 clearance 上限 INTERNAL，防越权自提；管理员建用户为主路径。
- **越权保护（后端唯一真相）**：前端隐藏/禁用仅 UX；每个受限端点后端守卫全覆盖（`require_permission` + `visible_to`），越权直击 403。Task 8 权限矩阵回归保证前后端一致。
- **软删除与审计**：用户 deactivate 为软删除（`is_active=False`），保留审计可追溯（谁/何时/做了什么/从哪来）；不物理删除，避免级联破坏历史记录。
- **CORS / 同源**：开发期走 Vite proxy 逻辑同源，默认不需要 CORS middleware；`cors_origins` 配置保留作兜底（默认空 = 关），仅未来确有跨域客户端时开启，生产收紧为实际域名。
- **测试边界**：后端端点 + 权限守卫用 `pytest` + `httpx`（受限端点做参数化矩阵：端点 × 角色 × 期望状态码）；前端组件用 `vitest` + Testing Library；Playwright 自 Task 2 接入，关键流程（登录/问答/浏览/管理）截图随 Task 推进补齐。前端不进检索精度回归（那是 P2 harness），但权限一致性有回归测试。
- **版本协调**：前端依赖锁定（package-lock + `.nvmrc`）。React 用 19（2026 新脚手架默认；shadcn/ui 为源码拷贝、兼容性取决于 Radix primitives，Radix/TanStack Query 均已支持 19）；`react-force-graph`（依赖 three.js）的 React 19 兼容性在 **Task 2 脚手架阶段**就 spike 验证（见 Task 2 Step 1），不兼容则定 vis-network 方案——避免拖到 Task 5（10 步核心）才发现不兼容、返工换底层引擎。
- **范围外（本阶段不做）**：审计记录查看 UI（审计只记不看，查看界面随 P4 或后续阶段）；refresh token 会话续期；merge/split（按裁剪线并入 P4）；OIDC/SSO（v2 精化）。
