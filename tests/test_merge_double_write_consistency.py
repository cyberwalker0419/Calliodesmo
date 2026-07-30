"""P4.5 Task 4 Step 4：Neo4j（权威）+ PG 镜像双写一致性。

Neo4j 与 PG 镜像双写非原子（两轨独立事务）。策略：**PG 镜像先写、Neo4j 权威后写**，
强制不变式"Neo4j 写成功 ⇒ PG 镜像已写"（PG 是 Neo4j 的超集）：
- PG 镜像写失败 -> 立即抛出，Neo4j 不写 -> 权威未污染（不留半写）。
- Neo4j 写失败（PG 已写）-> 读以 Neo4j 为准故读不见 -> 可检测；两端 upsert 幂等 -> 可重试收敛。

中途失败用模拟故障 driver / 故障 factory 注入，断言"不留半写 / 可检测可重试"。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytest.importorskip("pgvector")  # CI 未装 persistence extra 时跳过收集
pytest.importorskip("neo4j")

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_content import EntityRecordORM
from calliodesmo.interfaces.graph_store import EntityRecord
from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore


def _ctx(user_id) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


def _ent(name, owner) -> EntityRecord:
    return EntityRecord(
        name=name,
        type="organization",
        description="d",
        source_chunk_ids=["c#0"],
        template_conforming=False,
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
        project_id=None,
        team_id=None,
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


class _FailingPGSession:
    """模拟 PG 镜像写失败：execute 抛异常（自管 async context manager）。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        raise RuntimeError("PG mirror down")

    async def commit(self):
        pass


def _failing_pg_factory():
    return _FailingPGSession()


class _FailingNeo4jSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, *args, **kwargs):
        raise RuntimeError("Neo4j down")


class _FailingNeo4jDriver:
    def session(self):
        return _FailingNeo4jSession()


async def test_pg_mirror_failure_leaves_neo4j_clean(neo4j_session, factory):
    """PG 镜像写失败 -> Neo4j 权威不被污染（不留半写：Neo4j 写成功 ⇒ PG 已写）。

    顺序保证（PG 先、Neo4j 后）：PG 抛出即中止，Neo4j 块不执行。若顺序相反（Neo4j 先），
    Neo4j 已落数据而 PG 缺失——半写，本测试即捕获此回归。
    """
    owner = uuid.uuid4()
    store = Neo4jGraphStore(neo4j_session, _failing_pg_factory)
    with pytest.raises(RuntimeError, match="PG mirror down"):
        await store.upsert_graph([_ent("HalfWrite", owner)], [])

    # Neo4j 权威应无此实体（用真 factory 的核对 store 经同一 driver 读）
    check = Neo4jGraphStore(neo4j_session, factory)
    assert await check.get_entity("HalfWrite", access=_ctx(owner)) is None
    assert "HalfWrite" not in {e.name for e in await check.list_entities(access=_ctx(owner))}


async def test_neo4j_failure_leaves_pg_superset_retryable(neo4j_session, factory):
    """Neo4j 写失败（PG 已写）-> PG 镜像是超集；读以 Neo4j 为准故可检测；重试幂等收敛。"""
    owner = uuid.uuid4()
    store = Neo4jGraphStore(_FailingNeo4jDriver(), factory)
    with pytest.raises(RuntimeError, match="Neo4j down"):
        await store.upsert_graph([_ent("RetryMe", owner)], [])

    # PG 镜像已写（超集）：直接查 PG entities 表
    async with factory() as s:
        rows = (
            (await s.execute(select(EntityRecordORM).where(EntityRecordORM.name == "RetryMe")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].owner_id == owner

    # 读以 Neo4j 为准 -> Neo4j 无此实体 -> 读不见（可检测：操作看起来未完成）
    check = Neo4jGraphStore(neo4j_session, factory)
    assert await check.get_entity("RetryMe", access=_ctx(owner)) is None

    # 重试（真 driver + 同 factory）：两端 upsert 幂等 -> 收敛，Neo4j 也有
    retry = Neo4jGraphStore(neo4j_session, factory)
    await retry.upsert_graph([_ent("RetryMe", owner)], [])
    got = await retry.get_entity("RetryMe", access=_ctx(owner))
    assert got is not None and got.name == "RetryMe"
    # PG 镜像仍一行（幂等，未重复）
    async with factory() as s:
        rows = (
            (await s.execute(select(EntityRecordORM).where(EntityRecordORM.name == "RetryMe")))
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_double_write_both_consistent_on_success(neo4j_session, factory):
    """正常路径：Neo4j（权威）与 PG 镜像双写一致（回归守卫）。"""
    owner = uuid.uuid4()
    store = Neo4jGraphStore(neo4j_session, factory)
    await store.upsert_graph([_ent("Consistent", owner)], [])

    got = await store.get_entity("Consistent", access=_ctx(owner))
    assert got is not None and got.owner_id == owner
    async with factory() as s:
        rows = (
            (await s.execute(select(EntityRecordORM).where(EntityRecordORM.name == "Consistent")))
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].owner_id == owner
