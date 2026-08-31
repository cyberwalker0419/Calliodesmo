"""checkpointer 装配：InMemory | AsyncPostgresSaver（P7 决策 2 双轨）。

离线测试 InMemorySaver；运行态与 ``@pytest.mark.db`` 集成测试用官方
AsyncPostgresSaver——独立 ``psycopg[binary]`` ``AsyncConnectionPool``（与
SQLAlchemy engine 分池、指向同一 PG），``autocommit=True`` + ``dict_row``
（检查单坑①②）；``setup()`` 幂等须显式调用（lifespan，坑①）。
**不自写 SQLAlchemy checkpointer**（官方 psycopg saver 有 conformance 背书）。
"""

from __future__ import annotations

import asyncio
import sys

from calliodesmo.agent.extras import require_pg_checkpointer


def selector_loop_factory(use_subprocess: bool = False):
    """uvicorn 自定义 loop 工厂：Windows 下 uvicorn 默认 ProactorEventLoop，
    而 psycopg 异步仅兼容 selector——serve 经 ``loop=`` 注入本工厂（asyncpg /
    uvicorn 同兼容 selector）。回 loop 实例（asyncio.Runner 以零参调用本工厂）。"""
    return asyncio.SelectorEventLoop()


def serve_loop_kwargs() -> dict:
    """serve 装配：loop 走 uvicorn 平台默认（Windows Proactor 服务 asyncpg 主库；
    Linux 默认 selector 同时兼容 asyncpg 与 psycopg）。"""
    return {}


def build_runtime_checkpointer(database_url: str, *, schema: str | None = None):
    """运行态 checkpointer 平台路由（P7 T11 决策 2 的 Windows 兼容注记）。

    - Linux：selector loop 同时兼容 asyncpg（主库）与 psycopg（checkpointer）->
      AsyncPostgresSaver（执行态跨重启持久）。
    - Windows：asyncpg 需 Proactor 而 psycopg 需 Selector，单 loop 不可兼得——
      开发态降级 InMemorySaver（多轮在单进程内仍续接；ORM 三表恒为 system of
      record，重启续接留痕未竟：锚点 2026-W49 压测批同评跨 loop 桥接方案）。
    """
    if sys.platform == "win32":
        import logging

        logging.getLogger(__name__).warning(
            "Windows 单 loop 不可兼得 asyncpg/psycopg——agent checkpointer 降级 InMemory"
        )
        return build_checkpointer(None)
    return build_checkpointer(database_url, schema=schema)


def conninfo_from_database_url(url: str) -> str:
    """SQLAlchemy DSN -> psycopg conninfo（去 driver 方案段）。"""
    for scheme in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(scheme):
            return "postgresql://" + url[len(scheme) :]
    return url


def build_checkpointer(database_url: str | None, *, schema: str | None = None):
    """``None`` -> InMemorySaver（离线）；有 URL -> AsyncPostgresSaver（独立池）。

    参数:
        database_url: SQLAlchemy 形式数据库 URL；None 表示离线内存轨。
        schema: 非 None 时经 ``options=-c search_path=...`` 隔离（测试 schema）。
    """
    if database_url is None:
        require_pg_checkpointer()  # 守卫一致性：内存轨也须 extra 在场（langgraph 家族）
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool_kwargs: dict = {"autocommit": True, "row_factory": dict_row}
    if schema:
        pool_kwargs["options"] = f"-c search_path={schema},public"
    pool = AsyncConnectionPool(
        conninfo_from_database_url(database_url), kwargs=pool_kwargs, open=False
    )
    return AsyncPostgresSaver(pool)
