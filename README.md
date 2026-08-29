# Calliodesmo

> 三层知识图谱驱动的智能情报分析平台：GraphRAG 索引基座 + 混合检索与 Agent 编排，LLM / 嵌入 / 重排均可切换。

[![phase: P5 done](https://img.shields.io/badge/phase-P5%20advanced--rag%20done-22c55e)](docs/plans/phases/P5-advanced-rag.md)
[![phase: P6 planned](https://img.shields.io/badge/phase-P6%20llm--analysis%20planned-3b82f6)](docs/plans/phases/P6-llm-analysis-tasks.md)
[![python: 3.12](https://img.shields.io/badge/python-3.12-3776ab)](pyproject.toml)
[![license](https://img.shields.io/badge/license-AGPL--3.0--or--later-7c3aed)](LICENSE)

Calliodesmo 把原始文档加工成**三层知识图谱**（情景层 / 语义层 / 社区摘要层），支撑从精准检索到全局研判的多层问答，并以**三维正交权限模型**（角色 + 访问等级 + 库范围）和 **Git-like 协作推送**保证多用户情报生产的安全与可追溯。

## 部署（生产，二选一）

### 方式 A：Docker（推荐，一键全栈）

```bash
cp .env.example .env            # 配置密钥；设 CALLIODESMO_ADMIN_PASSWORD 启用初始管理员
set CALLIODESMO_ADMIN_PASSWORD=<你的密码>   # PowerShell 也可写进 .env
set CALLIODESMO_JWT_SECRET_KEY=<≥32 字节随机串>  # 生产必改

docker compose up -d --build    # 起 PostgreSQL+pgvector + Neo4j + app（自动 init/seed/serve）
```

- 访问 **http://127.0.0.1:8000**（Web UI + API + `/docs`），登录 `admin` / `<你的密码>`。
- 建图：文档放 `./data/docs`，执行 `docker compose exec app calliodesmo ingest /app/data/docs`。
- 日志 / 停止：`docker compose logs -f app` · `docker compose down`（`-v` 加删卷，慎用）。
- 容器连接串已由 compose 覆盖为服务名，`DATABASE_URL` / `NEO4J_URI` 无需手改。

详细见 [Docker 部署指南](docs/deploy/docker.md)。

### 方式 B：本地原生（uv，无 Docker）

前置：安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)（自动准备 Python 3.12），自备 PostgreSQL 16+（pgvector）与 Neo4j。

```bash
uv sync --extra persistence     # 安装依赖（含 pgvector/neo4j，P4.5 起必需）
cp .env.example .env            # 填 PG/Neo4j 连接串、模型配置；设管理员密码

uv run calliodesmo db init      # 建表（幂等）
uv run calliodesmo db seed      # 内置角色/权限 + 初始管理员（幂等）
uv run calliodesmo serve        # 启动 API + Web UI：http://127.0.0.1:8000
```

- 建图：`uv run calliodesmo ingest <path>`。
- 数据库 / 图库 / 模型的原生安装步骤见 [本地原生部署指南](docs/deploy/native.md)。

> 测试/开发环境（桩模型、跑测试套件、前端联调）已独立：见 [测试/开发环境](docs/deploy/testing.md)，不占用本页篇幅。

## 模型配置（三层可切换，只改 `.env` 不动代码）

| 层 | 配置项 | 取值 | 说明 |
| --- | --- | --- | --- |
| **LLM** | `LLM_MODEL/LLM_API_KEY/LLM_API_BASE` | LiteLLM `provider/model` | OpenAI / DeepSeek / Qwen / Ollama / llama.cpp 等一键切换；`test/stub` 离线桩 |
| **嵌入** | `EMBEDDING_PROVIDER/...` | `hash` / `bge-m3` / `remote` | 本地 BGE-M3（`uv sync --extra embedding-local`）或 OpenAI 兼容远端服务 |
| **重排** | `RERANKER_PROVIDER/...` | `none` / `local` / `remote` | `none` 保序降级（默认）；本地 BGE 交叉编码器或远端 llama.cpp `/rerank` |

> 本地模型豁免：`LLM_API_BASE` 指向 `localhost` 或 `LLM_MODEL` 以 `ollama/` `/lm-studio/` 开头时自动豁免 API key。完整示例见 `.env.example` 与部署指南。

## 项目结构（简）

```
src/calliodesmo/   FastAPI 后端 + Typer CLI（api / auth / ecl / retrieval / interfaces / providers / stores / eval / cli.py）
frontend/          React SPA（登录 / 问答 / 浏览 / 管理）
docs/              deploy（部署）· plans（路线图与阶段计划，Obsidian vault）· verification（验证报告）
tests/             pytest（真实 PG+pgvector+Neo4j，`-m "not db"` 跑纯逻辑）
```

## 文档导航

- 🚀 [Docker 部署指南](docs/deploy/docker.md) - 一键全栈生产
- 💻 [本地原生部署指南](docs/deploy/native.md) - 无 Docker 生产
- 🧪 [测试/开发环境](docs/deploy/testing.md) - 桩模型冒烟、pytest、前端联调
- 🗺️ [实施路线图](docs/plans/roadmap.md) - P0-P9 年计划
- ✅ [验证报告索引](docs/verification/README.md) - 各阶段测试证据

## License

[AGPL-3.0-or-later](LICENSE)
