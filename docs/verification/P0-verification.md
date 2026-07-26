---
title: P0 验证报告（地基脚手架 + 非 Docker 部署）
type: verification-report
phase: P0
date: 2026-07-26
tags:
  - verification
related:
  - "[[docs/plans/phases/P0-scaffolding]]"
  - "[[docs/deploy/native]]"
---
# P0 验证报告（地基脚手架 + 非 Docker 部署）

> [!info] 范围
> 本文档记录 P0 阶段（仓库骨架、三维权限模型、JWT/AccessContext/审计、三抽象接口、API/CLI、非 Docker 部署）的**测试内容、技术栈、验证原理与验证过程**。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P0-scaffolding|P0 阶段任务计划]] / [[docs/deploy/native|原生部署指南]]。

## 结论

| 验证项 | 结果 | 证据来源 |
| --- | --- | --- |
| 单元/集成测试 | **33 passed / 0 failed** | `pytest -v`（见 `pytest-output.txt`）+ `.pytest_cache/v/cache/nodeids`（33 条，无 `lastfailed`） |
| 静态检查 | ruff **0 error** | `ruff check .` -> `All checks passed!` |
| 格式检查 | **46 files 一致** | `ruff format --check .` -> `46 files already formatted` |
| 引导脚本端到端 | bootstrap.ps1 -Sqlite **连续 2 次 exit 0 且幂等** | `bootstrap-evidence.txt`（含 DB 内容佐证） |
| 库内容核验 | 7 表 / 3 角色 / admin(SECRET,active) / 15 权限行 | sqlite3 直查 `data/calliodesmo-dev.db` |
| 脚本语法 | PS1（Language.Parser）/ bash（`bash -n`）**均通过** | 解析器零错误 |
| YAML 配置 | compose / CI **解析合法**（2 服务 2 卷 1 job） | `yaml.safe_load` 输出 |
| Docker 起库 | **未本机执行**（本机无 Docker） | compose 已静态校验，留待学生环境 |

## 一、测试内容

### 1.1 自动化测试矩阵（33 用例，按模块）

| 模块 | 用例数 | 验证点 |
| --- | --- | --- |
| `test_config.py` | 2 | 默认值正确；`CALLIODESMO_` 前缀环境变量可覆盖 |
| `test_db_models.py` | 3 | 7 张 P0 表注册；用户-角色-用户组写入回读；用户名唯一约束 |
| `test_security.py` | 4 | Argon2 哈希往返/错误密码拒绝；JWT 往返/过期拒签/错误密钥拒签 |
| `test_access_context.py` | 6 | clearance 有序；`can_access` 判定；角色种子幂等；认证正反例；AccessContext 聚合（权限并集/scope/组）；未知用户 |
| `test_audit.py` | 2 | 具名/匿名审计落库（动作/详情/来源/时间） |
| `test_text_loader.py` | 4 | 目录递归加载并过滤；单文件；不支持后缀；源不存在 |
| `test_embedding.py` | 2 | Hash 嵌入确定性/归一化/区分度；BGE-M3 缺依赖友好报错 |
| `test_llm_provider.py` | 2 | LiteLLM 参数映射与响应解析；可选参数缺省不传 |
| `test_api_smoke.py` | 4 | `/healthz`；登录->`/auth/me`->审计全链路；错误密码 401；无 token 401 |
| `test_cli.py` | 4 | `--version`；`db init/seed` 端到端验库；`serve` 参数透传；`serve` 默认值 |

### 1.2 自动化之外的端到端验证

| 项 | 内容 |
| --- | --- |
| 引导脚本实测 | `scripts/bootstrap.ps1 -Sqlite` 全链路跑通（uv 检查 -> uv sync -> .env -> db init -> db seed）；**连续 2 次均 exit 0 且幂等**（.env 跳过、新建角色 0 个、管理员跳过） |
| 库内容核验 | SQLite 开发库实查：7 表齐全；roles=analyst/reviewer/admin；admin clearance=SECRET/active；role_permissions=15 行（4+4+7，与 `DEFAULT_ROLE_PERMISSIONS` 一致）；user_roles=1 |
| 脚本静态校验 | PS1 经 `System.Management.Automation.Language.Parser` 零错误；bash 经 Git Bash `bash -n` 零错误 |
| 健壮性回归 | 修复 bootstrap.ps1 在 `$ErrorActionPreference='Stop'` 下被 uv 写到 stderr 的进度信息误判为终止错误的问题（`Invoke-Native` helper 内临时切 `Continue`，仅按退出码判定） |
| 编码修复 | PS1 存 **UTF-8 with BOM** 保证 Windows PowerShell 5.1 中文不乱码（无 BOM 时按 ANSI 误读） |

## 二、技术栈

### 2.1 被测系统（P0 实现）

| 层 | 技术 |
| --- | --- |
| 语言/运行时 | Python 3.12（uv 0.11.24 管理，hatchling 打包，src 布局） |
| Web | FastAPI 0.140.0 · uvicorn 0.51.0 · pydantic 2.13.4 / pydantic-settings 2.14.2 |
| CLI | Typer 0.27.0 |
| 数据 | SQLAlchemy 2.0.51（async）· asyncpg 0.31.0（Postgres）· aiosqlite 0.22.1（SQLite） |
| 认证 | PyJWT 2.13.0（HS256）· pwdlib 0.3.0 + argon2-cffi 25.1.0 |
| LLM/嵌入接口 | LiteLLM 1.90.6（钉 `>=1.85,<1.91`，>=1.93 无 Windows wheel）· FlagEmbedding（可选 extra，懒加载） |
| 基础设施 | PostgreSQL 16 + pgvector · Neo4j 5（docker-compose 或原生安装） |

### 2.2 验证工具链

| 工具 | 用途 |
| --- | --- |
| pytest 9.1.1 + pytest-asyncio 1.4.0（auto 模式） | 异步测试执行 |
| httpx 0.28.1 `ASGITransport` | 进程内 ASGI 级 API 测试（不起真实端口） |
| 内存/临时文件 SQLite | 替代 Postgres 的测试数据库 |
| Typer `CliRunner` | CLI 进程内调用与断言 |
| monkeypatch + `sys.modules` 桩 | 隔离 litellm / FlagEmbedding / uvicorn 等外部依赖 |
| Ruff 0.16.0（lint + format） | 静态检查与格式门禁（CI 同步执行） |
| GitHub Actions（`.github/workflows/ci.yml`） | 持续集成：uv sync -> ruff -> pytest |
| `System.Management.Automation.Language.Parser` / `bash -n` | 部署脚本语法校验 |
| `yaml.safe_load` | compose/CI YAML 合法性校验 |

## 三、验证原理

> [!abstract] 设计原则：快、确定、可复现、与外部环境解耦

1. **TDD 红-绿循环**：每个 Task 先写失败测试再实现（步骤见 [[docs/plans/phases/P0-scaffolding|P0 计划]]），保证测试真的在测行为而非摆设。
2. **测试隔离（Hermetic）**：
   - 数据库：每用例独立**内存 SQLite**（`sqlite+aiosqlite:///:memory:`），`Base.metadata.create_all` 建全套表——P0 表只用可移植列类型（Uuid/JSON/非原生 Enum），故 SQLite 可等价替代 Postgres 验证 ORM 与服务层逻辑；pgvector 列自 P1 才引入，届时再配 Postgres 容器测试。
   - 外部服务：`sys.modules` 注入桩模块替代 litellm（验证参数映射而不发真实请求）、FlagEmbedding（模拟未安装以验证友好报错）、uvicorn（捕获 serve 参数而不真实监听）——**离线可跑、零网络抖动**。
   - FastAPI：`app.dependency_overrides[get_session]` 把请求会话替换为测试会话，验证真实路由+依赖链。
   - 配置：`Settings(_env_file=None)` + `monkeypatch.setenv` + `get_settings.cache_clear()`，环境变量用例互不透传。
3. **行为契约优先**：接口测试（LLM/Embedding/DocumentLoader）断言**输入映射与输出结构**（如 `calls["messages"]`、向量维度/归一化），不绑定具体后端实现——六个抽象接口可插拔的前提。
4. **幂等性显式验证**：`seed_default_roles` 二次调用返回空、bootstrap 连续 2 次运行全跳过——部署类脚本必须可重复执行。
5. **端到端与静态双轨**：自动化测试覆盖代码行为；引导脚本/compose/CI 等"环境产物"用**本机实测 + 解析器校验**（Parser/bash -n/yaml.safe_load）补足，无法本机执行的（Docker 起库）如实标注边界。
6. **权限语义数学化断言**：clearance 用 `IntEnum` 有序比较（`clearance >= access_level`），权限求**角色并集**，用正/反例真值覆盖。
7. **退出码而非输出文本判定**：bootstrap 容错设计只按原生命令退出码抛错，不受进度信息走 stderr 的干扰——本轮因此修复了一个真实缺陷。

## 四、验证过程

### 4.1 复现步骤（学生机/CI 通用）

```bash
uv sync                          # 1. 安装依赖（含 dev 组）
uv run ruff format --check .     # 2. 格式门禁
uv run ruff check .              # 3. 静态检查
uv run pytest -v                 # 4. 全部 33 用例
.\scripts\bootstrap.ps1 -Sqlite  # 5.（Windows）端到端引导；Linux/macOS: scripts/bootstrap.sh --sqlite
uv run calliodesmo serve         # 6. 起 API，浏览器开 /docs，curl /healthz
```

### 4.2 实际执行记录（2026-07-26，Windows 11 + uv 0.11.24 + Python 3.12）

| 步骤 | 命令 | 结果摘录 |
| --- | --- | --- |
| 依赖安装 | `uv sync` | 130 包解析、77 安装（litellm 1.90.6 纯 wheel；>=1.93 无 Windows wheel 已钉版规避） |
| 静态检查 | `ruff check .` | `All checks passed!`（期间修复：__init__ 残留 `` `n ``、StrEnum 化、RUF001-3/B008 中文标点与 FastAPI 惯用法豁免） |
| 格式 | `ruff format --check .` | `46 files already formatted` |
| 测试 | `pytest -v` | **33 passed**（1.36s），6 条 `InsecureKeyLengthWarning`（测试短密钥所致，见§五） |
| 引导实测 | `bootstrap.ps1 -Sqlite` ×2 | 两次均 exit 0；二跑 `.env 已存在，跳过` / `新建角色 0 个` / `管理员已存在...（跳过）` |
| 库内容 | sqlite3 直查 `data/calliodesmo-dev.db` | 7 表；roles=admin/analyst/reviewer；admin(SECRET, active)；role_permissions=15；user_roles=1 |
| 脚本解析 | PSParser / `bash -n` | 双双零错误 |
| YAML | `yaml.safe_load` | compose: services=[postgres, neo4j], volumes=[pgdata, neo4jdata]；ci: jobs=[lint-and-test] |

磁盘旁证：`.pytest_cache/v/cache/nodeids` 含且仅含 33 条 nodeid，无 `lastfailed`（全绿标志）。原始证据文件存于本目录：`pytest-output.txt`、`bootstrap-evidence.txt`。

> [!note] 关于捕获文本中的乱码
> CLI 经 PowerShell 管道捕获时，其 `Write-Host`/`typer.echo` 输出的中文在控制台代码页下呈乱码（如 db init 的「数据库表已创建」），但**退出码与脚本逻辑正确**，并由 DB 内容直查独立佐证。脚本文档与运行逻辑不受影响。

### 4.3 提交锚点

| 提交 | 内容 |
| --- | --- |
| `f1d3f0c` | 仓库骨架 |
| `936a9c1` | 月/周/P0 计划文档 |
| `6ae3588` | P0 全量实现（31 测试） |
| `8de243b` | 计划进度回填 |
| `970ef25` | 非 Docker 部署（serve/bootstrap/指南，+2 测试 = 33） |
| （本次） | bootstrap.ps1 健壮性修复 + 验证文档 |

## 五、已知边界与后续

> [!warning] 如实声明
> - `docker compose up -d` 与 Postgres/Neo4j 原生安装步骤**未在本机逐一实测**（本机无 Docker/数据库服务）；compose/CI 已静态校验，原生步骤按各平台官方流程撰写。
> - 6 条 `InsecureKeyLengthWarning`：测试用短密钥（"secret"/默认 dev 密钥 < 32 字节）触发，生产须用 ≥32 字节随机串（[[docs/deploy/native|原生部署指南 §五]] 已要求）。
> - BGE-M3 真实嵌入需 `uv sync --extra embedding-local`（重依赖），P1 前另行验证。
> - P1 起新增 pgvector/Neo4j 依赖的测试需引入容器化或原生实例的集成测试层（届时更新本文档）。