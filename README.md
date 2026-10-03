# Calliodesmo

> 三层知识图谱驱动的智能情报分析平台：GraphRAG 索引基座 + 混合检索 + LLM 分析 + Agent 模式，LLM / 嵌入 / 重排均可切换。

[![phase: P7 done](https://img.shields.io/badge/phase-P7%20agent--mode%20done-22c55e)](docs/plans/phases/P7-agent-mode.md)
[![phase: P8 next](https://img.shields.io/badge/phase-P8%20evidence--verification%20next-3b82f6)](docs/plans/phases/P7-agent-mode.md)
[![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)
[![license](https://img.shields.io/badge/license-AGPL--3.0--or--later-7c3aed)](LICENSE)

Calliodesmo 把原始文档加工成**三层知识图谱**（情景层 / 语义层 / 社区摘要层），支撑从精准检索到全局研判的多层问答、九类结构化 LLM 分析与**权限内行动的 Agent 多轮对话**，并以**三维正交权限模型**（角色 + 访问等级 + 库范围）和 **Git-like 协作推送**保证多用户情报生产的安全与可追溯。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| **ECL 建图** | 多格式文档 → 实体/关系/声明/协变量四类抽取 → 实体消解 + 社区检测 + 摘要 → 三层落库 |
| **检索问答** | Native / Local / Global 三模式；混合检索（稠密+稀疏+图 RRF）+ 交叉编码器重排；来源标注 |
| **高级 RAG** | MultiQuery / RAGFusion / CRAG / SelfCheck / contextual retrieval，评估 harness 回归 |
| **LLM 分析** | 9 类结构化报告（摘要/关键信息/时间线/实体/关系/任务/概念/问答/自定义）+ 异步 job + 报告历史与导出 |
| **Agent 模式** | ReAct 多轮对话（LangGraph）；只读工具七件 + 分析桥；三重预算帽；工具轨迹透明可审计 |
| **安全** | 三维权限贯穿全链路（检索 / 分析 / Agent 工具调用）；越权与不存在同消息不泄漏存在性；全程审计 |

## 技术栈

| 类别 | 技术 |
| --- | --- |
| Web / CLI | FastAPI · uvicorn · Typer |
| 数据 | SQLAlchemy 2.0 (async) · PostgreSQL 16+ + pgvector · Neo4j |
| 认证 | PyJWT · pwdlib + Argon2 |
| LLM / 嵌入 | LiteLLM（多后端可切换）· BGE-M3（本地，可选 extra） |
| 检索 / Agent | LlamaIndex + LangGraph 1.x（`agent` extra：langgraph + langgraph-checkpoint-postgres + psycopg[binary]）· GraphRAG（库形式集成） |
| 质量 | pytest + pytest-asyncio · Ruff · GitHub Actions · Playwright（e2e，本地） |
| 前端 | React 19 · Vite 6 · TanStack Query · React Router 7 · Tailwind · shadcn/ui（Radix 源码拷贝）· cytoscape + cytoscape-fcose · lucide-react |

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
uv sync --extra agent           # Agent 模式（langgraph 家族，按需）
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
| **LLM** | `LLM_MODEL/LLM_API_KEY/LLM_API_BASE` | LiteLLM `provider/model` | OpenAI / DeepSeek / Qwen / Ollama / llama.cpp 等一键切换；`test/stub` 离线桩；须支持原生 tool calls（Agent 模式） |
| **嵌入** | `EMBEDDING_PROVIDER/...` | `hash` / `bge-m3` / `remote` | 本地 BGE-M3（`uv sync --extra embedding-local`）或 OpenAI 兼容远端服务 |
| **重排** | `RERANKER_PROVIDER/...` | `none` / `local` / `remote` | `none` 保序降级（默认）；本地 BGE 交叉编码器或远端 llama.cpp `/rerank` |

> 本地模型豁免：`LLM_API_BASE` 指向 `localhost` 或 `LLM_MODEL` 以 `ollama/` `/lm-studio/` 开头时自动豁免 API key。完整示例见 `.env.example` 与部署指南。

## 项目结构（简）

```
src/calliodesmo/   FastAPI 后端 + Typer CLI
├── api/ auth/ audit/ db/          Web / 三维权限 / 审计 / ORM
├── ecl/                           ECL 建图管线（抽取→消解→社区→落库）
├── retrieval/ eval/               检索域 + 评估 harness（golden 回归）
├── analysis/                      P6 分析域（9 类报告 + 异步 job）
├── agent/                         P7 Agent 域（工具注册表 / ReAct 图 / 预算帽 / 会话持久）
└── interfaces/ providers/         可插拔抽象 + 默认实现（LiteLLM / BGE-M3 / 内存与真后端 stores）
frontend/          React SPA（登录 / 问答 / 浏览 / 分析 / Agent / 管理）
docs/              deploy（部署）· plans（阶段计划，Obsidian vault；年/月/周层 2026-08-31 撤销）· verification（验证报告）
tests/             pytest（真实 PG+pgvector+Neo4j，`-m "not db"` 跑纯逻辑）
```

## 文档导航

- 🚀 [Docker 部署指南](docs/deploy/docker.md) - 一键全栈生产
- 💻 [本地原生部署指南](docs/deploy/native.md) - 无 Docker 生产
- 🧪 [测试/开发环境](docs/deploy/testing.md) - 桩模型冒烟、pytest、前端联调
- 🗺️ [阶段计划](docs/plans/phases/) - P0-P7 阶段任务（唯一计划层；未竟重评议程随计划附录）
- ✅ [验证报告索引](docs/verification/README.md) - 各阶段测试证据
- 🤖 [P7 Agent 模式](docs/plans/phases/P7-agent-mode.md) - 设计决策 / 权限红线 / 评估双轨

## License

[AGPL-3.0-or-later](LICENSE)
