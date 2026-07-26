#!/usr/bin/env bash
# Calliodesmo 一键本地引导（无 Docker 原生部署）。幂等，重复执行安全。
# 数据库需已按 docs/deploy/native.md 原生安装并启动；或用 --sqlite 走零依赖开发模式。
# 用法：scripts/bootstrap.sh [--sqlite]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SQLITE=0
for arg in "$@"; do
  case "$arg" in
    --sqlite) SQLITE=1 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

echo '==> [1/5] 检查 uv'
command -v uv >/dev/null 2>&1 || {
  echo '未找到 uv。安装: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
}
uv --version

echo '==> [2/5] 同步依赖 (uv sync)'
uv sync

echo '==> [3/5] 准备 .env'
if [ ! -f .env ]; then
  cp .env.example .env
  echo '    已从 .env.example 生成 .env（请按需修改密钥与连接串）'
else
  echo '    .env 已存在，跳过'
fi

if [ "$SQLITE" -eq 1 ]; then
  echo '==> 使用 SQLite 开发模式（功能受限，见 docs/deploy/native.md）'
  export CALLIODESMO_DATABASE_URL='sqlite+aiosqlite:///./data/calliodesmo-dev.db'
  mkdir -p data
  export CALLIODESMO_ADMIN_PASSWORD="${CALLIODESMO_ADMIN_PASSWORD:-admin-dev-only}"
fi

echo '==> [4/5] 建表 (db init)'
uv run calliodesmo db init

echo '==> [5/5] 写入内置角色/管理员 (db seed)'
uv run calliodesmo db seed

echo
echo '引导完成。下一步：'
echo '  uv run calliodesmo serve --reload   # 启动 API（/healthz、/docs）'
echo '  uv run pytest                       # 运行测试'