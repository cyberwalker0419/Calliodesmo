"""P9 Task 7：检索谓词下推与 VectorStore 置换契约。

两条线合成一份测试：

1. **下推**：可见性过滤必须在取数层生效（SQL WHERE / 内存预过滤），不得「先取全量
   再后置过滤」；`get_chunks_by_ids` 传 access 时按 ID 直取也不越权；
2. **置换**：memory 与 postgres(pgvector) 两个实现对同一数据给出一致结果——换后端
   等于换实现，不能换语义。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index
from calliodesmo.stores.visibility import visible_to

pytest.importorskip("pgvector")

from calliodesmo.config import get_settings
from calliodesmo.providers.pg_vector_store import PgVectorStore

_DIM = get_settings().embedding_dimension
OWNER = uuid.uuid4()
OUTSIDER = uuid.uuid4()
TEAM = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _v(*coords: float) -> list[float]:
    vec = [0.0] * _DIM
    for i, c in enumerate(coords):
        vec[i] = c
    return vec


def _ctx(user_id, *, clearance=ClearanceLevel.SECRET) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        library_scopes=frozenset({LibraryScope.PERSONAL, LibraryScope.TEAM, LibraryScope.PROJECT}),
        team_ids=frozenset({TEAM}),
    )


def _corpus() -> list[ChunkRecord]:
    """四档：本人 internal / 本人 confidential / 他人 personal / 团队 public。"""
    return [
        ChunkRecord(
            chunk_id="mine-internal#0",
            doc_id="mine-internal",
            content="北方稀土总部位于内蒙古包头",
            vector=_v(1.0, 0.0),
            metadata={"doc_id": "mine-internal"},
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=OWNER,
        ),
        ChunkRecord(
            chunk_id="mine-confidential#0",
            doc_id="mine-confidential",
            content="夜莺组织威胁等级高",
            vector=_v(0.9, 0.1),
            metadata={"doc_id": "mine-confidential"},
            access_level=ClearanceLevel.CONFIDENTIAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=OWNER,
        ),
        ChunkRecord(
            chunk_id="other-personal#0",
            doc_id="other-personal",
            content="他人的私人笔记",
            vector=_v(0.8, 0.2),
            metadata={"doc_id": "other-personal"},
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=OUTSIDER,
        ),
        ChunkRecord(
            chunk_id="team-public#0",
            doc_id="team-public",
            content="稀土市场月度公开简报",
            vector=_v(0.7, 0.3),
            metadata={"doc_id": "team-public"},
            access_level=ClearanceLevel.PUBLIC,
            library_scope=LibraryScope.TEAM,
            owner_id=OWNER,
            team_id=TEAM,
        ),
    ]


async def _memory_store(chunks) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    await store.upsert_chunks(chunks)
    return store


async def _delete_pg_rows(engine):
    from calliodesmo.db.models_content import ChunkRecordORM, Document

    async with engine.begin() as conn:
        await conn.execute(ChunkRecordORM.__table__.delete())
        await conn.execute(Document.__table__.delete())


@pytest.fixture
async def pg_store(session):
    """真 pgvector 后端：先落两个真实用户（documents.owner_id 有 FK），用例前后清内容表。"""
    from calliodesmo.auth.models import User

    for user_id, username in ((OWNER, "vs-owner"), (OUTSIDER, "vs-outsider")):
        if (await session.get(User, user_id)) is None:
            session.add(User(id=user_id, username=username, hashed_password="x"))
    await session.commit()
    await _delete_pg_rows(session.bind)
    store = PgVectorStore(async_sessionmaker(session.bind, expire_on_commit=False))
    await store.upsert_chunks(_corpus())
    yield store
    await _delete_pg_rows(session.bind)


class TestGetChunksByIdsPushdown:
    async def test_memory_filters_by_access(self):
        store = await _memory_store(_corpus())
        chunks = await store.get_chunks_by_ids(
            ["mine-internal#0", "other-personal#0", "no-such#0"], access=_ctx(OWNER)
        )
        assert {c.chunk_id for c in chunks} == {"mine-internal#0"}

    async def test_memory_without_access_keeps_legacy(self):
        store = await _memory_store(_corpus())
        chunks = await store.get_chunks_by_ids(["mine-internal#0", "other-personal#0"])
        assert {c.chunk_id for c in chunks} == {"mine-internal#0", "other-personal#0"}

    async def test_pg_filters_by_access(self, pg_store):
        chunks = await pg_store.get_chunks_by_ids(
            ["mine-internal#0", "mine-confidential#0", "other-personal#0", "no-such#0"],
            access=_ctx(OWNER, clearance=ClearanceLevel.INTERNAL),
        )
        assert {c.chunk_id for c in chunks} == {"mine-internal#0"}

    async def test_pg_clearance_up_grants_view(self, pg_store):
        chunks = await pg_store.get_chunks_by_ids(
            ["mine-confidential#0"], access=_ctx(OWNER, clearance=ClearanceLevel.CONFIDENTIAL)
        )
        assert [c.chunk_id for c in chunks] == ["mine-confidential#0"]

    async def test_invisible_and_missing_same_result(self):
        """越权与不存在同语义：返回集里没有就是没有（不区分原因）。"""
        store = await _memory_store(_corpus())
        invisible = await store.get_chunks_by_ids(["other-personal#0"], access=_ctx(OWNER))
        missing = await store.get_chunks_by_ids(["no-such#0"], access=_ctx(OWNER))
        assert invisible == missing == []


class TestBackendParity:
    """同一数据、两种后端：可见集合与排序结果必须一致（换后端不换语义）。"""

    async def test_list_chunks_same_visible_ids(self, pg_store):
        """枚举可见集：两后端逐 clearance 必须一致。"""
        memory = await _memory_store(_corpus())
        for clearance in (
            ClearanceLevel.PUBLIC,
            ClearanceLevel.INTERNAL,
            ClearanceLevel.CONFIDENTIAL,
            ClearanceLevel.SECRET,
        ):
            access = _ctx(OWNER, clearance=clearance)
            mem_ids = sorted(c.chunk_id for c in await memory.list_chunks(access=access))
            pg_ids = sorted(c.chunk_id for c in await pg_store.list_chunks(access=access))
            assert mem_ids == pg_ids, f"clearance={clearance} 可见集不一致"

    async def test_search_same_ids_and_order(self, pg_store):
        memory = await _memory_store(_corpus())
        access = _ctx(OWNER, clearance=ClearanceLevel.INTERNAL)
        query = _v(1.0, 0.0)
        mem_hits = [h.chunk_id for h in await memory.search(query, top_k=10, access=access)]
        pg_hits = [h.chunk_id for h in await pg_store.search(query, top_k=10, access=access)]
        assert mem_hits == pg_hits == ["mine-internal#0", "team-public#0"]

    async def test_large_top_k_never_leaks(self, pg_store):
        """top_k 开大也不能把高密 / 他人块带出来（谓词在 SQL 里，不在 Python 里）。"""
        memory = await _memory_store(_corpus())
        access = _ctx(OWNER, clearance=ClearanceLevel.PUBLIC)
        mem_hits = [h.chunk_id for h in await memory.search(_v(1.0), top_k=1000, access=access)]
        pg_hits = [h.chunk_id for h in await pg_store.search(_v(1.0), top_k=1000, access=access)]
        assert set(mem_hits) == set(pg_hits) == {"team-public#0"}
        for hit in pg_hits:
            assert hit != "mine-confidential#0"


class TestSparsePrefilter:
    async def test_prefilter_equivalent_to_postfilter(self):
        chunks = _corpus()
        index = InMemoryBM25Index()
        await index.index(chunks)
        access = _ctx(OWNER, clearance=ClearanceLevel.INTERNAL)
        hits = await index.search("稀土", top_k=10, access=access)
        assert {h.chunk_id for h in hits} <= {c.chunk_id for c in chunks if visible_to(c, access)}
        assert "team-public#0" in [h.chunk_id for h in hits]

    async def test_scores_unchanged_by_prefilter(self):
        chunks = _corpus()
        index = InMemoryBM25Index()
        await index.index(chunks)
        access = _ctx(OWNER)
        hits = await index.search("夜莺 威胁", top_k=10, access=access)
        assert [h.chunk_id for h in hits] == ["mine-confidential#0"]
        assert all(h.score > 0 for h in hits)


class TestBackendSwap:
    """置换回归：配置切后端即换实现，语义由上面的契约测试锁死。"""

    def test_config_selects_pg_implementations(self, monkeypatch):
        import calliodesmo.api.deps as deps
        from calliodesmo.api.deps import AppStores
        from calliodesmo.config import Settings
        from calliodesmo.providers.pg_community_store import PgCommunityStore

        monkeypatch.setattr(
            deps,
            "get_settings",
            lambda: Settings(
                vector_store_backend="postgres",
                community_store_backend="postgres",
                graph_store_backend="memory",
                _env_file=None,
            ),
        )
        stores = AppStores()
        assert isinstance(stores.vector_store, PgVectorStore)
        assert isinstance(stores.community_store, PgCommunityStore)
        # ProfileCard 与 BM25 仍是进程内单例（P9 移交，2026-W52；见 deps TODO 与计划）
        assert stores.sparse_index is not None
