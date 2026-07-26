# Calliodesmo

三层知识图谱驱动的智能情报分析平台（GraphRAG + LlamaIndex/LangGraph，LLM/嵌入可切换）。

## 快速开始

应用层始终经 uv 本地运行；基础设施（PostgreSQL+pgvector / Neo4j）二选一：**Docker** 或**原生安装**（见 [docs/deploy/native.md](docs/deploy/native.md)）。

### 路径 A：Docker（省心）

```bash
uv sync                      # 安装依赖（uv 自动准备 Python 3.12）
cp .env.example .env         # 配置密钥与连接串
docker compose up -d         # 启动 PostgreSQL+pgvector 与 Neo4j
uv run calliodesmo db init   # 建表
uv run calliodesmo db seed   # 写入默认角色/权限与管理员
uv run calliodesmo serve     # 启动 API：http://127.0.0.1:8000（/healthz、/docs）
```

### 路径 B：原生（无 Docker）

```powershell
# Windows：一键引导（幂等）；-Sqlite 走零依赖开发模式
.\scripts\bootstrap.ps1
```

```bash
# Linux / macOS：一键引导（幂等）；--sqlite 走零依赖开发模式
scripts/bootstrap.sh
```

原生安装 PostgreSQL 16 + pgvector 与 Neo4j 的完整步骤、systemd/Windows 服务配置、生产要点见 **[docs/deploy/native.md](docs/deploy/native.md)**。

### 验证

```bash
uv run pytest                # 运行测试（内存 SQLite，无需任何外部服务）
```

## 计划文档

实施路线与月/周/阶段计划见 [docs/plans/roadmap.md](docs/plans/roadmap.md)（Obsidian vault 根为本仓库）。