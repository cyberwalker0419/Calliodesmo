#!/bin/sh
# 容器入口：按需建表 + 种子（设了管理员密码时）+ 启动服务。
# 用法：
#   docker run calliodesmo                         # 默认：init + seed(可选) + serve
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

# 3) 执行传入命令；无参则默认 serve
if [ "$#" -gt 0 ]; then
    exec calliodesmo "$@"
else
    exec calliodesmo serve --host 0.0.0.0 --port 8000
fi