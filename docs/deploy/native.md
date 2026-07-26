---
title: 原生部署指南（无 Docker）
type: guide
tags:
  - deploy
created: 2026-07-26
---
# 原生部署指南（无 Docker）

> [!info] 适用场景
> 本机/服务器不装 Docker 时的完整部署路径。应用层（API + CLI）本来就不进容器，经 uv 本地运行；需要原生安装的是两个基础设施：**PostgreSQL 16 + pgvector**（情景层）与 **Neo4j Community**（语义层）。Docker 路径见根目录 `docker-compose.yml`。关联：[[docs/plans/roadmap|年计划]]。

## 组件与原生替代总览

| 组件 | Docker 路径 | 原生替代 |
| --- | --- | --- |
| 应用（FastAPI + Typer CLI） | 无（始终本地运行） | uv + Python 3.12（三平台通用） |
| PostgreSQL 16 + pgvector | `pgvector/pgvector:pg16` | 系统包管理器 / 安装器 + pgvector 扩展 |
| Neo4j Community | `neo4j:5` | 官方 zip/tar 解压 + Java 17+ |

## 一、应用层（三平台通用）

前置：安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)（自动准备 Python 3.12）。

```bash
uv sync                      # 安装依赖
cp .env.example .env         # Windows: copy .env.example .env；按需改密钥与连接串
uv run calliodesmo db init   # 建表
uv run calliodesmo db seed   # 内置角色/权限 + 初始管理员（先设 CALLIODESMO_ADMIN_PASSWORD）
uv run calliodesmo serve --reload   # 启动 API：http://127.0.0.1:8000/healthz 与 /docs
```

或一键引导（幂等，重复执行安全）：

```powershell
# Windows
.\scripts\bootstrap.ps1
.\scripts\bootstrap.ps1 -Sqlite    # 零依赖开发模式
```

```bash
# Linux / macOS
scripts/bootstrap.sh
scripts/bootstrap.sh --sqlite      # 零依赖开发模式
```

> [!example] 冒烟验证
> ```bash
> curl http://127.0.0.1:8000/healthz
> # {"status":"ok","version":"0.1.0"}
> curl -X POST http://127.0.0.1:8000/auth/token -d "username=admin&password=<管理员密码>"
> # {"access_token":"...","token_type":"bearer"}
> curl http://127.0.0.1:8000/auth/me -H "Authorization: Bearer <token>"
> ```

## 二、PostgreSQL 16 + pgvector 原生安装

### Ubuntu / Debian（推荐，最省心）

```bash
# PGDG 官方源
sudo apt install wget ca-certificates
wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo tee /etc/apt/trusted.gpg.d/pgdg.asc
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install postgresql-16 postgresql-16-pgvector   # pgvector 官方包
sudo systemctl enable --now postgresql

# 建库建用户（与 .env 默认连接串一致）
sudo -u postgres psql -c "CREATE USER calliodesmo WITH PASSWORD 'calliodesmo';"
sudo -u postgres psql -c "CREATE DATABASE calliodesmo OWNER calliodesmo;"
sudo -u postgres psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### macOS

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
createuser calliodesmo -P          # 输入密码 calliodesmo
createdb calliodesmo -O calliodesmo
psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Windows

1. PostgreSQL 16：EDB 图形安装器，或 `winget install PostgreSQL.PostgreSQL.16`。
2. pgvector：**无官方 Windows 预编译包**，需 Visual Studio Build Tools（C++ 工作负载）后从源码编译：

```powershell
# x64 Native Tools 命令行中执行（需 pg_config 在 PATH）
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
# 随后在 psql 中：CREATE EXTENSION IF NOT EXISTS vector;
```

> [!warning] 退而求其次
> Windows 上编译 pgvector 对学生机门槛较高。**P0 阶段可先用 SQLite 开发模式（见第四节）**；到 P1/P2 需要向量与图库时，再选：本机编译 pgvector、装 Docker Desktop、或把 Postgres/Neo4j 部署到一台 Linux 机器/云主机后改 `.env` 连接串（应用层无感）。

## 三、Neo4j Community 原生安装

前置：**Java 17+**（如 Temurin：`winget install EclipseAdoptium.Temurin.21.JRE` / `brew install temurin` / `sudo apt install temurin-21-jre`）。

```powershell
# Windows：下载 community zip 解压后
bin\neo4j.bat console                 # 前台运行（开发推荐）
bin\neo4j.bat windows-service install # 注册为 Windows 服务
bin\neo4j.bat start
```

```bash
# Linux / macOS：下载 community tar 解压后
bin/neo4j console     # 前台运行
bin/neo4j start       # 后台运行
```

首次访问浏览器 `http://localhost:7474`，初始账号 `neo4j` / `neo4j` 强制改密；把新密码写进 `.env` 的 `CALLIODESMO_NEO4J_PASSWORD`。

> [!note] Linux systemd 单元（可选）
> ```ini
> # /etc/systemd/system/neo4j.service
> [Unit]
> Description=Neo4j Graph Database
> After=network.target
>
> [Service]
> Type=forking
> ExecStart=/opt/neo4j/bin/neo4j start
> ExecStop=/opt/neo4j/bin/neo4j stop
> Restart=on-failure
>
> [Install]
> WantedBy=multi-user.target
> ```
> `sudo systemctl enable --now neo4j`

## 四、SQLite 开发模式（零依赖降级）

```bash
# 一键：scripts/bootstrap.ps1 -Sqlite 或 scripts/bootstrap.sh --sqlite
# 手动：
export CALLIODESMO_DATABASE_URL='sqlite+aiosqlite:///./data/calliodesmo-dev.db'  # Windows: $env:CALLIODESMO_DATABASE_URL='...'
uv run calliodesmo db init && uv run calliodesmo db seed
```

> [!warning] 能力边界
> 可用：P0 全部（认证/权限/审计/CLI/API）、测试套件。
> 不可用：**pgvector 向量检索（P2 起）** 与 **Neo4j 语义层建图（P1 起）**——届时必须切到原生或 Docker 的 Postgres/Neo4j。测试套件本身用内存 SQLite，不受影响。

## 五、生产部署要点（原生）

- 进程管理：Linux 用 systemd 托管 `uv run calliodesmo serve --host 127.0.0.1 --port 8000`（uvicorn 可加 `--workers`）；Windows 用 NSSM 或任务计划。
- 反向代理：Nginx/Caddy 终结 TLS，转发到 127.0.0.1:8000。
- 密钥：`CALLIODESMO_JWT_SECRET_KEY` 用 ≥32 字节随机串；`.env` 权限 600，绝不入库（.gitignore 已覆盖）。
- 备份：`pg_dump`（Postgres）+ `neo4j-admin database dump`（Neo4j）。
- 升级：`uv sync --upgrade-package <pkg>` 后跑 `uv run pytest` 回归。

## 验证清单

- [ ] `uv run pytest` 全绿
- [ ] `uv run calliodesmo db init && uv run calliodesmo db seed` 成功
- [ ] `uv run calliodesmo serve` 后 `/healthz` 返回 ok
- [ ] `/auth/token` 拿到 JWT，`/auth/me` 返回 AccessContext JSON
- [ ] Postgres 中 `SELECT * FROM roles;` 有 analyst/reviewer/admin；`audit_logs` 有 login 记录
- [ ] Neo4j 浏览器可登录（P1 建图前的连通性确认）