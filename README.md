# Calliodesmo

三层知识图谱驱动的智能情报分析平台（GraphRAG + LlamaIndex/LangGraph，LLM/嵌入可切换）。

## 快速开始

```bash
uv sync                      # 安装依赖（uv 自动准备 Python 3.12）
cp .env.example .env         # 配置密钥与连接串
docker compose up -d         # 启动 PostgreSQL+pgvector 与 Neo4j
uv run calliodesmo db init   # 建表
uv run calliodesmo db seed   # 写入默认角色/权限与管理员
uv run pytest                # 运行测试
```

## 计划文档

实施路线与月/周/阶段计划见 [docs/plans/roadmap.md](docs/plans/roadmap.md)（Obsidian vault 根为本仓库）。