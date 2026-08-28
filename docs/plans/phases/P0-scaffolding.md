---
title: P0 地基脚手架 实施计划
type: phase-plan
phase: P0
tags:
  - plan/phase
created: 2026-07-26
---
# P0 地基脚手架 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/monthly/2026-08|2026-08 月计划]]。

**Goal:** 搭起可运行、可测试的系统地基：基础设施（Postgres+pgvector/Neo4j）、配置与密钥、三维权限模型（用户/角色/权限/用户组）+ JWT 认证 + AccessContext + 审计骨架、三大抽象接口（LLMProvider/EmbeddingProvider/DocumentLoader）及默认实现、冒烟测试与 CI。

**Architecture:** `src/` 单包 `calliodesmo`；SQLAlchemy 2.0 异步 ORM（开发/测试 SQLite，生产 Postgres，P0 不引入 Alembic，建表走 `Base.metadata.create_all`）；FastAPI 仅暴露 `/healthz` + `/auth/token` + `/auth/me`；Typer CLI 提供 `db init/seed`；接口层与默认实现分离，重依赖（FlagEmbedding）懒加载并列为可选 extra。

**Tech Stack:** Python 3.12 + uv · FastAPI · Typer · SQLAlchemy 2.0 (async) · PyJWT · pwdlib[argon2] · LiteLLM（钉 `>=1.85,<1.91`，>=1.93 无 Windows wheel）· pytest + pytest-asyncio + httpx · Ruff。

---

### Task 0: 仓库骨架（已完成）

提交 `f1d3f0c`：`pyproject.toml`(uv) / `.python-version` / `.gitignore` / `.env.example` / `docker-compose.yml` / `README.md` / `.github/workflows/ci.yml` / `src/calliodesmo/` 包结构 / `tests/`。`uv sync` 已安装 76 个包（litellm 1.90.6 纯 Python wheel）。

- [x] **Step 1:** `uv sync` 通过，`uv run python -c "import calliodesmo"` 成功
- [x] **Step 2:** 提交骨架

---

### Task 1: 配置模块（pydantic-settings）

**Files:**
- Create: `src/calliodesmo/config.py`
- Test: `tests/test_config.py`

- [x] **Step 1:** 写失败测试（`tests/test_config.py`：默认值 / `CALLIODESMO_` 环境变量覆盖）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError: calliodesmo.config`）
- [x] **Step 3:** 实现 `src/calliodesmo/config.py`（pydantic-settings，`CALLIODESMO_` 前缀 + `@lru_cache` 单例 `get_settings`）
- [x] **Step 4:** 运行确认通过（2 passed）
- [x] **Step 5:** 提交 `feat(config): pydantic-settings 配置模块（CALLIODESMO_ 前缀）`

---

### Task 2: 数据库基座（Base / 会话工厂 / 模型注册入口）

**Files:**
- Create: `src/calliodesmo/db/base.py`
- Create: `src/calliodesmo/db/session.py`
- Create: `src/calliodesmo/models.py`

- [x] **Step 1:** 实现纯骨架：`db/base.py`（声明式基类）+ `db/session.py`（异步 engine / `SessionLocal` / `get_session` 请求级依赖）+ `models.py`（集中导入全部 ORM 模型，保证 metadata 注册完整）；测试在 Task 3 随模型一起写
- [x] **Step 2:** 提交（随 Task 3 一起提交亦可）

---

### Task 3: 权限三维模型（users/roles/role_permissions/user_roles/user_groups/user_group_members）

**Files:**
- Create: `src/calliodesmo/auth/models.py`
- Test: `tests/test_db_models.py`
- Create: `tests/conftest.py`

- [x] **Step 1:** 写失败测试（`tests/conftest.py`：内存 SQLite 会话 + ASGI client 夹具；`tests/test_db_models.py`：metadata 注册 / user-role-group 往返 / 重名拒绝）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError: calliodesmo.auth.models`）
- [x] **Step 3:** 实现 `src/calliodesmo/auth/models.py`：`ClearanceLevel`（有序 IntEnum）/ `LibraryScope` / `Permission` + `DEFAULT_ROLE_PERMISSIONS` / `User`/`Role`/`RolePermission`/`UserRole`/`UserGroup`/`UserGroupMember`
- [x] **Step 4:** 运行确认通过（3 passed）
- [x] **Step 5:** 提交 `feat(auth): 三维权限模型（RBAC + clearance + scope + 用户组）`

---

### Task 4: 密码哈希与 JWT（security）

**Files:**
- Create: `src/calliodesmo/auth/security.py`
- Test: `tests/test_security.py`

- [x] **Step 1:** 写失败测试（`tests/test_security.py`：密码哈希往返 / JWT 往返 / 过期 / 错密钥）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `src/calliodesmo/auth/security.py`（pwdlib/Argon2 哈希 + PyJWT 编解码）
- [x] **Step 4:** 运行确认通过（4 passed）
- [x] **Step 5:** 提交 `feat(auth): Argon2 密码哈希与 JWT 编解码`

---

### Task 5: AccessContext 与 auth service

**Files:**
- Create: `src/calliodesmo/auth/context.py`
- Create: `src/calliodesmo/auth/service.py`
- Test: `tests/test_access_context.py`

- [x] **Step 1:** 写失败测试（clearance 有序比较 / `can_access` / seed 幂等 / authenticate / `get_access_context` 聚合权限+scope+组 / 未知用户 None）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `context.py`（frozen dataclass `AccessContext`）+ `service.py`（`create_user`/`authenticate`/`seed_default_roles`/`assign_role`/`create_group`/`add_group_member`/`get_access_context`）
- [x] **Step 4:** 运行确认通过（6 passed）
- [x] **Step 5:** 提交 `feat(auth): AccessContext 与用户/角色/用户组服务`

---

### Task 6: 审计骨架

**Files:**
- Create: `src/calliodesmo/audit/models.py`
- Create: `src/calliodesmo/audit/service.py`
- Test: `tests/test_audit.py`

- [x] **Step 1:** 写失败测试（`tests/test_audit.py`：`record_audit` 落库往返 / 匿名审计）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `audit/models.py`（`AuditLog` 表：谁/何时/做了什么/从哪来）+ `audit/service.py`（`record_audit` 统一写入入口）
- [x] **Step 4:** 运行确认通过（2 passed）
- [x] **Step 5:** 提交 `feat(audit): 审计日志表与 record_audit 骨架`

---

### Task 7: DocumentLoader 接口与默认实现

**Files:**
- Create: `src/calliodesmo/interfaces/document_loader.py`
- Create: `src/calliodesmo/providers/text_loader.py`
- Test: `tests/test_text_loader.py`

- [x] **Step 1:** 写失败测试（目录递归加载 / 单文件 / 不支持后缀 / 缺失源）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `interfaces/document_loader.py`（`LoadedDocument` + `DocumentLoader` ABC）+ `providers/text_loader.py`（`TextDocumentLoader`，.md/.txt）
- [x] **Step 4:** 运行确认通过（4 passed）
- [x] **Step 5:** 提交 `feat(providers): DocumentLoader 接口与文本加载默认实现`

---

### Task 8: EmbeddingProvider 接口与默认实现（Hash + BGE-M3）

**Files:**
- Create: `src/calliodesmo/interfaces/embedding.py`
- Create: `src/calliodesmo/providers/hash_embedding.py`
- Create: `src/calliodesmo/providers/bge_m3.py`
- Test: `tests/test_embedding.py`

- [x] **Step 1:** 写失败测试（Hash 确定性 + 单位归一化 / 缺 FlagEmbedding 友好报错）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `interfaces/embedding.py`（`EmbeddingResult` + ABC）+ `providers/hash_embedding.py`（确定性离线）+ `providers/bge_m3.py`（FlagEmbedding 懒加载，缺依赖提示 `uv sync --extra embedding-local`）
- [x] **Step 4:** 运行确认通过（2 passed）
- [x] **Step 5:** 提交 `feat(providers): EmbeddingProvider 接口与 Hash/BGE-M3 实现`

---

### Task 9: LLMProvider 接口与 LiteLLM 默认实现

**Files:**
- Create: `src/calliodesmo/interfaces/llm.py`
- Create: `src/calliodesmo/providers/litellm_provider.py`
- Test: `tests/test_llm_provider.py`

- [x] **Step 1:** 写失败测试（`sys.modules` 桩 litellm，离线可跑：参数透传 / 可选参数省略）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError`）
- [x] **Step 3:** 实现 `interfaces/llm.py`（`LLMMessage`/`LLMResponse` + ABC）+ `providers/litellm_provider.py`（延迟导入 litellm，model/key/base 透传）
- [x] **Step 4:** 运行确认通过（2 passed）
- [x] **Step 5:** 提交 `feat(providers): LLMProvider 接口与 LiteLLM 默认实现`

---

### Task 10: FastAPI 应用（/healthz + JWT 认证链路）

**Files:**
- Create: `src/calliodesmo/api/schemas.py`
- Create: `src/calliodesmo/api/deps.py`
- Create: `src/calliodesmo/api/app.py`
- Test: `tests/test_api_smoke.py`

- [x] **Step 1:** 写失败测试（/healthz / 完整认证流含审计落库 / 错密码 401 / 无 token 401）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError: calliodesmo.api.app`）
- [x] **Step 3:** 实现 `api/schemas.py`（Token/MeResponse）+ `api/deps.py`（`get_current_context`：JWT -> AccessContext）+ `api/app.py`（`create_app`：/healthz、/auth/token 且 `record_audit`、/auth/me）
- [x] **Step 4:** 运行确认通过（4 passed）
- [x] **Step 5:** 提交 `feat(api): /healthz 与 JWT 登录、/auth/me AccessContext 链路`

---

### Task 11: Typer CLI（--version / db init / db seed）

**Files:**
- Create: `src/calliodesmo/cli.py`
- Test: `tests/test_cli.py`

- [x] **Step 1:** 写失败测试（--version / db init + seed 建表、内置角色与 admin）
- [x] **Step 2:** 运行确认失败（`ModuleNotFoundError: calliodesmo.cli`）
- [x] **Step 3:** 实现 `src/calliodesmo/cli.py`（`db init` 幂等建表 / `db seed` 内置角色 + 初始管理员）
- [x] **Step 4:** 运行确认通过（2 passed）
- [x] **Step 5:** 提交 `feat(cli): Typer 入口与 db init/seed 命令`

---

### Task 12: 全量验收（Ruff + 全量测试 + compose 校验 + CI）

**Files:**
- Verify: `docker-compose.yml`、`.github/workflows/ci.yml`（Task 0 已建）

- [x] **Step 1:** `uv run ruff format .` + `uv run ruff check --fix .`（无 error，import 排序等自动修复）
- [x] **Step 2:** `uv run pytest -q` 全部通过（约 25 个用例）
- [x] **Step 3:** `docker compose config -q` 配置合法；本机有 Docker 时 `docker compose up -d` 实测起库
- [x] **Step 4:** 提交 `chore(p0): ruff 格式化与全量验收`

---

## 自查清单（写完计划后对照 roadmap 复核）

- [x] docker-compose(Postgres+pgvector/Neo4j)、配置密钥 -> Task 0/1
- [x] 三接口(LLMProvider/EmbeddingProvider/DocumentLoader)+默认实现 -> Task 7/8/9
- [x] 用户/角色/权限/用户组表 + JWT 认证 + AccessContext + 审计骨架 -> Task 3/4/5/6/10
- [x] CI + 冒烟测试 -> Task 0/10/11/12
- [x] 类型一致性：`AccessContext` 字段、`get_session` 依赖键、`DEFAULT_ROLE_PERMISSIONS` 在测试与实现间一致

## 执行方式

按用户目标 inline 顺序执行（本计划即执行脚本），每 Task 完成后勾选 checkbox 并提交。

> [!success] 执行记录（2026-07-26）
> P0 全部 12 个 Task 当日由 agent inline 执行完毕：ruff 0 error，`pytest` **31 passed**。提交：骨架 `f1d3f0c` -> 计划文档 `936a9c1` -> 全量实现 `6ae3588`（分支 `codex/p0-scaffolding`）。Task 12 Step 3 的 `docker compose up -d` 实测起库因本机未装 Docker 留待学生环境执行（compose/CI YAML 已通过解析校验）。

> [!note] 补充（2026-07-26）：无 Docker 部署路径
> 应用户要求补全非 Docker 部署：`calliodesmo serve`（uvicorn 启动 API）、`scripts/bootstrap.ps1` / `scripts/bootstrap.sh`（幂等一键引导，支持 SQLite 降级模式）、[[docs/deploy/native|原生部署指南]]（三平台 Postgres+pgvector / Neo4j 原生安装、systemd/Windows 服务、生产要点、验证清单）。

> 精简于 2026-08（文档重构）：删除嵌入代码块，保留任务/勾选结构。
