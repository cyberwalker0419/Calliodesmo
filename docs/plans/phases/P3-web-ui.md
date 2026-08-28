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

> [!important] 前置条件：P3 分支从 **P2 合并后的 main** 切出（`/query`/`get_search_engine` 需与 stores 依赖工厂共享同一实例）；MVP 裁剪线——Task 5 子图可降级为邻居列表、Task 7 merge/split 整块并入 P4；MVP 必做清单 = Task 1 全量 + 2 + 3 + 4 + 5 降级版 + 8 权限矩阵回归。

**Goal:** 启动 Web UI 并持续迭代：登录与会话、个人/组织库浏览、问答面板、用户与团队/项目管理、文档社区手动管理、角色可见性。**后端补全是 UI 前置**——补全用户/团队/项目 list/update/deactivate service 与 `/admin/*` 管理端点、`/library/*` 只读浏览端点，再在其上构建前端。UI 用 `frontend-design` skill 构建，面向情报分析人员的**操作工具风格**（密集有序、可扫描、可比对、可重复操作），而非营销/编辑风。

**Architecture:** 前端为独立 SPA（`frontend/`）与后端 FastAPI 解耦：开发期 Vite dev server（5173）经 dev proxy 把 `/api` 转发后端（8000），逻辑同源（httpOnly cookie 全程可用，无 CORS middleware）；生产期构建产物 FastAPI `StaticFiles` 静态托管（`frontend/dist`），同源免 CORS。后端沿用 `AccessContext` + 审计：`/admin/*` 需 `manage_users`/`manage_community` 守卫（403）、`/library/*` 与 P2 `/query` 需 `query` 权限；**后端为权限唯一真相**，前端隐藏/禁用仅 UX。内存 stores 单例经 FastAPI 依赖工厂共享（ingest/query/browse 同进程），prod 持久化随真后端（P9）。

**Tech Stack:**
- 前端：React 19 + Vite + TypeScript · Tailwind CSS · shadcn/ui（源码拷贝）· TanStack Query · React Router
- 构建/测试：Vite（dev）/ 产物 FastAPI 静态托管（prod）；后端 pytest + httpx（端点 + 守卫）、前端 vitest + Testing Library + Playwright（关键流程截图）

### Task 1: 管理与浏览后端补全（service + API + CLI）

**目标：** 补全延后至 P3 的管理后端：用户/团队/项目的 list/update/deactivate service、`/admin/*` 管理端点（`manage_users`/`manage_community` 守卫）、`/library/*` 只读浏览端点（`query` 守卫，接入 ProfileCardStore/CommunityStore/GraphStore）、CLI 管理命令；管理动作全程记审计。

> [!note] 现状：`auth.service` 仅有 create/assign_role/add_member/get_access_context，缺 list/update/deactivate；API 仅 `/healthz` `/auth/token` `/auth/me`；三 store 无 HTTP 端点。本 Task 是 UI（Task 2-8）的接口地基。

**Files:**
- `src/calliodesmo/auth/service.py` · `api/{admin,library,app,deps,schemas}.py`（`/admin/{users,teams,projects}` + `/library/{profile-cards,communities,entities/{name}}` + `require_permission`/三 store 单例工厂）· `cli.py`（users/teams 管理 + `serve --seed-demo`）· `data/demo/`（样例文档，clearance 拉开 public/internal/confidential 梯度）· 测试 `tests/test_{admin_api,library_api,admin_cli,serve_seed_demo}.py`

- [x] **Step 1:** `require_permission` helper：有权放行、无权 403 测试 -> 实现跑绿
- [x] **Step 2:** `list_users`/`update_user`（clearance/active）/`deactivate_user`（软删除 `is_active=False` 保留审计）+ `/admin/users`；缺 `manage_users` -> 403；记 `action="manage_user"` 审计测试 -> 实现跑绿
- [x] **Step 3:** `/admin/{teams,projects}`（list/create）+ 成员增删端点；`manage_users` 守卫 + 审计测试 -> 实现跑绿
- [x] **Step 4:** `/library/*`：profile-cards 按 `visible_to` 过滤、communities 按 level 过滤、`entities/{name}` 含 neighbors；`query` 守卫；越权记录不返回测试 -> 实现跑绿
- [x] **Step 5:** stores 依赖工厂（三 store 内存单例，与 `get_search_engine` 共享同一实例）测试 -> 实现跑绿
- [x] **Step 6:** CLI `users list/create/deactivate`、`teams create/add-member`（CliRunner 断言退出码与输出）测试 -> 实现跑绿
- [x] **Step 7:** 软删除与引用完整性：deactivate 后不可登录、历史审计保留；`get_access_context` 对 `is_active=False` 返 None 测试 -> 实现跑绿
- [x] **Step 8:** `serve --seed-demo`：serve 进程内对 `data/demo/` 跑 ECL 注入内存 stores（解决跨进程不可见）；seed 落盘缓存 `data/demo/seed-cache.json` 二次启动跳过 LLM；seed 后 `/library/profile-cards` 非空测试 -> 实现跑绿

**验收：**
- 用户/团队/项目 CRUD + 成员管理齐全、守卫 + 审计；`/library/*` 只读按 `visible_to` 过滤、`query` 守卫；CLI 可用；停用用户既有内容保留且仍按 clearance 可见（情报连续性）；`serve --seed-demo` 后浏览端点非空

### Task 2: 前端工程脚手架

**目标：** 初始化 `frontend/` SPA 工程（React + Vite + TS + Tailwind + shadcn/ui），建 API 客户端（同源 cookie 会话 + JWT 注入）、TanStack Query 配置、React Router 骨架；开发期 Vite dev proxy 同源 + 生产静态托管，前端能联通 `/healthz`。

**Files:**
- `frontend/`（package.json/vite.config.ts/tsconfig/tailwind/postcss/index.html）· `frontend/src/{api/client.ts,main.tsx,App.tsx,routes.tsx}` · `api/app.py`（StaticFiles 挂 dist + `/api` 双挂）· `config.py`（`allow_self_register` 默 False、`cors_origins` 空=关）· `.gitignore` · `frontend/playwright.config.ts` · `.github/workflows/ci.yml`（前端 job）· 测试 `frontend/src/api/client.test.ts`

- [x] **Step 1:** `frontend/` 初始化（Vite React-TS + Tailwind + shadcn/ui + `lucide-react`）；`npm run build` 产出 `dist/`；**图引擎选型 spike（前置）**：脚手架阶段即验证 `react-force-graph`（依赖 three.js）的 React 19 兼容性（最小 demo 跑通即可），不兼容定 vis-network；选型回填 Task 5 图引擎与 `SubgraphResponse` 契约测试 -> 实现跑绿
- [x] **Step 2:** `api/client.ts`：fetch wrapper 注入 Bearer、401 自动跳登录、统一错误对象；TanStack Query 配置测试 -> 实现跑绿
- [x] **Step 3:** Vite dev proxy（/api -> 8000，rewrite 去前缀，逻辑同源）+ 后端 API 双挂 `/api` 前缀 + 生产 StaticFiles（SPA fallback `index.html`）；`/healthz` 经 proxy 联通测试 -> 实现跑绿
- [x] **Step 4:** React Router 骨架（`/login` `/app/*` 占位）+ `RequireAuth` 守卫占位（Task 3 实现）测试 -> 实现跑绿
- [x] **Step 5:** Playwright 接入（`@playwright/test` + 桌面/移动视口 + 登录页冒烟截图用例）；CI 前端 job（npm ci / build / vitest）跑通测试 -> 实现跑绿

**验收：**
- `frontend/` 独立工程可 `npm run dev`（5173）与 `npm run build`；API 客户端 JWT/401 处理 + QueryClient 就绪；dev proxy 同源 + 生产静态托管、`/healthz` 联通；Playwright 冒烟可跑、CI 含前端 job

### Task 3: 登录与会话

**目标：** 登录页（`POST /auth/token`）+ 会话管理（JWT 存 httpOnly cookie 优先）+ `AccessContext` 全局注入（`GET /auth/me`）+ 受保护路由 + 登出。自注册默认关（`CALLIODESMO_ALLOW_SELF_REGISTER` 开关）。

> [!note] JWT 存 httpOnly + SameSite=Lax cookie（防 XSS）；开发经 proxy 同源、生产静态托管同源，无跨源复杂度。**无 refresh token：JWT 过期即 401 -> 清会话重登**。Bearer 仅留 CLI/脚本，不作前端主路径。自注册默认关防开放注册滥用。

**Files:**
- `frontend/src/features/auth/{LoginPage,AuthContext,RequireAuth,ChangePasswordForm}.tsx` · `api/{client.ts,app.py}`（token/cookie/logout/change-password）· `auth/service.py`（`change_password`：旧密码 + Argon2 重哈希）· `config.py` · 测试 `frontend/src/features/auth/*.test.tsx`、`tests/test_{auth_cookie_api,change_password}.py`

- [x] **Step 1:** 登录页表单 -> `/auth/token` 存 token；凭证错误显示"用户名或密码错误"；登录后跳 `/app` 测试 -> 实现跑绿
- [x] **Step 2:** `AuthContext`：启动拉 `/auth/me` 注入全局 AccessContext（clearance/permissions/scopes/team_ids/project_ids）；401 清会话跳登录测试 -> 实现跑绿
- [x] **Step 3:** `RequireAuth` 守卫：无 token 跳 `/login` 记回跳地址；登出清会话测试 -> 实现跑绿
- [x] **Step 4:** `/auth/token` httpOnly + SameSite=Lax cookie 下发 + `/auth/logout` 清 cookie；Bearer 仅 CLI/脚本测试 -> 实现跑绿
- [x] **Step 5:** 自注册：关时 `/register` 404/403；开时注册含 clearance 上限 INTERNAL（防越权自提）测试 -> 实现跑绿
- [x] **Step 6:** 自助改密：`POST /auth/change-password`（旧密码校验 + Argon2 重哈希 + 记 `action="change_password"` 审计）；设置页表单；改密后旧会话失效重登测试 -> 实现跑绿

**验收：**
- 登录/登出/会话失效完整；JWT httpOnly cookie（防 XSS）、无 refresh 过期 401 重登路径明确；自注册默认关、开启防越权自提；用户可自助改密（校验 + 审计 + 重登）

### Task 4: 问答面板

**目标：** 接入 P2 `POST /query` 的问答面板：模式切换（Native/Local/Global）、`top_k` 调节、答案展示 + **来源标注高亮**（点击展开 `context_chunks`）、loading/error/empty 状态。无 `query` 权限时隐藏入口（Task 8）。

**Files:**
- `frontend/src/features/qa/{AskPanel,AnswerCard,useQuery}.tsx` · 测试 `frontend/src/features/qa/*.test.tsx`

- [x] **Step 1:** 模式切换（segmented control 图标）+ `top_k` stepper；提交走 `/query`；loading 骨架测试 -> 实现跑绿
- [x] **Step 2:** `AnswerCard`：答案文本 + 来源标注列表（source_chunk_ids + context_chunks）；点击标注展开 chunk 原文（证据溯源）测试 -> 实现跑绿
- [x] **Step 3:** 状态：error（错误提示）/ empty（候选为空 -> "无可引用证据"，对应 P2 不编造约束）/ success 测试 -> 实现跑绿
- [x] **Step 4:** 端到端（离线）：mock `/query` 返回带来源答案 -> 面板渲染 + 标注点击展开测试 -> 实现跑绿

**验收：**
- 三模式 + top_k + 来源标注高亮（证据可溯源展开）；empty 态与 P2 不编造一致；loading/error 状态完备

### Task 5: 知识库浏览（ProfileCard / 社区导航 / 库视图）

**目标：** 个人/组织库浏览：ProfileCard 列表与详情（结构化字段 + narrative 人读区）、社区导航（level 0 实体社区 / level 1 文档社区 -> 成员实体）、实体详情（邻居子图）。库视图按 `AccessContext` scope 切换（personal/project/team）。

> [!note] ProfileCard 的 `narrative` 为 P1"仅供人读、不进检索链路"字段，UI 单独呈现并标注"概览叙述（不参与检索）"，与结构化字段区分展示。`EntityGraph` 为"从种子实体出发的局部子图、可动态调范围"：双击展开邻居（加入画布）/折叠（移除其邻居保留本身）、滑块/步进器调跳数与节点上限，避免全库渲染卡死；前端图引擎 `react-force-graph`（Canvas）或 vis-network；后端 `GET /library/subgraph` 按种子+跳数+上限增量拉取。

**Files:**
- `frontend/src/features/library/{ProfileCardList,ProfileCardDetail,CommunityNav,EntityDetail,EntityGraph,useSubgraph,ScopeSwitcher}.tsx` · `api/library.py`（新增 `GET /library/subgraph?seeds=&hops=&limit=`）· `interfaces/graph_store.py`（`subgraph` 方法）· `providers/in_memory_graph_store.py`（BFS + limit 截断 + `SubgraphView`）· `api/schemas.py`（`SubgraphResponse`）· 测试 `frontend/src/features/library/*.test.tsx`、`tests/test_subgraph_api.py`

- [x] **Step 1:** `ProfileCardList`（/library/profile-cards）+ `ProfileCardDetail`：结构化字段表格 + narrative 概览区（标注不进检索）；evidence_chunk_ids 可溯源点击测试 -> 实现跑绿
- [x] **Step 2:** `CommunityNav`：level 0/1 tab -> 社区列表 -> 成员实体；点击实体进详情测试 -> 实现跑绿
- [x] **Step 3:** `GraphStore.subgraph` 接口 + `InMemoryGraphStore` 实现：BFS 按 hops 扩展、limit 截断、去重、返 `SubgraphView`；全程 `visible_to`（越权邻居不入子图）；`truncated` 标记测试 -> 实现跑绿
- [x] **Step 4:** `GET /library/subgraph`：多种子逗号分隔、hops 默认 1、limit 默认 50（防拉爆）；`query` 守卫；返 `SubgraphResponse`（nodes/edges/expanded_seeds/truncated）测试 -> 实现跑绿
- [x] **Step 5:** `EntityGraph` 基础渲染：种子实体 -> 拉子图（hops=1, limit=50）-> 图引擎渲染节点+边（Canvas，类型着色沿用 `graph_html.py` 的 `_TYPE_COLORS`）；单击节点展示该实体结构化信息（type/description/ProfileCard/证据 chunk）测试 -> 实现跑绿
- [x] **Step 6:** **展开（双击）**：以该节点为新种子 hops=1 增量拉取合并入画布（去重）；被展开节点加"已展开"标记（避免重复展开）测试 -> 实现跑绿
- [x] **Step 7:** **折叠（双击）**：移除其引入的邻居（保留节点本身 + 其他路径仍可达节点），不破坏子图连通性；未展开走展开、已展开走折叠（状态切换）测试 -> 实现跑绿
- [x] **Step 8:** **调范围**：跳数滑块（1-3 默认 1）+ 节点上限步进器（50/100/200/500 默认 50）；调整后按当前种子重新拉取；达上限提示"已截断，提高上限或折叠部分节点"测试 -> 实现跑绿
- [x] **Step 9:** `EntityDetail`：结构化字段面板（左）+ `EntityGraph` 画布（右）；从 CommunityNav/ProfileCard 点击实体进入；种子可多选（勾选多个作为初始 seeds）测试 -> 实现跑绿
- [x] **Step 10:** `ScopeSwitcher`：按有权 scope 切换（personal/project/team）；无权不可选；切换后列表与子图均随 scope 过滤测试 -> 实现跑绿

**验收：**
- ProfileCard 含结构化字段 + narrative 人读区（区分标注）；社区/实体导航可用、子图按权限过滤；库视图按 scope 切换、无权不可选；**交互式子图**（从种子出发、点节点展开/折叠、滑块调跳数与上限）大库不卡

### Task 6: 用户与团队/项目管理 UI

**目标：** 管理员管理界面（/admin）：用户列表/新建/编辑（clearance 下拉、active toggle、角色分配）、团队/项目管理（新建、成员增删、项目内角色）。`manage_users` 守卫显隐入口。

**Files:**
- `frontend/src/features/admin/{UserManage,TeamManage,ProjectManage,AdminNav}.tsx` · 测试 `frontend/src/features/admin/*.test.tsx`

- [x] **Step 1:** `AdminNav`：仅 `manage_users` 可见；无权用户看不到 /admin 链接（前端隐藏，后端仍守卫）测试 -> 实现跑绿
- [x] **Step 2:** `UserManage`：列表 + 新建 + 编辑（clearance 下拉/active toggle/角色分配）；操作后 `invalidateQueries` 刷新；错误提示测试 -> 实现跑绿
- [x] **Step 3:** `TeamManage`/`ProjectManage`：新建 + 成员增删 + 项目内角色；审计由后端记（Task 1）测试 -> 实现跑绿
- [x] **Step 4:** 越权探测：无 `manage_users` 直击 `/admin/users` 前端路由 + 后端端点均 403/拦截测试 -> 实现跑绿

**验收：**
- 用户/团队/项目 CRUD UI 可用、`manage_users` 守卫；操作后缓存失效刷新；越权（前端路由 + 后端端点）双重拦截

### Task 7: 文档社区手动管理 UI（选项 A 手动部分）

**目标：** 在 P1 自动派生之上提供文档社区**手动管理**——命名/打标、设 access_level、增删文档。后端扩展 `CommunityStore` 手动操作接口 + `/admin/document-communities` 端点（`manage_community` 守卫），前端构建管理 UI；merge/split 随版本能力并入 P4。

> [!note] 与 P1 自动派生的关系：自动派生建 level=1 文档社区，本 Task 提供手动编辑能力；手动编辑标记 provenance，自动重派生时不覆盖手改（复用 P1 ProfileCard `locked` 思路）；完整社区版本/分支/回滚为 P4。merge/split 整块移至 P4（依赖版本/分支/回滚，无 undo 不安全），本阶段只做可安全重做的 rename/retag/access_level/增删文档，不在 P3 出现半切实现。

**Files:**
- `interfaces/community_store.py`（`rename`/`retag`/`set_access_level`/`add_member_doc`/`remove_member_doc`）· `providers/in_memory_community_store.py`（手动编辑置 `metadata["manual"]=True`）· `ecl/community_deriver.py`（跳过 manual 社区）· `api/admin.py` 扩展（`/admin/document-communities` GET/POST + PATCH）· `frontend/src/features/admin/DocumentCommunityManage.tsx` · 测试 `tests/test_document_community_manage_api.py`、`frontend/src/features/admin/DocumentCommunityManage.test.tsx`

- [x] **Step 1:** `CommunityStore` 手动接口 + `InMemoryCommunityStore` 实现：rename/retag/set_access/add/remove_member_doc；置 `metadata["manual"]=True`；`visible_to` 守卫测试 -> 实现跑绿
- [x] **Step 2:** 自动派生不覆盖手改：`DocumentCommunityDeriver` 跳过 `metadata["manual"]=True` 社区；手动命名不被重派生覆盖测试 -> 实现跑绿
- [x] **Step 3:** `/admin/document-communities` 端点（GET 列表 + PATCH 各操作）；`manage_community` 守卫；记 `action="manage_community"` 审计测试 -> 实现跑绿
- [x] **Step 4:** `DocumentCommunityManage` UI：社区命名/打标签/access_level、增删文档；`manage_community` 用户可见测试 -> 实现跑绿

**验收：**
- 手动命名/打标/access/增删文档齐全、`manage_community` 守卫；自动派生不覆盖手动编辑（`manual` 标记）

### Task 8: 角色可见性与 UI 隔离

**目标：** 三维权限（角色 RBAC + clearance + scope）在 UI 的体现与**前后端一致性**：权限驱动渲染（无权按钮隐藏/禁用、无 `query` 看不到问答入口）、clearance/scope 隔离（不可见数据不渲染）、后端为唯一真相（受限端点全覆盖守卫）。

**Files:**
- `frontend/src/auth/useAccess.ts`（`can(perm)`/`clearance >= level`/`hasScope`）· `frontend/src/App.tsx`（导航按权限显隐）· 测试 `frontend/src/auth/useAccess.test.ts`、`tests/test_permission_isolation.py`（参数化矩阵：受限端点 × analyst/reviewer/admin/匿名 × 期望状态码）

- [x] **Step 1:** `useAccess` hook：can/clearanceAtLeast/hasScope；权限驱动渲染（无权组件返 null/disabled）测试 -> 实现跑绿
- [x] **Step 2:** clearance 隔离：低 clearance 用户浏览/问答看不到高 access_level 数据（后端 `visible_to` 已过滤，前端不渲染不存在的）；UI 无越权数据泄露测试 -> 实现跑绿
- [x] **Step 3:** scope 隔离：库视图只列有权 scope；personal 库仅本人可见（与 Task 5 ScopeSwitcher 一致）测试 -> 实现跑绿
- [x] **Step 4:** 前后端一致性：每个受限端点（/query /admin/* /library/*）后端守卫全覆盖；前端隐藏仅 UX；越权直击后端端点 -> 403 测试 -> 实现跑绿
- [x] **Step 5:** 权限矩阵回归：analyst/reviewer/admin 三角色分别走问答/浏览/管理/社区管理全流程，断言可见与可操作集合符合 `DEFAULT_ROLE_PERMISSIONS` 测试 -> 实现跑绿

**验收：**
- `useAccess` 权限驱动渲染；clearance/scope 隔离在 UI 体现；后端为唯一真相（守卫全覆盖、越权 403）；三角色权限矩阵与 `DEFAULT_ROLE_PERMISSIONS` 对齐

## 前端设计与 UX 前瞻

- **设计基调/配色（`frontend-design` skill，操作工具风格）**：密集但有序、可扫描可比对可重复操作；避免大 hero/装饰卡片/营销式构图；全宽带状/无框布局为主；克制中性（灰阶）+ 单一功能强调色，避免单色族主导（紫/紫蓝渐变、米色/沙色、深蓝/石板、棕/橙），scan 前核对 CSS 配色
- **图标与控件**：`lucide-react` 工具按钮（tooltip 标注）；segmented control / toggle/checkbox / stepper/slider / 菜单/tab / icon+text 按语义选用
- **验证与移动端**：关键流程 Playwright 截图（桌面 + 移动视口）核对非空白、不重叠、不溢出 + 权限矩阵三角色各跑一遍；情报分析以桌面为主，移动端保证基本可用（响应式）

## 依赖与风险（P3 全量）

- **前端依赖隔离与版本协调**：`frontend/package.json` 与后端 Python 依赖隔离；CI 前端 job（npm ci + build + vitest）；Node 锁 `.nvmrc`；React 19（shadcn/ui 源码拷贝、Radix/TanStack Query 均支持 19）；`react-force-graph`（依赖 three.js）React 19 兼容性在 **Task 2 阶段 spike**，不兼容定 vis-network——避免拖到 Task 5 返工
- **内存 stores 单进程 / P3 依赖 P2**：UI 走 API，API 进程注入内存 stores 单例（ingest/query/browse 共享）；CLI `ingest`（独立进程）数据 API 不可见——演示统一走 `serve --seed-demo`（serve 内自灌）官方路径，seed 缓存 `data/demo/seed-cache.json` 二次启动跳过 LLM，文档 clearance 拉开梯度供权限矩阵回归；问答面板（Task 4）依赖 P2 `/query`，开工前置 `codex/p2-retrieval-rag` 先合并 main、P3 分支从合并后 main 切出（见头部）
- **JWT 与自注册**：httpOnly + SameSite=Lax（防 XSS）；开发/prod 均同源无跨源 CORS 复杂度；Bearer 仅 CLI/脚本；无 refresh token 过期重登；自注册默认关（`allow_self_register=False`）、开时 clearance 上限 INTERNAL 防自提，管理员建用户为主路径
- **越权保护与审计**：前端隐藏/禁用仅 UX；`require_permission` + `visible_to` 全覆盖、越权直击 403（Task 8 权限矩阵回归保证前后端一致）；deactivate 为软删除（`is_active=False`）保留审计（谁/何时/做了什么/从哪来），不物理删除避免级联破坏历史
- **CORS / 测试边界 / 范围外**：开发走 Vite proxy 逻辑同源默认不需 CORS（`cors_origins` 保留兜底、默认空=关）；后端端点+守卫 pytest + httpx 参数化矩阵（端点 × 角色 × 期望状态码）、前端 vitest + Testing Library、Playwright 截图随 Task 补齐，前端不进 P2 检索精度回归但权限一致性有回归测试；本阶段不做审计记录查看 UI（只记不看）、refresh token 会话续期、merge/split（并入 P4）、OIDC/SSO（v2 精化）

> 精简于 2026-08（文档重构）：删除嵌入代码块，保留任务/勾选结构。
