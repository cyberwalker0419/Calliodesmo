---
title: 原生部署指南（按步骤）
type: guide
tags:
  - deploy
created: 2026-07-26
---
# 原生部署指南（按步骤）

> [!info] 适用场景
> 本机/服务器不装 Docker 时的完整部署路径。按下方顺序执行：**装环境 → 装依赖 → 配 `.env` → 初始化 → （可选）模型服务 → （可选）前端 → 启动后端 → 验证**。基础设施可选 SQLite（零依赖开发）或 PostgreSQL+pgvector / Neo4j（生产）。一键 Docker 全栈见根目录 `docker-compose.yml` + `Dockerfile`。关联：[[docs/plans/roadmap|年计划]]。

## 0. 组件与选型

| 组件 | 作用 | 开发（零依赖） | 生产 |
| --- | --- | --- | --- |
| 应用（FastAPI + CLI） | API / Web UI / CLI | uv + Python 3.12 | 同左 |
| 情景层 DB | 文本块 + 向量 | SQLite（内存 stores 降级） | PostgreSQL 16 + pgvector |
| 语义层 | 实体关系图 | 内存 GraphStore | Neo4j Community |
| 摘要层 | 社区摘要 | 内存 CommunityStore | PostgreSQL |
| LLM | 抽取 / 摘要 / 问答合成 | `test/stub` 离线桩 | 云端 / 本地 / 远端 HTTP |
| 嵌入 | 向量化 | `hash` 桩 | 本地 BGE-M3 / 远端 HTTP |
| 重排 | 交叉编码器重排 | `none` 保序降级 | 本地 BGE / 远端 HTTP |

> 三层模型（LLM / 嵌入 / 重排）**独立配置**，可分别选本地或远端，互不耦合。

---

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

可选 extras（按需启用对应能力，缺时懒加载报错并提示安装命令）：

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

## 3. 配置 .env

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

### 3.1 数据库

**开发（SQLite，零依赖）**——取消注释该行、注释掉 Postgres 行：

```dotenv
# CALLIODESMO_DATABASE_URL=postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo
CALLIODESMO_DATABASE_URL=sqlite+aiosqlite:///./data/calliodesmo-dev.db
```

**生产（PostgreSQL 16 + pgvector + Neo4j）**——保留 Postgres 连接串，按下方安装基础设施。

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
createuser calliodesmo -P          # 密码 calliodesmo
createdb calliodesmo -O calliodesmo
psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Windows：EDB 图形安装器或 `winget install PostgreSQL.PostgreSQL.16`；pgvector **无官方 Windows 预编译包**，需 Visual Studio Build Tools（C++ 工作负载）从源码编译：

```powershell
# x64 Native Tools 命令行（需 pg_config 在 PATH）
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> [!tip] Windows 门槛高？
> 先用 SQLite 开发模式（本节开发配置）跑通应用；需要向量检索/图库时，把 Postgres/Neo4j 部署到 Linux 机器/容器，仅改 `.env` 连接串，应用层无感。

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

### 3.2 密钥与管理员

```dotenv
CALLIODESMO_JWT_SECRET_KEY=<≥32 字节随机串>   # 生产必改
CALLIODESMO_ADMIN_USERNAME=admin
CALLIODESMO_ADMIN_PASSWORD=<初始管理员密码>    # 仅 db seed 创建管理员时用
CALLIODESMO_ALLOW_SELF_REGISTER=false          # 自注册默认关
```

生成密钥：`python -c "import secrets;print(secrets.token_urlsafe(32))"`。

### 3.3 模型配置（三层，独立可切换）

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
> 当 `LLM_API_BASE` 指向 `localhost` / `127.0.0.1` / `0.0.0.0` / `::1`，或 `LLM_MODEL` 以 `ollama/` / `lm-studio/` 开头时，自动豁免 API key 校验。指向**非 localhost 的自建服务**（如局域网 llama.cpp）时，填任意非空 `LLM_API_KEY` 即可（服务通常不校验密钥）。

#### 嵌入

| 场景 | `EMBEDDING_PROVIDER` | 其他项 |
| --- | --- | --- |
| 离线桩（无网络） | `hash` | `EMBEDDING_DIMENSION=64` |
| 本地 BGE-M3 | `bge-m3` | 需 `--extra embedding-local`；`MODEL=BAAI/bge-m3`；`DIMENSION=1024` |
| 远端 HTTP | `remote` | `API_BASE=http://<host>:8082`（无需带 `/v1`）；`MODEL=bge-m3`；`DIMENSION=1024` |

#### 重排

| 场景 | `RERANKER_PROVIDER` | 其他项 |
| --- | --- | --- |
| 保序降级（默认） | `none` | 无（不重排，按召回序） |
| 本地 BGE 交叉编码器 | `local` | 需 `--extra search-rerank`；`MODEL=BAAI/bge-reranker-v2-m3` |
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

> 三层可任意组合，例如 LLM 用云端 OpenAI、嵌入与重排用局域网自建 BGE 服务。

## 4. 初始化数据库

```bash
uv run calliodesmo db init   # 建 Base.metadata 全部表（幂等）
uv run calliodesmo db seed   # 内置角色/权限 + 初始管理员（幂等；需先设 ADMIN_PASSWORD）
```

## 5. （可选）自建模型服务

若用 llama.cpp 自建 LLM / 嵌入 / 重排（OpenAI 兼容）：

```bash
# LLM（对话/抽取/摘要）
./llama-server -m qwen.gguf --port 8081 --host 0.0.0.0
# 嵌入（bge-m3，启用 /v1/embeddings）
./llama-server --embeddings -m bge-m3.gguf --port 8082 --host 0.0.0.0
# 重排（bge-reranker-v2-m3，启用 /rerank）
./llama-server --rerank -m bge-reranker-v2-m3.gguf --port 8083 --host 0.0.0.0
```

连通性验证：

```bash
curl http://<host>:8081/v1/models     # LLM
curl http://<host>:8082/v1/models     # 嵌入
curl -X POST http://<host>:8083/rerank -H 'Content-Type: application/json' \
  -d '{"query":"测试","documents":["文档一","文档二"]}'   # 重排
```

## 6. （可选）前端

```bash
cd frontend && npm ci
npm run dev        # 开发：Vite 5173，/api 经 proxy 转 8000
npm run build      # 生产：产出 dist/，由 FastAPI StaticFiles 同源托管（无需单独部署前端）
```

> 生产无需单独部署前端：`serve` 会托管 `frontend/dist`（SPA 静态文件）。仅开发期才用 `npm run dev`。

## 7. 启动后端

```bash
uv run calliodesmo serve                    # API + SPA：http://127.0.0.1:8000
uv run calliodesmo serve --seed-demo        # 同上 + 启动前灌 data/demo/ 演示数据
uv run calliodesmo serve --host 0.0.0.0 --port 8000   # 监听所有网卡
```

> [!note] `--seed-demo` 说明
> 内存 stores 模式下 CLI `ingest`（独立进程）灌的数据 serve 进程不可见，故演示数据统一走 serve 进程内自灌：对 `data/demo/` 跑 ECL（首次含 LLM 调用，较慢），产物落盘 `data/demo/seed-cache.json`，二次启动命中缓存跳过 LLM。指向自定义语料可设 `CALLIODESMO_DEMO_DIR`。重复运行崩溃已修复（`selectinload`）。

建图（写入个人库，CLI；跨进程，serve 内存模式不可见）：

```bash
uv run calliodesmo ingest <path>           # 文件或目录，按后缀分发加载器
uv run calliodesmo ingest <path> --dump-json out.json --dump-html out.html   # 导出抽取详情/关系图
```

## 8. 验证

```bash
curl http://127.0.0.1:8000/healthz
# {"status":"ok",...}
# 登录拿 token：
curl -X POST http://127.0.0.1:8000/auth/token -d "username=admin&password=<密码>"
# {"access_token":"...","token_type":"bearer"}
curl http://127.0.0.1:8000/auth/me -H "Authorization: Bearer <token>"
```

浏览器打开 `http://127.0.0.1:8000` 登录，问答 / 浏览 / 管理（P3 Web UI）。API 文档 `/docs`。

验证清单：

- [ ] `db init` + `db seed` 成功（管理员已创建）
- [ ] `serve` 后 `/healthz` 返回 ok
- [ ] `/auth/token` 拿到 JWT，`/auth/me` 返回 AccessContext JSON
- [ ] `POST /query` 返回带来源标注的答案；`GET /library/profile-cards` 返回档案卡（需先 `ingest` 或 `serve --seed-demo`）
- [ ] 浏览器打开 http://127.0.0.1:8000 可登录并问答/浏览（P3 Web UI）
- [ ] Postgres 中 `SELECT * FROM roles;` 有 analyst/reviewer/admin；`audit_logs` 有 login 记录
- [ ] Neo4j 浏览器可登录（语义层建图前的连通性确认）

## 9. 生产加固

- **进程管理**：Linux 用 systemd 托管；Windows 用 NSSM / 任务计划。
- **反向代理**：Nginx/Caddy 终结 TLS，转发到 127.0.0.1:8000。
- **密钥**：`JWT_SECRET_KEY` 用 ≥32 字节随机串；`.env` 权限 600，绝不入库（`.gitignore` 已覆盖）。
- **会话**：JWT 经 httpOnly + SameSite=Lax cookie 下发（防 XSS 读 token）；无 refresh token，过期 401 重登。
- **备份**：`pg_dump`（Postgres）+ `neo4j-admin database dump`（Neo4j）。
- **升级**：`uv sync --upgrade-package <pkg>` 后跑 `uv run pytest` 回归。

systemd 单元示例：

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
    # ssl_certificate ...
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 10. 故障排查

| 现象 | 原因 / 解决 |
| --- | --- |
| `LLM 缺 API key` | 非 localhost 服务需填 `LLM_API_KEY`（任意非空）或改指向 localhost |
| litellm 安装失败（Windows） | 钉版 `<1.91`；`≥1.93` 无预编译 wheel，需 Rust/MSVC |
| PDF / Word 加载报错 | `uv sync --extra documents-pdf` / `documents-office` |
| pgvector Windows 编译难 | 先用 SQLite 开发模式，或把 Postgres 部署到 Linux/容器 |
| `serve --seed-demo` 重复运行崩溃 | 已修复（`selectinload`）；拉取最新代码 |
| 查询无结果 | 检查用户 clearance/scope；演示数据需 `serve --seed-demo`；非 admin 看不到他人个人库 |
| LiteLLM `CERTIFICATE_VERIFY_FAILED` 警告 | 仅模型价格表拉取失败，已回退本地备份，不影响推理 |
| 自建服务 `Connection refused` | 确认 `--host 0.0.0.0`、端口与 `.env` 一致、防火墙放行 |