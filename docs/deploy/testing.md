---
title: 测试 / 开发环境
type: guide
tags:
  - deploy
  - testing
created: 2026-08-20
---
# 测试 / 开发环境

> 本地跑测试套件、桩模型冒烟、前端联调。生产部署见 [docker.md](docker.md) / [native.md](native.md)。

## 0. 前置

- [uv](https://docs.astral.sh/uv/getting-started/installation/)（自动准备 Python 3.12）。
- 可用的 **PostgreSQL 16+（pgvector）+ Neo4j**（本地或局域网自建；测试会真实连库，`.env` 驱动）。

## 1. 安装依赖

```bash
uv sync --extra persistence    # 核心依赖 + pgvector/neo4j（测试与运行必需）
# 可选：uv sync --extra embedding-local  # 本地 BGE-M3
# 可选：uv sync --extra search-rerank    # 本地重排
```

## 2. 配置 .env（真后端 + 离线桩模型）

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

数据库/图库用真实 PG+Neo4j（连接串默认即本地，无需改）：

```dotenv
CALLIODESMO_DATABASE_URL=postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo
CALLIODESMO_NEO4J_URI=bolt://localhost:7687
CALLIODESMO_NEO4J_USER=neo4j
CALLIODESMO_NEO4J_PASSWORD=calliodesmo
```

模型三段设为离线桩（无网络，仅验证管线机制）：

```dotenv
CALLIODESMO_LLM_MODEL=test/stub      # 离线桩 LLM（返回固定抽取）
CALLIODESMO_EMBEDDING_PROVIDER=hash
CALLIODESMO_EMBEDDING_DIMENSION=64
CALLIODESMO_RERANKER_PROVIDER=none

CALLIODESMO_ADMIN_PASSWORD=admin-123456   # 仅 db seed 用
```

## 3. 跑测试套件

```bash
uv run calliodesmo db init     # 建表（幂等；PG 需已 CREATE EXTENSION vector）
uv run pytest -v              # 全量测试（连 .env 的 PG+Neo4j）
uv run pytest -m "not db"     # 仅纯逻辑（CI 等价，不连库）
uv run ruff check .
uv run ruff format --check .
```

隔离原理：每用例在专用 PG schema `calliodesmo_test` 内每测 TRUNCATE（与生产 `public` 物理隔离）；CLI 测试经 `cli_db` 夹具唯一 schema；Neo4j 经 `neo4j_session` 每测清图；`sys.modules` 桩隔离 litellm/uvicorn。DB 依赖用例自动打 `@pytest.mark.db`，CI 以 `-m "not db"` 跳过。

> P4.5 起不再有 SQLite 零依赖模式：测试与运行一律连真实 PG+pgvector+Neo4j。

## 4. 冒烟验证（桩模型 + 演示数据）

```bash
uv run calliodesmo db init && uv run calliodesmo db seed
uv run calliodesmo serve --seed-demo    # 对 data/demo/ 跑桩 ECL，启动后 http://127.0.0.1:8000
```

登录 `admin` / `admin-123456`，走问答 / 浏览 / 管理。

```bash
curl http://127.0.0.1:8000/healthz
```

> `--seed-demo`：对 `data/demo/` 在 serve 进程内跑 ECL，产物落盘 `data/demo/seed-cache.json`，二次启动命中缓存跳过 LLM。桩抽取是写死的，只验证管线/UI/权限，**不验证抽取质量**。

## 5. 前端开发（frontend/）

```bash
cd frontend && npm ci
npm run dev      # Vite dev server（5173，/api 代理到 8200）
npm run build    # tsc -b && vite build -> dist/（由后端 StaticFiles 同源托管）
npm test         # vitest
npm run lint     # tsc -b --noEmit（严格类型检查）
```

后端联调：另开 `uv run calliodesmo serve --seed-demo --port 8200`（dev proxy 目标即 8200）。

## 6. CI

`.github/workflows/ci.yml`：后端 job `uv sync -> ruff check/format -> pytest -m "not db"`；前端 job `npm ci -> npm run build -> vitest`。全量 DB 回归只在本地 `.env` 跑。
