"""PgVectorStore 契约测试（P4.5 Task 2 Step 2）。

走真实 PG+pgvector（``_pg_engine``），验证 upsert 幂等 / search 余弦排序 + visible_to 过滤 /
get_chunks_by_ids / list_chunks，对齐 InMemoryVectorStore 语义。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.config import get_settings
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.pg_vector_store import PgVectorStore

_DIM = get_settings().embedding_dimension


def _v(*coords: float) -> list[float]:
    """构造 _DIM 维向量（前若干位填 coords，其余 0）。"""
    vec = [0.0] * _DIM
    for i, c in enumerate(coords):
        vec[i] = c
    return vec


def _ctx(user_id, *, clearance=ClearanceLevel.SECRET, project_ids=(), team_ids=()) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        project_ids=frozenset(project_ids),
        team_ids=frozenset(team_ids),
    )


def _chunk(
    chunk_id,
    owner,
    *,
    doc_id=None,
    vector=None,
    access_level=ClearanceLevel.INTERNAL,
    scope=LibraryScope.PERSONAL,
    project_id=None,
    team_id=None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id or chunk_id,
        content=f"content-{chunk_id}",
        vector=vector or _v(1.0),
        metadata={"doc_id": doc_id or chunk_id},
        access_level=access_level,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
        project_id=project_id,
        team_id=team_id,
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


async def _make_user(factory, username="u") -> uuid.UUID:
    """建真实 User（documents.owner_id FK->users.id 须有真实行）。"""
    from calliodesmo.auth.models import User

    async with factory() as s:
        u = User(username=f"{username}-{uuid.uuid4().hex[:6]}", hashed_password="x")
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
        return uid


async def test_upsert_and_get_roundtrip(factory):
    store = PgVectorStore(factory)
    owner = await _make_user(factory)
    await store.upsert_chunks([_chunk("c#0", owner, vector=_v(1.0))])
    got = await store.get_chunks_by_ids(["c#0"])
    assert len(got) == 1
    assert got[0].content == "content-c#0"
    assert got[0].vector == _v(1.0)
    assert got[0].owner_id == owner


async def test_upsert_idempotent_overwrites(factory):
    store = PgVectorStore(factory)
    owner = await _make_user(factory)
    await store.upsert_chunks([_chunk("c#0", owner)])  # type: ignore[misc]
    # 同 chunk_id 二次 upsert（改 vector）
    await store.upsert_chunks([_chunk("c#0", owner, vector=_v(0.0, 1.0))])
    got = await store.get_chunks_by_ids(["c#0"])
    assert len(got) == 1
    assert got[0].vector == _v(0.0, 1.0)


async def test_search_cosine_order_and_visibility(factory):
    store = PgVectorStore(factory)
    owner = await _make_user(factory)
    # 三条同 owner personal chunk：与 query 余弦相似度递减
    await store.upsert_chunks(
        [
            _chunk("near", owner, vector=_v(1.0)),
            _chunk("mid", owner, vector=_v(0.7, 0.7)),
            _chunk("far", owner, vector=_v(0.0, 1.0)),
        ]
    )
    hits = await store.search(_v(1.0), top_k=3, access=_ctx(owner))
    assert [h.chunk_id for h in hits] == ["near", "mid", "far"]  # 相似度降序
    assert hits[0].score > hits[1].score > hits[2].score
    # 别人的 personal chunk 不可见
    other = await _make_user(factory, "other")
    await store.upsert_chunks([_chunk("other", other, vector=_v(1.0))])
    hits2 = await store.search(_v(1.0), top_k=10, access=_ctx(owner))
    assert "other" not in {h.chunk_id for h in hits2}


async def test_search_clearance_filter(factory):
    store = PgVectorStore(factory)
    owner = await _make_user(factory)
    # owner 的两条 personal chunk：一条 INTERNAL（可见）、一条 SECRET（低 clearance 不可见）
    await store.upsert_chunks(
        [
            _chunk("lo", owner, access_level=ClearanceLevel.INTERNAL, vector=_v(1.0)),
            _chunk("hi", owner, access_level=ClearanceLevel.SECRET, vector=_v(1.0)),
        ]
    )
    # owner clearance=INTERNAL -> 只见 INTERNAL 那条
    hits = await store.search(
        _v(1.0), top_k=10, access=_ctx(owner, clearance=ClearanceLevel.INTERNAL)
    )
    assert {h.chunk_id for h in hits} == {"lo"}
    # clearance=SECRET -> 两条都见
    hits2 = await store.search(
        _v(1.0), top_k=10, access=_ctx(owner, clearance=ClearanceLevel.SECRET)
    )
    assert {h.chunk_id for h in hits2} == {"lo", "hi"}


async def test_list_chunks_visibility(factory):
    store = PgVectorStore(factory)
    owner = await _make_user(factory)
    proj = uuid.uuid4()
    await store.upsert_chunks(
        [
            _chunk("mine", owner, scope=LibraryScope.PERSONAL, vector=_v(1.0)),
            _chunk(
                "proj",
                owner,
                scope=LibraryScope.PROJECT,
                project_id=proj,
                vector=_v(1.0),
            ),
        ]
    )
    # owner 个人库可见
    listed = await store.list_chunks(access=_ctx(owner))
    assert "mine" in {c.chunk_id for c in listed}
    # owner 不在 project_ids -> 项目库不可见
    listed2 = await store.list_chunks(access=_ctx(owner, project_ids=[]))
    assert "proj" not in {c.chunk_id for c in listed2}
    # owner 在 project_ids -> 项目库可见
    listed3 = await store.list_chunks(access=_ctx(owner, project_ids=[proj]))
    assert "proj" in {c.chunk_id for c in listed3}
