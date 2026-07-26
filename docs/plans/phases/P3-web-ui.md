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

**Goal:** 启动 Web UI 并持续迭代：登录与会话、个人/组织库浏览、问答面板、用户与团队/项目管理、文档社区手动管理、角色可见性。**后端补全是 UI 的前置**——兑现路线图“用户/用户组管理 CRUD 延后至 P3 落地，service/CLI/API 管理端点同步补全”：补全用户/团队/项目的 list/update/deactivate service 与 `/admin/*` 管理端点、`/library/*` 只读浏览端点，再在其上构建前端。UI 用 `frontend-design` skill 构建，面向情报分析人员的**操作工具风格**（密集有序、可扫描、可比对、可重复操作），而非营销/编辑风。

**Architecture:** 前端为独立 SPA（`frontend/` 目录，与 `src/` 平级），与后端 FastAPI 解耦。开发期 Vite dev server（5173）+ FastAPI（8000）+ CORS；生产期前端构建产物由 FastAPI 静态托管（`StaticFiles` 挂 `frontend/dist`），同源免 CORS。后端沿用 P0/P1 的 `AccessContext` 依赖与审计：管理端点 `/admin/*` 需 `manage_users` / `manage_community` 权限守卫（403），浏览端点 `/library/*` 与 P2 `/query` 需 `query` 权限；**后端为权限唯一真相**，前端隐藏/禁用仅 UX。stores 注入：内存 stores 单例经 FastAPI 依赖工厂共享（ingest/query/browse 同进程），prod 持久化随真后端（P9）。

**Tech Stack:**
- 前端：React 18 + Vite + TypeScript · Tailwind CSS · shadcn/ui（Radix primitives + `lucide-react` 图标）· TanStack Query（数据获取/缓存/失效）· React Router（路由 + 受保护路由）
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
- Modify: `src/calliodesmo/cli.py`（`users list/create/deactivate`、`teams create/add-member`）
- Test: `tests/test_admin_api.py`、`tests/test_library_api.py`、`tests/test_admin_cli.py`

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

**验收：**
- 用户/团队/项目 CRUD + 成员管理齐全，`manage_users` / `manage_community` 守卫，管理动作记审计
- `/library/*` 只读浏览端点按 `visible_to` 过滤、`query` 守卫
- CLI 管理 + 浏览命令可用；软删除保留审计可追溯

---

### Task 2: 前端工程脚手架

**目标：** 初始化 `frontend/` SPA 工程（React + Vite + TS + Tailwind + shadcn/ui），建 API 客户端（JWT 注入）、TanStack Query 配置、React Router 骨架；后端配 CORS（开发）+ 静态托管（生产），前端能联通 `/healthz`。

**Files:**
- Create: `frontend/`（`package.json` / `vite.config.ts` / `tsconfig.json` / `tailwind.config.ts` / `postcss.config.js` / `index.html`）
- Create: `frontend/src/api/client.ts`（fetch wrapper + `Authorization: Bearer` 注入 + 统一错误处理）
- Create: `frontend/src/main.tsx` / `App.tsx`（QueryClientProvider + RouterProvider）
- Create: `frontend/src/routes.tsx`（路由表 + 受保护路由占位）
- Modify: `src/calliodesmo/api/app.py`（CORS middleware + `StaticFiles` 挂 `frontend/dist`，生产同源）
- Modify: `src/calliodesmo/config.py`（`cors_origins: list[str]`，默认 `["http://localhost:5173"]`；`allow_self_register: bool = False`）
- Modify: `.gitignore`（`frontend/node_modules/` `frontend/dist/`）
- Test: `frontend/src/api/client.test.ts`（Vitest）

- [ ] **Step 1:** `frontend/` 初始化（Vite React-TS 模板 + Tailwind + shadcn/ui CLI 接入 + `lucide-react`）；`npm run build` 产出 `dist/` 测试（构建通过）
- [ ] **Step 2:** `api/client.ts`：`fetch` wrapper 注入 Bearer、401 自动跳登录、统一错误对象；TanStack Query `QueryClient` 配置测试 -> 实现跑绿
- [ ] **Step 3:** 后端 CORS（开发期放行 5173）+ 生产 `StaticFiles` 挂 `frontend/dist`（SPA fallback 到 `index.html`）；`/healthz` 联通测试 -> 实现跑绿
- [ ] **Step 4:** React Router 骨架（`/login` `/app/*` 占位）+ `RequireAuth` 守卫占位（Task 3 实现）测试 -> 实现跑绿

**验收：**
- `frontend/` 独立工程可 `npm run dev`（5173）与 `npm run build`
- API 客户端注入 JWT、401 处理；TanStack Query 配置就绪
- 后端开发 CORS + 生产静态托管；`/healthz` 前端可联通

---

### Task 3: 登录与会话

**目标：** 登录页（`POST /auth/token`）+ 会话管理（JWT 存 httpOnly cookie 优先）+ `AccessContext` 全局注入（`GET /auth/me`）+ 受保护路由 + 登出。自注册默认关（管理员建用户为主，`CALLIODESMO_ALLOW_SELF_REGISTER` 开关）。

> [!note] JWT 存储：优先 httpOnly + SameSite cookie（防 XSS 读 token）；localStorage 次选（简单但有 XSS 暴露风险）。同源部署（Task 2 静态托管）下 cookie 方案无 CORS 复杂度。自注册默认关闭，防开放注册滥用。

**Files:**
- Create: `frontend/src/features/auth/LoginPage.tsx` / `AuthContext.tsx` / `RequireAuth.tsx`
- Modify: `frontend/src/api/client.ts`（token 读写 + 401 拦截）
- Modify: `src/calliodesmo/api/app.py`（`/auth/token` 支持下发 httpOnly cookie；`POST /auth/logout` 清 cookie）
- Modify: `src/calliodesmo/config.py`（`allow_self_register`，默认 `False`）
- Test: `frontend/src/features/auth/*.test.tsx`、`tests/test_auth_cookie_api.py`

- [ ] **Step 1:** 登录页表单 -> `POST /auth/token` -> 存 token；凭证错误显示“用户名或密码错误”；登录后跳 `/app` 测试 -> 实现跑绿
- [ ] **Step 2:** `AuthContext`：启动拉 `/auth/me` 注入全局 `AccessContext`（clearance/permissions/scopes/team_ids/project_ids）；401/失效清会话跳登录测试 -> 实现跑绿
- [ ] **Step 3:** `RequireAuth` 守卫：无 token 跳 `/login` 并记回跳地址；登出清会话测试 -> 实现跑绿
- [ ] **Step 4:** `/auth/token` httpOnly + SameSite cookie 下发 + `/auth/logout` 清 cookie；cookie 与 Bearer 双支持（开发期兼容）测试 -> 实现跑绿
- [ ] **Step 5:** 自注册：`allow_self_register=False` 时 `/register` 端点 404/403；开启时管理员外可注册（含 clearance 上限 INTERNAL，防越权自提）测试 -> 实现跑绿

**验收：**
- 登录/登出/会话失效完整；`AccessContext` 全局可用
- JWT httpOnly cookie（防 XSS）+ Bearer 兼容
- 自注册默认关、开启时防越权自提 clearance

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

**Files:**
- Create: `frontend/src/features/library/ProfileCardList.tsx` / `ProfileCardDetail.tsx`
- Create: `frontend/src/features/library/CommunityNav.tsx`（level tab + 成员实体列表）
- Create: `frontend/src/features/library/EntityDetail.tsx`（实体 + neighbors 子图可视化）
- Create: `frontend/src/features/library/ScopeSwitcher.tsx`（库视图切换，按 scope）
- Test: `frontend/src/features/library/*.test.tsx`

- [ ] **Step 1:** `ProfileCardList`（`/library/profile-cards`）+ `ProfileCardDetail`：结构化字段表格 + narrative 概览区（标注不进检索）；evidence_chunk_ids 可溯源点击测试 -> 实现跑绿
- [ ] **Step 2:** `CommunityNav`：level 0/1 tab -> 社区列表 -> 成员实体；点击实体进详情测试 -> 实现跑绿
- [ ] **Step 3:** `EntityDetail`：实体 + neighbors 子图（轻量图视图）；越权邻居后端已过滤不出现测试 -> 实现跑绿
- [ ] **Step 4:** `ScopeSwitcher`：按 `AccessContext` 有权 scope 切换（personal/project/team）；无权 scope 不可选；切换后列表随 scope 过滤测试 -> 实现跑绿

**验收：**
- ProfileCard 浏览含结构化字段 + narrative 人读区（区分标注）
- 社区/实体导航可用；邻居子图按权限过滤
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

**目标：** 路线图“手动策略 展 并入 P3”的兑现：在 P1 自动派生（选项 A 自动部分）之上，提供文档社区**手动管理**——命名/打标、设 access_level、合并/拆分、增删文档。后端扩展 `CommunityStore` 手动操作接口 + `/admin/document-communities` 端点（`manage_community` 守卫），前端构建管理 UI。

> [!note] 与 P1 自动派生的关系：自动派生建 level=1 文档社区；本 Task 提供手动编辑能力（分析师命名/打标/调 access_level/合并/拆分/增删文档）。手动编辑标记 provenance，自动重派生时不覆盖手改（复用 P1 ProfileCard 的 `locked` 思路）。完整社区版本/分支/回滚为 P4。

**Files:**
- Modify: `src/calliodesmo/interfaces/community_store.py`（`CommunityStore` 扩展手动操作：`rename` / `retag` / `set_access_level` / `add_member_doc` / `remove_member_doc` / `merge_communities` / `split_community`）
- Modify: `src/calliodesmo/providers/in_memory_community_store.py`（实现上述操作，手动编辑置 `metadata["manual"]=True`）
- Modify: `src/calliodesmo/ecl/community_deriver.py`（自动派生跳过 `metadata["manual"]=True` 的社区，避免覆盖手改）
- Create: `src/calliodesmo/api/admin.py` 扩展（`/admin/document-communities` GET/POST + `/admin/document-communities/{id}` PATCH 操作：rename/retag/access/merge/split/add-doc/remove-doc）
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
    @abstractmethod
    async def merge_communities(
        self, source_id: str, target_id: str, *, access: AccessContext
    ) -> None: ...
    @abstractmethod
    async def split_community(
        self, community_id: str, member_doc_ids: list[str], *, access: AccessContext
    ) -> str: ...
```

- [ ] **Step 1:** `CommunityStore` 手动操作接口 + `InMemoryCommunityStore` 实现：rename/retag/set_access/add_member_doc/remove_member_doc/merge/split；手动操作置 `metadata["manual"]=True`；`visible_to` 守卫测试 -> 实现跑绿
- [ ] **Step 2:** 自动派生不覆盖手改：`DocumentCommunityDeriver` 跳过 `metadata["manual"]=True` 的社区；手动命名不被重派生覆盖测试 -> 实现跑绿
- [ ] **Step 3:** `/admin/document-communities` 端点（GET 列表 + PATCH 各操作）；`manage_community` 守卫；操作记 `action="manage_community"` 审计测试 -> 实现跑绿
- [ ] **Step 4:** `DocumentCommunityManage` UI：社区命名/打标签/access_level、合并（选源+目标）、拆分（选成员文档）、增删文档；`manage_community` 用户可见测试 -> 实现跑绿
- [ ] **Step 5:** merge/split 语义：merge 合并成员实体与文档、保留来源；split 按文档集合新建社区；幂等可重复测试 -> 实现跑绿

**验收：**
- 文档社区手动命名/打标/access/合并/拆分/增删文档齐全，`manage_community` 守卫
- 自动派生不覆盖手动编辑（`manual` 标记）
- merge/split 语义正确、幂等可重复；操作记审计

---

### Task 8: 角色可见性与 UI 隔离

**目标：** 三维权限（角色 RBAC + clearance + scope）在 UI 的体现与**前后端一致性**：权限驱动渲染（无权按钮隐藏/禁用、无 `query` 看不到问答入口）、clearance/scope 隔离（不可见数据不渲染）、后端为唯一真相（前端隐藏 ≠ 后端放行，受限端点全覆盖守卫）。

**Files:**
- Create: `frontend/src/auth/useAccess.ts`（`AccessContext` hook：`can(perm)` / `clearance >= level` / `hasScope`）
- Modify: `frontend/src/App.tsx`（导航按权限显隐：无 `query` 隐藏问答、无 `manage_users` 隐藏管理）
- Test: `frontend/src/auth/useAccess.test.ts`、`tests/test_permission_isolation.py`（前后端一致性）

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

- **前端依赖隔离**：`frontend/package.json` 与后端 Python 依赖隔离；CI 加 node 构建（`npm ci && npm run build`），构建产物挂 FastAPI 静态托管。Node 版本锁定（`.nvmrc`）。
- **内存 stores 单进程**：UI 走 API，API 进程需注入内存 stores 单例（ingest/query/browse 共享）；prod 持久化随真后端（P9）。P3 演示需同进程：`calliodesmo ingest` 与 `serve` 在内存模式下需同进程注入（或等待真后端接入）。Task 1 stores 依赖工厂为此预留单例。
- **P3 依赖 P2**：问答面板（Task 4）依赖 P2 `/query`；若 P2 未接入真后端，UI 演示用同进程内存 stores。P3 与 P2 可并行推进，Task 4 在 P2 `/query` 就绪后接。
- **JWT 存储**：优先 httpOnly + SameSite cookie（防 XSS 读 token）；同源部署（Task 2 静态托管）下无 CORS/cookie 复杂度。localStorage 次选（简单但 XSS 暴露），仅开发期兼容。
- **自注册安全**：默认关（`allow_self_register=False`）；开启时自注册 clearance 上限 INTERNAL，防越权自提；管理员建用户为主路径。
- **越权保护（后端唯一真相）**：前端隐藏/禁用仅 UX；每个受限端点后端守卫全覆盖（`require_permission` + `visible_to`），越权直击 403。Task 8 权限矩阵回归保证前后端一致。
- **软删除与审计**：用户 deactivate 为软删除（`is_active=False`），保留审计可追溯（谁/何时/做了什么/从哪来）；不物理删除，避免级联破坏历史记录。
- **CORS / 同源**：开发期 CORS 放行 Vite 5173；生产同源静态托管免 CORS。`cors_origins` 可配，生产收紧为实际域名。
- **测试边界**：后端端点 + 权限守卫用 `pytest` + `httpx`；前端组件用 `vitest` + Testing Library；关键流程用 Playwright 截图。前端不进检索精度回归（那是 P2 harness），但权限一致性有回归测试。
- **版本协调**：前端依赖锁定（package-lock）；引入 shadcn/ui/TanStack Query 等时注意 React 18 主版本兼容。
