---
title: 原生部署指南（测试 / 生产）
type: guide
tags:
  - deploy
created: 2026-07-26
---
# 原生部署指南

> [!info] 两种部署模式
> - **测试 / 开发部署**：SQLite + 离线桩模型（`test/stub` + `hash` + `none`），零基础设施、几分钟拉起，用于跑测试套件与本地冒烟。见第二部分。
> - **生产部署**：PostgreSQL+pgvector / Neo4j + 真实模型（云端或自建），按步骤完整部署。见第三部分。
>
> 一键 Docker 全栈见根目录 `docker-compose.yml` + `Dockerfile`。关联：[[docs/plans/roadmap|年计划]]。

## 0. 组件与选型

| 组件 | 作用 | 测试/开发 | 生产 |
| --- | --- | --- | --- |
| 应用（FastAPI + CLI） | API / Web UI / CLI | uv + Python 3.12 | 同左 |
| 情景层 DB | 文本块 + 向量 | SQLite（内存 stores 降级） | PostgreSQL 16 + pgvector |
| 语义层 | 实体关系图 | 内存 GraphStore | Neo4j Community |
| 摘要层 | 社区摘要 | 内存 CommunityStore | PostgreSQL |
| LLM | 抽取 / 摘要 / 合成 | `test/stub` 离线桩 | 云端 / 本地 / 远端 HTTP |
| 嵌入 | 向量化 | `hash` 桩 | 本地 BGE-M3 / 远端 HTTP |
| 重排 | 交叉编码器重排 | `none` 保序降级 | 本地 BGE / 远端 HTTP |

> 三层模型（LLM / 嵌入 / 重排）**独立配置**，可分别选本地或远端，互不耦合。

---

# 第一部分　基础准备（两种模式共用）

## 1. 安装 uv（Python 3.12）

[uv](https://docs.astral.sh/uv/getting-started/installation/) 自动准备 Python 3.12，无需预装 Python。

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

验证：`uv --version`。

## 2. 获取代码与安装依赖

```bash
git clone <repo-url> calliodesmo && cd calliodesmo
uv sync                       # 核心依赖（含 dev 组）
```

可选 extras（按需启用，缺时懒加载报错并提示安装命令）：

| extra | 作用 | 命令 |
| --- | --- | --- |
| `embedding-local` | 本地 BGE-M3 嵌入 | `uv sync --extra embedding-local` |
| `search-rerank` | 本地 bge-reranker-v2-m3 重排 | `uv sync --extra search-rerank` |
| `documents-pdf` | PDF 加载（pypdf） | `uv sync --extra documents-pdf` |
| `documents-office` | Word/Excel/PPT（python-docx…） | `uv sync --extra documents-office` |
| `documents-opendocument` | ODF（odfpy） | `uv sync --extra documents-opendocument` |
| `search-bm25` | BM25 稀疏库（默认用自建倒排） | `uv sync --extra search-bm25` |

> [!warning] litellm 钉版
> `litellm>=1.85,<1.91`。≥1.93 无 Windows 预编译 wheel（需 Rust/MSVC 工具链）。升级前先确认 wheel 可用性。

> [!note] 前端依赖隔离
> 前端是独立 npm 工程（`frontend/`），与后端 Python 依赖隔离；仅在生产托管或前端开发时才需 Node（见第三部分 §11）。

---

# 第二部分　测试 / 开发部署

> [!tip] 目标
> 几分钟拉起可测试实例：无需 Postgres/Neo4j/真实模型，全离线。适合本地开发、跑测试套件、UI 冒烟。

## 3. 配置 .env（SQLite + 离线桩模型）

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

把数据/模型三段设为离线桩：

```dotenv
# 数据库：SQLite 零依赖
CALLIODESMO_DATABASE_URL=sqlite+aiosqlite:///./data/calliodesmo-dev.db

# LLM：离线桩（无网络，返回固定响应，仅验证管线机制）
CALLIODESMO_LLM_MODEL=test/stub
CALLIODESMO_LLM_API_KEY=
CALLIODESMO_LLM_API_BASE=

# 嵌入：哈希桩（确定性伪向量，离线）
CALLIODESMO_EMBEDDING_PROVIDER=hash
CALLIODESMO_EMBEDDING_DIMENSION=64

# 重排：保序降级（不调用任何模型）
CALLIODESMO_RERANKER_PROVIDER=none

# 管理员（仅 db seed 用）
CALLIODESMO_ADMIN_PASSWORD=admin-123456
```

> `test/stub` 对任意输入返回写死的抽取（如 `OpenAI -developed-> GPT-4`），**用于验证管线机制而非抽取质量**。真实抽取见第三部分模型配置。

## 4. 初始化数据库

```bash
uv run calliodesmo db init   # 建表（幂等）
uv run calliodesmo db seed   # 内置角色/权限 + 初始管理员（幂等）
```

或一键引导（幂等，自动设 SQLite + 建表 + 种子 + 冒烟）：

```powershell
# Windows
.\scripts\bootstrap.ps1 -Sqlite
```
```bash
# Linux / macOS
scripts/bootstrap.sh --sqlite
```

## 5. 测试套件

### 5.1 后端（pytest）

```bash
uv run pytest -v             # 289 用例，内存 SQLite，离线可跑
uv run ruff check .          # 静态检查
uv run ruff format --check . # 格式检查
```

隔离原理（无需外部服务即可跑）：

- **内存 SQLite**：每用例独立 `sqlite+aiosqlite:///:memory:`（见 `tests/conftest.py`）。
- **`sys.modules` 桩**：隔离 litellm / uvicorn 等外部依赖--完全离线。
- **契约优先**：接口测试断言输入映射与输出结构，保证可插拔。
- **幂等**：种子与引导脚本均显式验证可重复执行。
- **权限矩阵**：`/query` `/admin/*` `/library/*` 受限端点做参数化矩阵（3 角色 × 端点）。
- **stores 隔离**：内存 stores 单例经 `reset_app_stores()` 在 try/finally 清理。

### 5.2 前端（vitest）

```bash
cd frontend && npm ci
npm test                    # vitest（API 客户端契约等）
npm run lint                # tsc -b --noEmit 类型检查
npm run build               # vite build（验证产物可构建）
```

### 5.3 CI（GitHub Actions）

`.github/workflows/ci.yml` 在每次 push/PR 自动执行：

- 后端 job：`uv sync` -> `ruff check` + `ruff format --check` -> `pytest`。
- 前端 job：`npm ci` -> `npm run build` -> `vitest`。

本地复现 CI：依次跑上述 5.1 + 5.2 命令即可。

## 6. 冒烟验证

启动 API + 桩演示数据（全离线，秒级）：

```bash
uv run calliodesmo serve --seed-demo   # 对 data/demo/ 跑桩 ECL 灌内存 stores，启动 SPA
```

```bash
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/auth/token -d "username=admin&password=admin-123456"
# 用返回 token 调 /query（桩答案）/library/profile-cards（桩档案卡）
```

浏览器打开 `http://127.0.0.1:8000` 登录 `admin` / `admin-123456`，走问答 / 浏览 / 管理（验证 UI 与权限矩阵）。

> [!note] 桩数据的局限
> `test/stub` 抽取是写死的，与文档真实内容无关；冒烟仅验证"管线跑通 + UI 可用 + 权限正确"，**不验证抽取质量**。真实抽取需切到第三部分的真实模型。

CLI 建图冒烟（导出抽取详情供检查）：

```bash
uv run calliodesmo ingest <path> --dump-json out.json --dump-html out.html
```

## 7. 能力边界（SQLite 开发模式）

| 可用 | 不可用 |
| --- | --- |
| 认证 / 权限 / 审计 / CLI / API / Web UI 全功能 | pgvector 持久化向量检索 |
| 检索与问答（向量库/图库/社区库降级为**内存实现**） | Neo4j 持久化语义层 |
| 完整测试套件（内存 SQLite） | 进程重启后内存 stores 数据丢失（仅 SQLite 持久化元数据） |

> 需要持久化向量检索 / 图库时，切到第三部分生产部署（仅改 `.env` 连接串，应用层无感）。

---

# 第三部分　生产部署（按步骤）

> [!tip] 目标
> 完整生产实例：PostgreSQL+pgvector / Neo4j 持久化 + 真实模型（云端或自建）。

## 8. 配置 .env（生产）

### 8.1 数据库

保留 Postgres 连接串，按下方安装 PostgreSQL 16 + pgvector 与 Neo4j。

```dotenv
CALLIODESMO_DATABASE_URL=postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo
```

#### PostgreSQL 16 + pgvector

Ubuntu / Debian（推荐）：

```bash
sudo apt install wget ca-certificates
wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo tee /etc/apt/trusted.gpg.d/pgdg.asc
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install postgresql-16 postgresql-16-pgvector
sudo systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE USER calliodesmo WITH PASSWORD 'calliodesmo';"
sudo -u postgres psql -c "CREATE DATABASE calliodesmo OWNER calliodesmo;"
sudo -u postgres psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

macOS：

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
createuser calliodesmo -P
createdb calliodesmo -O calliodesmo
psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Windows：EDB 图形安装器或 `winget install PostgreSQL.PostgreSQL.16`；pgvector **无官方 Windows 预编译包**，需 Visual Studio Build Tools（C++）从源码编译：

```powershell
# x64 Native Tools 命令行（需 pg_config 在 PATH）
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> [!tip] Windows 门槛高？
> 先用第二部分 SQLite 开发模式跑通应用；需要向量检索/图库时，把 Postgres/Neo4j 部署到 Linux 机器/容器，仅改 `.env` 连接串，应用层无感。

#### Neo4j Community

前置：**Java 17+**（`winget install EclipseAdoptium.Temurin.21.JRE` / `brew install temurin` / `sudo apt install temurin-21-jre`）。

```powershell
# Windows：下载 community zip 解压后
bin\neo4j.bat console                 # 前台（开发推荐）
bin\neo4j.bat windows-service install # 注册为服务
```
```bash
# Linux / macOS：下载 community tar 解压后
bin/neo4j console     # 前台
bin/neo4j start       # 后台
```

首次访问 `http://localhost:7474`，初始账号 `neo4j` / `neo4j` 强制改密；新密码写进 `.env`：

```dotenv
CALLIODESMO_NEO4J_URI=bolt://localhost:7687
CALLIODESMO_NEO4J_USER=neo4j
CALLIODESMO_NEO4J_PASSWORD=<改后的密码>
```

### 8.2 密钥与管理员

```dotenv
CALLIODESMO_JWT_SECRET_KEY=<≥32 字节随机串>   # 生产必改
CALLIODESMO_ADMIN_USERNAME=admin
CALLIODESMO_ADMIN_PASSWORD=<初始管理员密码>    # 仅 db seed 创建管理员时用
CALLIODESMO_ALLOW_SELF_REGISTER=false          # 自注册默认关
```

生成密钥：`python -c "import secrets;print(secrets.token_urlsafe(32))"`。

### 8.3 模型配置（三层，独立可切换）

#### LLM（经 LiteLLM，`<provider>/<model>`）

| 场景 | `LLM_MODEL` | `LLM_API_KEY` | `LLM_API_BASE` |
| --- | --- | --- | --- |
| 云端 OpenAI | `openai/gpt-4o-mini` | `sk-...` | （留空） |
| 云端 Qwen | `openai/qwen-plus` | `sk-...` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 云端 DeepSeek | `deepseek/deepseek-chat` | `sk-...` | （留空） |
| 本地 Ollama | `ollama/qwen2.5` | （留空） | `http://localhost:11434` |
| 本地 LM Studio | `openai/local-model` | 任意非空占位 | `http://localhost:1234/v1` |
| 本地/远端 llama.cpp | `openai/local-model` | 任意非空占位 | `http://<host>:<port>/v1` |
| 离线桩（无网络） | `test/stub` | （留空） | （留空） |

> [!tip] 本地豁免
> 当 `LLM_API_BASE` 指向 `localhost` / `127.0.0.1` / `0.0.0.0` / `::1`，或 `LLM_MODEL` 以 `ollama/` / `lm-studio/` 开头时，自动豁免 API key 校验。指向**非 localhost 自建服务**（如局域网 llama.cpp）时，填任意非空 `LLM_API_KEY` 即可。

#### 嵌入

| 场景 | `EMBEDDING_PROVIDER` | 其他项 |
| --- | --- | --- |
| 离线桩 | `hash` | `DIMENSION=64` |
| 本地 BGE-M3 | `bge-m3` | 需 `--extra embedding-local`；`MODEL=BAAI/bge-m3`；`DIMENSION=1024` |
| 远端 HTTP | `remote` | `API_BASE=http://<host>:8082`（无需带 `/v1`）；`MODEL=bge-m3`；`DIMENSION=1024` |

#### 重排

| 场景 | `RERANKER_PROVIDER` | 其他项 |
| --- | --- | --- |
| 保序降级（默认） | `none` | 无（不重排） |
| 本地 BGE | `local` | 需 `--extra search-rerank`；`MODEL=BAAI/bge-reranker-v2-m3` |
| 远端 HTTP | `remote` | `API_BASE=http://<host>:8083`；`MODEL=BAAI/bge-reranker-v2-m3`；`API_KEY=` |

#### 远端三服务示例（自建 llama.cpp）

```dotenv
CALLIODESMO_LLM_MODEL=openai/local-model
CALLIODESMO_LLM_API_KEY=local
CALLIODESMO_LLM_API_BASE=http://<llm-host>:8081/v1
CALLIODESMO_EMBEDDING_PROVIDER=remote
CALLIODESMO_EMBEDDING_API_BASE=http://<embed-host>:8082
CALLIODESMO_EMBEDDING_MODEL=bge-m3
CALLIODESMO_EMBEDDING_DIMENSION=1024
CALLIODESMO_RERANKER_PROVIDER=remote
CALLIODESMO_RERANKER_API_BASE=http://<rerank-host>:8083
CALLIODESMO_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
CALLIODESMO_RERANKER_API_KEY=
```

## 9. 初始化数据库

```bash
uv run calliodesmo db init   # 建表（幂等）
uv run calliodesmo db seed   # 内置角色/权限 + 初始管理员（幂等；需 ADMIN_PASSWORD）
```

## 10. （可选）自建模型服务

若用 llama.cpp 自建 LLM / 嵌入 / 重排（OpenAI 兼容）：

```bash
./llama-server -m qwen.gguf --port 8081 --host 0.0.0.0              # LLM
./llama-server --embeddings -m bge-m3.gguf --port 8082 --host 0.0.0.0 # 嵌入
./llama-server --rerank -m bge-reranker-v2-m3.gguf --port 8083 --host 0.0.0.0  # 重排
```

连通性验证：

```bash
curl http://<host>:8081/v1/models
curl http://<host>:8082/v1/models
curl -X POST http://<host>:8083/rerank -H 'Content-Type: application/json' \
  -d '{"query":"测试","documents":["文档一","文档二"]}'
```

## 11. 前端

```bash
cd frontend && npm ci
npm run build      # 产出 dist/，由 FastAPI StaticFiles 同源托管
```

> 生产无需单独部署前端：`serve` 托管 `frontend/dist`（SPA）。仅开发期才用 `npm run dev`（5173，/api proxy 转 8000）。

## 12. 启动后端

```bash
uv run calliodesmo serve                    # API + SPA：http://127.0.0.1:8000
uv run calliodesmo serve --seed-demo        # 同上 + 启动前灌 data/demo/ 演示数据
uv run calliodesmo serve --host 0.0.0.0 --port 8000   # 监听所有网卡
```

> [!note] `--seed-demo` 说明
> 内存 stores 模式下 CLI `ingest`（独立进程）灌的数据 serve 进程不可见，故演示数据走 serve 进程内自灌：对 `data/demo/` 跑 ECL（首次含 LLM 调用，较慢），产物落盘 `data/demo/seed-cache.json`，二次启动命中缓存跳过 LLM。指向自定义语料可设 `CALLIODESMO_DEMO_DIR`。重复运行崩溃已修复（`selectinload`）。

建图（写入个人库，CLI）：

```bash
uv run calliodesmo ingest <path>           # 文件或目录
uv run calliodesmo ingest <path> --dump-json out.json --dump-html out.html
```

## 13. 验证

```bash
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/auth/token -d "username=admin&password=<密码>"
curl http://127.0.0.1:8000/auth/me -H "Authorization: Bearer <token>"
```

浏览器 `http://127.0.0.1:8000` 登录，问答 / 浏览 / 管理。API 文档 `/docs`。

验证清单：

- [ ] `db init` + `db seed` 成功（管理员已创建）
- [ ] `serve` 后 `/healthz` 返回 ok
- [ ] `/auth/token` 拿到 JWT，`/auth/me` 返回 AccessContext
- [ ] `POST /query` 返回带来源标注的答案；`GET /library/profile-cards` 返回档案卡（需先 `ingest` 或 `serve --seed-demo`）
- [ ] 浏览器可登录并问答/浏览（Web UI）
- [ ] Postgres `SELECT * FROM roles;` 有 analyst/reviewer/admin；`audit_logs` 有 login
- [ ] Neo4j 浏览器可登录

## 14. 生产加固

- **进程管理**：Linux systemd 托管；Windows NSSM / 任务计划。
- **反向代理**：Nginx/Caddy 终结 TLS，转发 127.0.0.1:8000。
- **密钥**：`JWT_SECRET_KEY` ≥32 字节随机；`.env` 权限 600，不入库（`.gitignore` 已覆盖）。
- **会话**：JWT 经 httpOnly + SameSite=Lax cookie（防 XSS 读 token）；无 refresh token，过期 401 重登。
- **备份**：`pg_dump`（Postgres）+ `neo4j-admin database dump`（Neo4j）。
- **升级**：`uv sync --upgrade-package <pkg>` 后跑 `uv run pytest` 回归。

systemd 单元：

```ini
[Unit]
Description=Calliodesmo API
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/opt/calliodesmo
ExecStart=/usr/local/bin/uv run calliodesmo serve --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Nginx 片段：

```nginx
server {
    listen 443 ssl http2;
    server_name calliodesmo.example;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 15. 故障排查

| 现象 | 原因 / 解决 |
| --- | --- |
| `LLM 缺 API key` | 非 localhost 服务需填 `LLM_API_KEY`（任意非空）或改指向 localhost |
| litellm 安装失败（Windows） | 钉版 `<1.91`；`≥1.93` 无预编译 wheel，需 Rust/MSVC |
| PDF / Word 加载报错 | `uv sync --extra documents-pdf` / `documents-office` |
| pgvector Windows 编译难 | 先用 SQLite 开发模式，或把 Postgres 部署到 Linux/容器 |
| `serve --seed-demo` 重复运行崩溃 | 已修复（`selectinload`）；拉取最新代码 |
| 查询无结果 | 检查用户 clearance/scope；演示数据需 `serve --seed-demo`；非 admin 看不到他人个人库 |
| LiteLLM `CERTIFICATE_VERIFY_FAILED` 警告 | 仅模型价格表拉取失败，已回退本地备份，不影响推理 |
| 自建模型服务 `Connection refused` | 确认 `--host 0.0.0.0`、端口与 `.env` 一致、防火墙放行 |
| `test_ingest_llm_missing_key` 本地失败 | 本地 `.env` 设了 `LLM_API_KEY` 导致；CI 无 `.env` 不受影响 |