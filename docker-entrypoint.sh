#!/bin/sh
# 容器入口：建表与迁移 + 种子（设了管理员密码时）+ 配置体检 + 启动服务。
# 用法：
#   docker run calliodesmo                         # 默认：init + seed(可选) + doctor + serve
#   docker run calliodesmo serve --host 0.0.0.0    # 透传 CLI 参数
#   docker run calliodesmo ingest /app/data/docs   # 跑其他子命令（跳过 serve）
set -e

echo "[entrypoint] CALLIODESMO_ENVIRONMENT=${CALLIODESMO_ENVIRONMENT:-development}"

# 1) 建表（幂等）
echo "[entrypoint] db init ..."
calliodesmo db init

# 2) 种子（仅在显式提供管理员密码时；避免无密码重复 seed 报错）
if [ -n "$CALLIODESMO_ADMIN_PASSWORD" ]; then
    echo "[entrypoint] db seed ..."
    calliodesmo db seed
else
    echo "[entrypoint] 跳过 db seed（未设 CALLIODESMO_ADMIN_PASSWORD）"
fi

# 3) 配置与连通体检：只报问题不阻断启动（首启常未配模型 key）
echo "[entrypoint] doctor（配置体检）..."
calliodesmo doctor --check-db || echo "[entrypoint] doctor 报告问题（不阻断启动；见 docs/deploy/docker.md）"

# 4) 执行传入命令；无参则默认 serve
if [ "$#" -gt 0 ]; then
    exec calliodesmo "$@"
else
    exec calliodesmo serve --host 0.0.0.0 --port 8000
fi