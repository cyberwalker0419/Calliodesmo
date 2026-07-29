---
title: Docker 部署指南
type: guide
tags:
  - deploy
created: 2026-07-27
---
# Docker 部署指南

> [!info] 适用场景
> 一键拉起全栈：PostgreSQL+pgvector + Neo4j + 应用（FastAPI）。适合不想原生装基础设施、快速验证或容器化生产部署。无 Docker 的原生路径（测试/开发 + 生产）见 [[docs/deploy/native|原生部署指南]]。关联：[[docs/plans/roadmap|年计划]]。

## 0. 组件

`docker-compose.yml` 编排三个服务：

| 服务 | 镜像 | 作用 | 端口 |
| --- | --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 情景层 + 摘要层（文本块 / 向量 / 社区） | 5432 |
| `neo4j` | `neo4j:5` | 语义层（实体关系图） | 7474 浏览器 / 7687 Bolt |
| `app` | 本地构建 `calliodesmo:latest` | FastAPI + CLI（自动 init/seed/serve） | 8000 |

`Dockerfile` 多阶段构建（builder 装 uv 依赖，runtime 精简）；`docker-entrypoint.sh` 自动 `db init` -> `db seed`（设了管理员密码才执行）-> `serve`。

## 1. 前置

- Docker Engine + Docker Compose v2。
- `.env`（见下）。

## 2. 配置 .env

```bash
cp .env.example .env
```

> 容器内连接串由 compose 覆盖为服务名（`postgres` / `neo4j`），**无需手改** `DATABASE_URL` / `NEO4J_URI`。

关键项：

```dotenv
CALLIODESMO_ADMIN_PASSWORD=<初始管理员密码>   # 设了才会 seed 管理员
CALLIODESMO_JWT_SECRET_KEY=<≥32 字节随机串>     # 生产必改
```

### 模型配置（三层）

容器经 `host.docker.internal` 访问**宿主机**的本地模型服务（Ollama / LM Studio / llama.cpp）；compose 已设 `extra_hosts: host.docker.internal:host-gateway`（Linux 也支持）。远端云模型直接填云端地址。

```dotenv
# 例：宿主机 llama.cpp 三服务
CALLIODESMO_LLM_MODEL=openai/local-model
CALLIODESMO_LLM_API_KEY=local
CALLIODESMO_LLM_API_BASE=http://host.docker.internal:8081/v1
CALLIODESMO_EMBEDDING_PROVIDER=remote
CALLIODESMO_EMBEDDING_API_BASE=http://host.docker.internal:8082
CALLIODESMO_EMBEDDING_MODEL=bge-m3
CALLIODESMO_EMBEDDING_DIMENSION=1024
CALLIODESMO_RERANKER_PROVIDER=remote
CALLIODESMO_RERANKER_API_BASE=http://host.docker.internal:8083
CALLIODESMO_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

> 三层（LLM/嵌入/重排）独立可切，详见 [[docs/deploy/native#8-3-模型配置三层独立可切换|原生指南 §8.3]]。离线桩（`test/stub`+`hash`+`none`）也可在容器内用，但仅验证管线机制。

> [!tip] 跳过 BGE-M3 重依赖（减小镜像）
> 默认 `INSTALL_EMBEDDING=1`（镜像含本地 BGE-M3，较大）。用远端嵌入或 hash 桩时设 `0`：
> ```bash
> CALLIODESMO_INSTALL_EMBEDDING=0 docker compose up -d --build
> ```

## 3. 启动

```bash
docker compose up -d --build   # 构建 app + 起 pg/neo4j/app（app 自动 db init/seed/serve）
docker compose logs -f app     # 跟踪启动日志（等 app healthy）
```

访问：
- 应用：http://127.0.0.1:8000（SPA + API + `/docs`）
- Neo4j 浏览器：http://127.0.0.1:7474（`neo4j` / `calliodesmo`）

健康检查：`docker compose ps`（app 带 `healthcheck` curl `/healthz`）。

## 4. 建图（ingest）

文档放宿主机 `./data/docs/`（挂载到容器 `/app/data`）：

```bash
docker compose exec app calliodesmo ingest /app/data/docs
docker compose exec app calliodesmo ingest /app/data/docs \
  --dump-json /app/data/dump.json --dump-html /app/data/graph.html
```

演示数据（内存 stores 模式进程内自灌）：

```bash
docker compose exec app calliodesmo serve --seed-demo     # 容器内同样支持
```

## 5. 运维

```bash
docker compose logs -f app          # 应用日志
docker compose ps                   # 状态（含 healthcheck）
docker compose restart app          # 重启应用
docker compose down                 # 停止（保留卷数据）
docker compose down -v              # 停止并删数据卷（慎用：清库）
```

卷：`pgdata`（Postgres）、`neo4jdata`（Neo4j）、`hfcache`（BGE-M3 模型缓存，避免重复下载）、`./data`（文档 / SQLite，宿主机挂载）。

## 6. 生产加固

- **密钥**：`JWT_SECRET_KEY` ≥32 字节随机；`.env` 不入库（`.gitignore` 已覆盖）。
- **反向代理**：Nginx/Caddy 终结 TLS 转发 8000（或 compose 加反代服务）。
- **资源**：Neo4j / BGE-M3 吃内存，按机器在 compose 调 `deploy.resources`。
- **升级**：`git pull && docker compose up -d --build`（entrypoint 幂等 init/seed）。
- **备份**：`docker compose exec postgres pg_dump -U calliodesmo calliodesmo > backup.sql` / `docker compose exec neo4j neo4j-admin database dump --to-path=/data neo4j`。

## 7. 故障排查

| 现象 | 解决 |
| --- | --- |
| app 一直重启 | `docker compose logs app` 看报错（多为模型 key / 连接） |
| 连不上宿主机模型 | 宿主机服务需 `--host 0.0.0.0`；`.env` 用 `host.docker.internal`；防火墙放行端口 |
| BGE-M3 首次拉模型慢 | 命中 `hfcache` 卷后秒启；或 `INSTALL_EMBEDDING=0` 用远端/hash |
| 端口占用 | 改 compose `ports` 映射 |
| `db seed` 未执行 | 未设 `CALLIODESMO_ADMIN_PASSWORD`；entrypoint 跳过 seed |
| 容器内 ingest 数据 serve 看不到 | CLI ingest 跨进程；演示数据走 `serve --seed-demo`（同进程内存 stores） |
| 镜像构建慢 / 拉取失败 | 确认网络；`uv` 缓存层 `--mount=type=cache` 已启用 |