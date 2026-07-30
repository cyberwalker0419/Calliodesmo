"""pytest 共享夹具：真实 PG（走 ``.env``）会话与 ASGI 测试客户端。

P4.5 Task 1：测试连真实 PG（专用 schema 隔离 + 每测 TRUNCATE）+ Neo4j（连通），
不再用内存 SQLite。DB 依赖的测试由 ``pytest_collection_modifyitems`` 自动打
``@pytest.mark.db`` 标记，CI 以 ``-m "not db"`` 跳过；全量回归靠本地 ``.env`` 纪律。

隔离策略：所有测试表落在专用 schema ``calliodesmo_test``（经 asyncpg
``server_settings.search_path`` 绑定到 engine 每条连接），与生产 ``public`` 物理隔离；
每个用例开始前 ``TRUNCATE ... RESTART IDENTITY CASCADE`` 清空，保证用例间互不污染。
CLI 测试经 ``cli_db`` 夹具用唯一 schema（monkeypatch ``cli.create_async_engine`` 注入
search_path）隔离，inspect 走 SQLAlchemy 而非 sqlite3。
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base
from calliodesmo.db.session import get_session

# 专用测试 schema：与生产 public 物理隔离（search_path 仅本 schema，避免 public 同名表遮蔽）
_TEST_SCHEMA = "calliodesmo_test"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """用 session/client 夹具的测试自动打 db 标记（CI -m 'not db' 跳过）。"""
    db_marker = pytest.mark.db
    for item in items:
        if any(
            f in item.fixturenames for f in ("session", "client", "neo4j_session", "_pg_engine")
        ):
            item.add_marker(db_marker)


@pytest.fixture(scope="session")
async def _pg_engine():
    """会话级 PG engine：建专用测试 schema + 一次性 create_all。

    两阶段 search_path：
    - **create_all** 用 ``search_path=test``（仅测试 schema）——避免 public 同名表经 has_table
      反射被跳过（遮蔽），确保全部表（含 Task 2 内容层 pgvector 表）建进 test。
    - **DML engine** 用 ``search_path=test,public``——表在 test 优先解析，pgvector 的
      ``vector`` 类型经 public 解析（public 已安装扩展，且不含内容表故无遮蔽）。
    """
    settings = get_settings()
    # 1) 建测试 schema + create_all（search_path 仅 test，避开 public 遮蔽）
    setup_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with setup_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_TEST_SCHEMA}"))
        await conn.execute(text(f"SET search_path TO {_TEST_SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    await setup_engine.dispose()
    # 2) DML engine：search_path=test,public（Vector 经 public 解析，表在 test 优先）
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f"{_TEST_SCHEMA},public"}},
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(_pg_engine) -> AsyncIterator[AsyncSession]:
    """每用例独立会话：测前 TRUNCATE 全表清空，保证隔离。"""
    table_names = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    if table_names:
        async with _pg_engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(_pg_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI 测试客户端：复用 session 夹具（同 engine、同会话），覆盖 get_session 依赖。"""
    from calliodesmo.api.app import create_app

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def neo4j_session() -> AsyncIterator:
    """Neo4j 连通夹具：每测前清空全图（DETACH DELETE），保证隔离。

    用例需图库时显式请求本夹具。单进程串行跑安全；并行跑需改用独立 database。
    """
    from neo4j import AsyncGraphDatabase

    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    await driver.verify_connectivity()
    async with driver.session() as s:
        await s.run("MATCH (n) DETACH DELETE n")
    yield driver
    await driver.close()


# ---------- CLI 测试：唯一 PG schema 隔离 ----------


async def _exec_ddl(schema: str, *, drop: bool) -> None:
    """在一次性 engine 上 CREATE/DROP schema（独立 loop，避免污染会话级 _pg_engine）。"""
    settings = get_settings()
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with eng.begin() as conn:
            if drop:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            else:
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    finally:
        await eng.dispose()


async def _create_all_in_schema(schema: str) -> None:
    """在指定 schema 预建全部表（search_path 仅该 schema，避开 public 遮蔽；含 pgvector 表）。"""
    settings = get_settings()
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with eng.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await eng.dispose()


@pytest.fixture
def cli_db(monkeypatch) -> str:
    """CLI 测试专用：唯一 PG schema 隔离。

    asyncpg 无法经 URL 传 search_path，故 monkeypatch ``calliodesmo.cli.create_async_engine``
    注入 ``connect_args.server_settings.search_path=<schema>``（不含 public，避免遮蔽）；
    CLI 各命令在建 engine 时统一带上。用例结束 DROP schema CASCADE。返回 schema 名供 inspect 复用。
    """
    import calliodesmo.cli as cli_mod

    schema = f"cli_test_{uuid.uuid4().hex[:10]}"
    # 先清 get_settings 缓存：避免先前 sqlite 用例残留的陈旧缓存（setenv sqlite 后 teardown 未清）
    get_settings.cache_clear()
    # 预建 schema + create_all（search_path 仅 schema，避开 public 遮蔽；含 Task 2 pgvector 表）
    asyncio.run(_create_all_in_schema(schema))
    real_create_async_engine = cli_mod.create_async_engine

    def patched_create_async_engine(url, **kwargs):  # type: ignore[no-untyped-def]
        # search_path=schema,public：表在 schema 优先，pgvector vector 类型经 public 解析。
        # 已预建表 -> CLI 的 db init create_all 幂等跳过，不会遮蔽到 public。
        kwargs.setdefault("connect_args", {})["server_settings"] = {
            "search_path": f"{schema},public"
        }
        return real_create_async_engine(url, **kwargs)

    monkeypatch.setattr(cli_mod, "create_async_engine", patched_create_async_engine)
    monkeypatch.setenv("CALLIODESMO_ADMIN_PASSWORD", "admin-pw")
    get_settings.cache_clear()
    yield schema
    get_settings.cache_clear()
    asyncio.run(_exec_ddl(schema, drop=True))


@pytest.fixture
def cli_inspect(cli_db):
    """CLI 测试 inspect：返回同步 callable ``inspect(sql, params=None) -> list[row]``。

    封装 ``cli_query``（async）的 ``asyncio.run``，供同步 CLI 测试直接用，替代 sqlite3 直查。
    """

    def _inspect(sql: str, params: dict | None = None) -> list:
        return asyncio.run(cli_query(cli_db, sql, params))

    return _inspect


async def cli_query(schema: str, sql: str, params=None) -> list:
    """CLI 测试 inspect 辅助：在指定 schema 上执行 SQL 返回行列表（替代 sqlite3 直查）。"""
    settings = get_settings()
    eng = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    try:
        async with eng.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return list(result.fetchall())
    finally:
        await eng.dispose()
