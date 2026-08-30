"""agent extra 懒导入守卫：缺依赖友好报错（API 层转 503，同 ingest / analyze 惯例）。

langgraph 家族依赖走 ``optional-dependencies`` ``agent``（P7 T2 钉版）：
``langgraph>=1.2,<2`` + ``langgraph-checkpoint-postgres>=3.1.1,<4`` +
``psycopg[binary]>=3.2,<3.4`` + ``psycopg-pool>=3.2,<3.4``。
禁裸 psycopg（Windows 无系统 libpq）与 ``psycopg[c]``（无 Windows wheel 触发源码编译）；
``langgraph-checkpoint-postgres`` 自身依赖裸 psycopg，须以 ``psycopg[binary]`` 覆盖提供
psycopg-binary（cp311 win_amd64 wheel）。下限 3.1.1 = CVE-2026-71433 修复版（GHSA-47pj-3jcm-6whg）。
"""

from __future__ import annotations

AGENT_EXTRA_HINT = "uv sync --extra agent"


def require_langgraph():
    """懒导入 langgraph 核心；缺依赖 RuntimeError（友好报错含安装指令）。"""
    try:
        import langgraph
    except ImportError as exc:
        raise RuntimeError(f"缺少 agent extra 依赖（langgraph）。安装：{AGENT_EXTRA_HINT}") from exc
    return langgraph


def require_pg_checkpointer():
    """懒导入 AsyncPostgresSaver；缺依赖 RuntimeError（友好报错含安装指令）。"""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        raise RuntimeError(
            "缺少 agent extra 依赖（langgraph-checkpoint-postgres / psycopg[binary]）。"
            f"安装：{AGENT_EXTRA_HINT}"
        ) from exc
    return AsyncPostgresSaver
