---
title: 本地原生部署指南（生产）
type: guide
tags:
  - deploy
created: 2026-07-26
updated: 2026-08-13
---
# 本地原生部署指南（生产，无 Docker）

> 自备 PostgreSQL 16+（pgvector）与 Neo4j，用 uv 跑应用。测试/开发环境见 [testing.md](testing.md)；Docker 全栈见 [docker.md](docker.md)。

## 0. 组件与选型

| 组件 | 作用 | 生产 |
| --- | --- | --- |
| 应用（FastAPI + CLI） | API / Web UI / CLI | uv + Python 3.12 |
| 情景层 DB | 文本块 + 向量 | PostgreSQL 16+ + pgvector |
| 语义层 | 实体关系图 | Neo4j Community |
| 摘要层 | 社区摘要 | PostgreSQL |
| LLM / 嵌入 / 重排 | 三层模型 | 云端 / 本地 / 远端 HTTP（见 §6） |

## 1. 安装 uv 与依赖

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # Windows: irm https://astral.sh/uv/install.ps1 | iex
uv sync --extra persistence   # 核心依赖 + pgvector/neo4j（P4.5 起必需）
```

可选 extras（按需）：`embedding-local`（本地 BGE-M3）· `search-rerank`（本地重排）· `documents-pdf/office/opendocument`（多格式）· `search-bm25`。

> litellm 钉版 `>=1.85,<1.91`：≥1.93 无 Windows 预编译 wheel（需 Rust/MSVC）。

## 2. 安装 PostgreSQL 16 + pgvector

Ubuntu / Debian：

```bash
sudo apt install postgresql-16 postgresql-16-pgvector
sudo systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE USER calliodesmo WITH PASSWORD 'calliodesmo';"
sudo -u postgres psql -c "CREATE DATABASE calliodesmo OWNER calliodesmo;"
sudo -u postgres psql -d calliodesmo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

macOS：`brew install postgresql@16 pgvector`。Windows：EDB 图形安装器 + 从源码编译 pgvector（无官方预编译包）；**嫌麻烦直接用 Docker 全栈或局域网自建 PG/Neo4j**。

## 3. 安装 Neo4j Community

前置：Java 17+。下载 community 解压后 `bin/neo4j console`（前台）或 `bin/neo4j start`。首次访问 `http://localhost:7474`，初始 `neo4j/neo4j` 强制改密，新密码写进 `.env`。

## 4. 配置 .env（生产）

```bash
cp .env.example .env
```

核心项：

```dotenv
CALLIODESMO_DATABASE_URL=postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo
CALLIODESMO_NEO4J_URI=bolt://localhost:7687
CALLIODESMO_NEO4J_USER=neo4j
CALLIODESMO_NEO4J_PASSWORD=<改后的密码>

CALLIODESMO_JWT_SECRET_KEY=<≥32 字节随机串>   # 生产必改（python -c "import secrets;print(secrets.token_urlsafe(32))"）
CALLIODESMO_ADMIN_PASSWORD=<初始管理员密码>    # 仅 db seed 用
CALLIODESMO_ALLOW_SELF_REGISTER=false
```

## 5. 初始化与启动

```bash
uv run calliodesmo db init      # 建表（幂等）
uv run calliodesmo db seed      # 角色/权限 + 初始管理员（幂等）
uv run calliodesmo serve        # API + SPA：http://127.0.0.1:8000
```

建图：`uv run calliodesmo ingest <path>`（文件或目录）；演示数据：`uv run calliodesmo serve --seed-demo`。

前端：生产无需单独部署——`serve` 托管 `frontend/dist`（需先 `cd frontend && npm ci && npm run build`）。

## 6. 模型配置（三层独立可切）

### LLM（LiteLLM，`<provider>/<model>`）

| 场景 | `LLM_MODEL` | `LLM_API_KEY` | `LLM_API_BASE` |
| --- | --- | --- | --- |
| OpenAI | `openai/gpt-4o-mini` | `sk-...` | （留空） |
| DeepSeek | `deepseek/deepseek-chat` | `sk-...` | （留空） |
| Qwen（DashScope 兼容） | `openai/qwen-plus` | `sk-...` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Ollama（本地） | `ollama/qwen2.5` | （留空） | `http://localhost:11434` |
| llama.cpp（本地/远端） | `openai/local-model` | 任意非空占位 | `http://<host>:<port>/v1` |

> 本地豁免：`LLM_API_BASE` 指向 `localhost` / `127.0.0.1` / `0.0.0.0`，或 `LLM_MODEL` 以 `ollama/` / `lm-studio/` 开头时，自动豁免 API key 校验；指向非 localhost 自建服务填任意非空 key 即可。

### 嵌入

| 场景 | `EMBEDDING_PROVIDER` | 其他 |
| --- | --- | --- |
| 本地 BGE-M3 | `bge-m3` | 需 `uv sync --extra embedding-local`；`MODEL=BAAI/bge-m3`；`DIMENSION=1024` |
| 远端 HTTP | `remote` | `API_BASE=http://<host>:8082`（无需 `/v1`）；`MODEL=bge-m3`；`DIMENSION=1024` |
| 离线桩 | `hash` | `DIMENSION=64`（仅测试环境） |

### 重排

| 场景 | `RERANKER_PROVIDER` | 其他 |
| --- | --- | --- |
| 保序降级（默认） | `none` | 无 |
| 本地 BGE | `local` | 需 `uv sync --extra search-rerank`；`MODEL=BAAI/bge-reranker-v2-m3` |
| 远端 HTTP | `remote` | `API_BASE=http://<host>:8083`；`MODEL=BAAI/bge-reranker-v2-m3` |

### 自建三服务（llama.cpp，示例）

```bash
./llama-server -m qwen.gguf --port 8081 --host 0.0.0.0               # LLM
./llama-server --embeddings -m bge-m3.gguf --port 8082 --host 0.0.0.0  # 嵌入
./llama-server --rerank -m bge-reranker-v2-m3.gguf --port 8083 --host 0.0.0.0  # 重排
```

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
```

## 7. 验证

```bash
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/auth/token -d "username=admin&password=<密码>"
```

浏览器登录后走问答 / 浏览 / 管理；API 文档 `/docs`。

## 8. 生产加固

- **进程管理**：Linux 用 systemd 托管 `uv run calliodesmo serve --host 127.0.0.1 --port 8000`；Windows 用 NSSM / 任务计划。
- **反向代理**：Nginx/Caddy 终结 TLS，转发 127.0.0.1:8000。
- **密钥**：`JWT_SECRET_KEY` ≥32 字节随机；`.env` 权限 600，不入库（`.gitignore` 已覆盖）。
- **会话**：JWT 经 httpOnly + SameSite=Lax cookie；无 refresh token，过期 401 重登。
- **备份**：`pg_dump`（Postgres）+ `neo4j-admin database dump`（Neo4j）。
- **升级**：`git pull && uv sync` 后重启 + `uv run pytest` 回归。

## 9. 故障排查

| 现象 | 解决 |
| --- | --- |
| `LLM 缺 API key` | 非 localhost 服务填非空 key 或改指向 localhost |
| litellm 安装失败（Windows） | 钉版 `<1.91`；≥1.93 无预编译 wheel |
| PDF / Word 加载报错 | `uv sync --extra documents-pdf` / `documents-office` |
| pgvector Windows 编译难 | 用 Docker 全栈或局域网自建 PG/Neo4j |
| 查询无结果 | 检查用户 clearance/scope；演示数据需 `serve --seed-demo` |
| 自建模型服务 `Connection refused` | 服务需 `--host 0.0.0.0`；端口 / 防火墙对 |
