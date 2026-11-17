#!/usr/bin/env bash
# Calliodesmo 一键本地引导（无 Docker 原生部署）。幂等，重复执行安全。
# 前置：PG 16+（含 pgvector 扩展）与 Neo4j 已按 docs/deploy/native.md 安装运行，
# 且 .env 指向它们（CALLIODESMO_DATABASE_URL / CALLIODESMO_NEO4J_URI）。不再支持 SQLite。
# 用法：scripts/bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo '==> [1/7] 检查 uv'
command -v uv >/dev/null 2>&1 || {
  echo '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
}
uv --version

# Windows 控制台默认 GBK，中文输出会乱码；UTF-8 模式让 CLI / 测试输出可读
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo '==> [2/7] 同步依赖（persistence：pgvector / neo4j；agent：LangGraph）'
# 两个 extra 都要装：uv sync 不带某 extra 会把上次装的它卸掉（漏 agent 则 Agent 面 503）
uv sync --extra persistence --extra agent

echo '==> [3/7] 准备 .env'
if [ ! -f .env ]; then
  cp .env.example .env
  echo '    已从 .env.example 生成 .env（请填 PG/Neo4j 连接串与 JWT_SECRET_KEY）'
else
  echo '    .env 已存在，跳过'
fi

echo '==> [4/7] 建表与迁移 (db init)'
uv run calliodesmo db init

echo '==> [5/7] 写入内置角色/管理员/系统账户 (db seed)'
uv run calliodesmo db seed

echo '==> [6/7] 迁移台账核对 (db migrate，幂等)'
uv run calliodesmo db migrate

echo '==> [7/7] 配置与连通体检 (doctor)'
if uv run calliodesmo doctor; then
  echo '    体检通过'
else
  echo '    体检报告问题：按上面提示修 .env 后重跑本脚本（建表与种子已完成）' >&2
fi

# 前端产物缺失时提醒：SPA 由 FastAPI 托管 frontend/dist，不建就是纯 API
if [ -f frontend/package.json ] && [ ! -d frontend/dist ]; then
  echo
  echo '    提示：未找到 frontend/dist，Web UI 需先构建：'
  echo '      cd frontend && npm ci && npm run build'
fi

echo
echo '引导完成。下一步：'
echo '  uv run calliodesmo serve --reload   # 启动 API（/healthz 存活、/readyz 就绪、/docs）'
echo '  curl http://127.0.0.1:8000/readyz   # 组件级就绪自检（数据库 / 图库 / 配置）'
echo '  uv run pytest                       # 全量测试（连 .env 的 PG+Neo4j）'
echo '  uv run pytest -m "not db"           # 仅纯逻辑（CI 等价，不连 DB）'
