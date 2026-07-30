"""Neo4jGraphStore 契约测试（P4.5 Task 2 Step 3）。

走真实 Neo4j（``neo4j_session`` 夹具清图）+ PG 镜像（``_pg_engine`` factory），
验证 upsert MERGE 幂等 / get_entity + visible_to / neighbors / subgraph BFS / list_*，
对齐 InMemoryGraphStore 语义。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore


def _ctx(user_id, *, clearance=ClearanceLevel.SECRET, project_ids=(), team_ids=()) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        project_ids=frozenset(project_ids),
        team_ids=frozenset(team_ids),
    )


def _ent(
    name,
    owner,
    *,
    type="org",
    desc="d",
    scope=LibraryScope.PERSONAL,
    access=ClearanceLevel.INTERNAL,
    chunks=("c#0",),
) -> EntityRecord:
    return EntityRecord(
        name=name,
        type=type,
        description=desc,
        source_chunk_ids=list(chunks),
        template_conforming=False,
        metadata={},
        access_level=access,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
        project_id=uuid.uuid4() if scope == LibraryScope.PROJECT else None,
        team_id=uuid.uuid4() if scope == LibraryScope.TEAM else None,
    )


def _rel(src, tgt, owner, *, type="developed", scope=LibraryScope.PERSONAL) -> RelationRecord:
    return RelationRecord(
        source=src,
        target=tgt,
        type=type,
        description="",
        source_chunk_ids=["c#0"],
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
        project_id=None,
        team_id=None,
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


async def test_upsert_and_get_entity(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    await store.upsert_graph([_ent("OpenAI", owner)], [])
    got = await store.get_entity("OpenAI", access=_ctx(owner))
    assert got is not None
    assert got.name == "OpenAI"
    assert got.owner_id == owner
    # 别人的 personal 实体不可见
    other = uuid.uuid4()
    assert await store.get_entity("OpenAI", access=_ctx(other)) is None
    # 不存在
    assert await store.get_entity("Nope", access=_ctx(owner)) is None


async def test_upsert_idempotent_merge(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    await store.upsert_graph([_ent("OpenAI", owner, desc="v1")], [])
    await store.upsert_graph([_ent("OpenAI", owner, desc="v2")], [])
    got = await store.get_entity("OpenAI", access=_ctx(owner))
    assert got.description == "v2"  # MERGE 覆盖


async def test_neighbors(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    await store.upsert_graph(
        [_ent("OpenAI", owner), _ent("GPT-4", owner)],
        [_rel("OpenAI", "GPT-4", owner)],
    )
    nodes, rels = await store.neighbors("OpenAI", access=_ctx(owner))
    assert {n.name for n in nodes} == {"GPT-4"}
    assert len(rels) == 1
    assert rels[0].source == "OpenAI" and rels[0].target == "GPT-4"


async def test_subgraph_bfs(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    # OpenAI -> GPT-4 -> Tokenizer
    await store.upsert_graph(
        [_ent("OpenAI", owner), _ent("GPT-4", owner), _ent("Tokenizer", owner)],
        [_rel("OpenAI", "GPT-4", owner), _rel("GPT-4", "Tokenizer", owner)],
    )
    view = await store.subgraph(["OpenAI"], hops=2, limit=10, access=_ctx(owner))
    assert {n.name for n in view.nodes} == {"OpenAI", "GPT-4", "Tokenizer"}
    assert view.expanded_seeds == ["OpenAI"]
    assert not view.truncated
    assert len(view.edges) == 2
    # hops=1 只扩一跳
    view1 = await store.subgraph(["OpenAI"], hops=1, limit=10, access=_ctx(owner))
    assert {n.name for n in view1.nodes} == {"OpenAI", "GPT-4"}


async def test_subgraph_limit_truncates(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    await store.upsert_graph(
        [_ent("A", owner), _ent("B", owner), _ent("C", owner)],
        [_rel("A", "B", owner), _rel("A", "C", owner)],
    )
    view = await store.subgraph(["A"], hops=1, limit=2, access=_ctx(owner))
    assert view.truncated  # A + 1 neighbor 达 limit=2
    assert len(view.nodes) == 2


async def test_list_visibility(neo4j_session, factory):
    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    other = uuid.uuid4()
    await store.upsert_graph(
        [_ent("mine", owner), _ent("yours", other)],
        [],
    )
    listed = await store.list_entities(access=_ctx(owner))
    assert {e.name for e in listed} == {"mine"}
    listed2 = await store.list_entities(access=_ctx(other))
    assert {e.name for e in listed2} == {"yours"}


async def test_pg_mirror_written(neo4j_session, factory):
    """Neo4j 写入同步镜像到 PG entities 表（供 visible_to 聚合 fallback）。"""
    from sqlalchemy import select

    from calliodesmo.db.models_content import EntityRecordORM

    store = Neo4jGraphStore(neo4j_session, factory)
    owner = uuid.uuid4()
    await store.upsert_graph([_ent("Mirrored", owner)], [])
    async with factory() as s:
        rows = (
            (await s.execute(select(EntityRecordORM).where(EntityRecordORM.name == "Mirrored")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].owner_id == owner
