"""异步 engine 与请求级会话工厂。

P9 可用化：池参数与 SQL 回显从配置来（``db_pool_size`` / ``db_max_overflow`` /
``db_echo``）。``echo`` 不再绑 ``debug``——开着 DEBUG 就把每条 SQL 打到 stdout，
并发检索时序列化在管道写出上，实测显著抬高 p95。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from calliodesmo.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级异步会话。"""
    async with SessionLocal() as session:
        yield session
