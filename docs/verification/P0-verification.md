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
> 记录 P0 阶段（仓库骨架、三维权限模型、JWT/AccessContext/审计、三抽象接口、API/CLI、非 Docker 部署）的**测试内容、技术栈、验证原理与验证过程**。关联：[[docs/plans/phases/P0-scaffolding|P0 计划]] / [[docs/deploy/native|原生部署]]。

## 结论

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| 单元/集成测试 | **33 passed / 0 failed** | `pytest-output.txt` + `.pytest_cache` nodeids（33 条无 lastfailed） |
| 静态检查 | ruff **0 error** | `ruff check .` / `format --check`（46 files） |
| 引导脚本端到端 | bootstrap.ps1 -Sqlite **连续 2 次 exit 0 幂等** | `bootstrap-evidence.txt` |
| 库内容核验 | 7 表 / 3 角色 / admin(SECRET,active) / 15 权限 | sqlite3 直查 |
| Docker 起库 | 未本机执行（本机无 Docker） | compose 已静态校验 |

## 一、测试内容

**33 用例矩阵**：config(2) · db_models(3) · security(4，Argon2/JWT) · access_context(6，clearance/can_access/聚合) · audit(2) · text_loader(4) · embedding(2，Hash/BGE 缺依赖) · llm_provider(2) · api_smoke(4，/healthz + 登录链路 + 401) · cli(4)。

**自动化之外的端到端**：bootstrap.ps1 -Sqlite 全链路（uv -> sync -> .env -> init -> seed）连续 2 次幂等；PS1 经 Parser / bash 经 `bash -n` 零错误；修复 bootstrap 在 `$ErrorActionPreference='Stop'` 下误判 uv stderr 进度为终止错误（`Invoke-Native` 内切 Continue）；PS1 存 UTF-8 with BOM 防中文乱码。

## 二、技术栈

- **被测**：Python 3.12（uv 0.11.24 + hatchling src 布局）· FastAPI 0.140 + uvicorn 0.51 · pydantic 2.13/settings 2.14 · Typer 0.27 · SQLAlchemy 2.0.51（async）+ asyncpg/aiosqlite · PyJWT 2.13 + pwdlib 0.3（argon2）· LiteLLM 1.90.6（钉 `>=1.85,<1.91`）· PostgreSQL 16 + pgvector / Neo4j 5。
- **工具链**：pytest 9.1.1 + pytest-asyncio（auto）· httpx ASGITransport（进程内 ASGI）· 内存 SQLite · CliRunner · `sys.modules` 桩隔离 litellm/FlagEmbedding/uvicorn · Ruff 0.16 · GitHub Actions · PSParser/`bash -n`/`yaml.safe_load`。

## 三、验证原理

1. **TDD 红-绿**：步骤见 P0 计划，保证测试真实测行为。
2. **隔离**：每用例独立内存 SQLite（P0 表可移植列类型）；`sys.modules` 桩零网络；`dependency_overrides[get_session]` 走真实路由；`Settings(_env_file=None)` 环境变量用例互不透传。
3. **契约优先**：接口测试只断输入映射/输出结构，不绑定后端。
4. **幂等显式**：`seed_default_roles` 二次空返回、bootstrap 二次全跳过。
5. **双轨**：代码行为走自动化；环境产物（脚本/compose/CI）走实测 + 解析器校验。
6. **权限数学化**：clearance `IntEnum` 有序比较 + 权限角色并集，正反例覆盖。
7. **退出码判定**：不按 stderr 文本，修复了真实缺陷。

## 四、验证过程

```bash
uv sync && uv run ruff format --check . && uv run ruff check . && uv run pytest -v
.\scripts\bootstrap.ps1 -Sqlite   # 连续 2 次 exit 0
uv run calliodesmo serve          # /docs + curl /healthz
```

实际执行（2026-07-26，Windows 11）：`33 passed`（1.36s，6 条 InsecureKeyLengthWarning 为短测试密钥所致）；bootstrap 二跑「.env 已存在跳过 / 新建角色 0 / 管理员已存在」；SQLite 直查 7 表 / roles / role_permissions=15 / user_roles=1。

**提交锚点**：`f1d3f0c` 骨架 · `6ae3588` P0 全量（31 测试）· `970ef25` 非 Docker 部署（+2 测试 = 33）。

> [!note] 乱码说明
> CLI 经 PowerShell 管道捕获时中文输出乱码（代码页），但退出码与脚本正确，DB 内容已独立佐证。

## 五、已知边界与后续

- `docker compose up -d` 与 PG/Neo4j 原生安装步骤未本机实测（无 Docker/DB），已静态校验。
- 6 条 `InsecureKeyLengthWarning`：测试短密钥所致，生产须 ≥32 字节随机串（[[docs/deploy/native|原生部署]]）。
- BGE-M3 真实嵌入需 `--extra embedding-local`，P1 前另验。
- P1 起 pgvector/Neo4j 集成测试引入容器或原生实例层（届时更新本文档）。
