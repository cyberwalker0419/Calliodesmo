"""P4.5 Task 2 Step 6 贯通测试：ingest -> 新 store 实例（模拟重启）-> 数据仍在。

证明三 store 真后端持久化：写入后用全新 store 实例（同一 PG/Neo4j）仍可读回，
即"进程重启不丢数据"。store 级测试（不经 AppStores 单例），用 ``_pg_engine`` factory
+ ``neo4j_session`` driver 隔离于 calliodesmo_test schema / 干净 Neo4j 库。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, User
from calliodesmo.config import get_settings
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.pg_community_store import PgCommunityStore
from calliodesmo.providers.pg_vector_store import PgVectorStore

_DIM = get_settings().embedding_dimension


def _ctx(user_id) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


async def _make_user(factory) -> uuid.UUID:
    async with factory() as s:
        u = User(username=f"rt-{uuid.uuid4().hex[:6]}", hashed_password="x")
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
        return uid


async def test_persistence_roundtrip(factory, neo4j_session):
    """ingest 经 store1 -> 全新 store2 实例 -> 数据仍可读（重启不丢）。"""
    from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore

    owner = await _make_user(factory)

    # 1) store1：写入三层数据
    store1_vec = PgVectorStore(factory)
    store1_graph = Neo4jGraphStore(neo4j_session, factory)
    store1_comm = PgCommunityStore(factory)
    await store1_vec.upsert_chunks(
        [
            ChunkRecord(
                chunk_id="d#0",
                doc_id="d",
                content="OpenAI 开发 GPT-4",
                vector=[1.0] + [0.0] * (_DIM - 1),
                metadata={"doc_id": "d"},
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner,
            )
        ]
    )
    await store1_graph.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="AI 公司",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner,
            ),
            EntityRecord(
                name="GPT-4",
                type="model",
                description="大模型",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner,
            ),
        ],
        [
            RelationRecord(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner,
            )
        ],
    )
    await store1_comm.upsert_communities(
        [
            CommunityRecord(
                community_id="doc-d",
                level=1,
                title="OpenAI 社区",
                summary="",
                member_entity_names=["OpenAI"],
                metadata={"doc_id": "d"},
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner,
            )
        ]
    )
    # 释放 store1 引用（模拟进程退出）
    del store1_vec, store1_graph, store1_comm

    # 2) store2：全新实例（同一 PG/Neo4j）-> 数据仍在
    store2_vec = PgVectorStore(factory)
    store2_graph = Neo4jGraphStore(neo4j_session, factory)
    store2_comm = PgCommunityStore(factory)

    chunks = await store2_vec.list_chunks(access=_ctx(owner))
    assert any(c.chunk_id == "d#0" for c in chunks)

    ents = await store2_graph.list_entities(access=_ctx(owner))
    assert any(e.name == "OpenAI" for e in ents)
    rels = await store2_graph.list_relations(access=_ctx(owner))
    assert any(r.source == "OpenAI" and r.target == "GPT-4" for r in rels)

    comms = await store2_comm.list_communities(access=_ctx(owner))
    assert any(c.community_id == "doc-d" for c in comms)


async def test_pg_backend_appstores_routing(monkeypatch):
    """AppStores 经 config backend 选 PG 真后端（vector/community）。"""
    monkeypatch.setenv("CALLIODESMO_VECTOR_STORE_BACKEND", "postgres")
    monkeypatch.setenv("CALLIODESMO_COMMUNITY_STORE_BACKEND", "postgres")
    from calliodesmo.config import get_settings

    get_settings.cache_clear()
    from calliodesmo.api.deps import AppStores

    stores = AppStores()
    from calliodesmo.providers.pg_community_store import PgCommunityStore
    from calliodesmo.providers.pg_vector_store import PgVectorStore

    assert isinstance(stores.vector_store, PgVectorStore)
    assert isinstance(stores.community_store, PgCommunityStore)
    get_settings.cache_clear()
