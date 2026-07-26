# syntax=docker/dockerfile:1.7
# Calliodesmo 应用镜像（FastAPI + Typer CLI）。
# 多阶段构建：builder 用 uv 安装依赖，runtime 精简。
# 基础设施（PostgreSQL+pgvector / Neo4j）见 docker-compose.yml。

# ---------- builder ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

ARG INSTALL_EMBEDDING=1

# 先装依赖（仅 pyproject 声明，源码尚未拷入）。--no-deps 留到源码就位后。
# 用 uv export + pip install 锁依赖，避免 -e .（editable 需源码）。
COPY pyproject.toml ./
# 写一个最小 stub 让 -e "." 能在无源码时也解析元数据依赖：
#   hatchling 需 src/ 存在，故先建空包占位。
RUN mkdir -p src/calliodesmo && touch src/calliodesmo/__init__.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv && \
    if [ "$INSTALL_EMBEDDING" = "1" ]; then \
      uv pip install --python /app/.venv/bin/python -e ".[embedding-local]"; \
    else \
      uv pip install --python /app/.venv/bin/python -e "."; \
    fi

# 拷入真实源码，重新以 --no-deps 安装本包（覆盖 stub，依赖已就位不重装）
COPY src/ ./src/
COPY README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv/bin/python -e "." --no-deps

# ---------- runtime ----------
FROM python:3.12-slim-bookworm AS runtime

# 运行时依赖：libgomp（FlagEmbedding/numpy OpenMP）、tini（PID1 信号处理）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 tini ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 calliodesmo \
    && useradd --system --uid 1001 --gid calliodesmo --create-home --home-dir /app appuser

WORKDIR /app

COPY --from=builder --chown=appuser:calliodesmo /app/.venv /app/.venv
COPY --chown=appuser:calliodesmo docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /app/data && chown -R appuser:calliodesmo /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/data/hf-cache

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["serve"]