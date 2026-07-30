#!/usr/bin/env bash
# Calliodesmo 一键本地引导（无 Docker 原生部署）。幂等，重复执行安全。
# 前置：PG 16+（含 pgvector 扩展）与 Neo4j 已按 docs/deploy/native.md 安装运行，
# 且 .env 指向它们（CALLIODESMO_DATABASE_URL / CALLIODESMO_NEO4J_URI）。不再支持 SQLite。
# 用法：scripts/bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo '==> [1/5] 检查 uv'
command -v uv >/dev/null 2>&1 || {
  echo '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
}
uv --version

echo '==> [2/5] 同步依赖（含 persistence extra：pgvector / neo4j）'
uv sync --extra persistence

echo '==> [3/5] 准备 .env'
if [ ! -f .env ]; then
  cp .env.example .env
  echo '    已从 .env.example 生成 .env（请填 PG/Neo4j 连接串与 JWT_SECRET_KEY）'
else
  echo '    .env 已存在，跳过'
fi

echo '==> [4/5] 建表 (db init)'
uv run calliodesmo db init

echo '==> [5/5] 写入内置角色/管理员/系统账户 (db seed)'
uv run calliodesmo db seed

echo
echo '引导完成。下一步：'
echo '  uv run calliodesmo serve --reload   # 启动 API（/healthz、/docs）'
echo '  uv run pytest                       # 全量测试（连 .env 的 PG+Neo4j）'
echo '  uv run pytest -m "not db"           # 仅纯逻辑（CI 等价，不连 DB）'
