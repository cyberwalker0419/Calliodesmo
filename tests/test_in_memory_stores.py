"""Task 4 Step 2-4/6：内存三 store + 幂等 upsert 测试。"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore


def _ctx(*, user=None, clearance=ClearanceLevel.INTERNAL, teams=(), projects=()) -> AccessContext:
    return AccessContext(
        user_id=user or uuid.uuid4(),
        username="u",
        clearance=clearance,
        team_ids=frozenset(teams),
        project_ids=frozenset(projects),
    )


def _personal(owner, level=ClearanceLevel.INTERNAL):
    return {"library_scope": LibraryScope.PERSONAL, "owner_id": owner, "access_level": level}


# ---- VectorStore ----


async def test_vector_store_search_filters_and_orders():
    owner = uuid.uuid4()
    store = InMemoryVectorStore()
    recs = [
        ChunkRecord(chunk_id="a", doc_id="d", content="a", vector=[1.0, 0.0], **_personal(owner)),
        ChunkRecord(chunk_id="b", doc_id="d", content="b", vector=[0.0, 1.0], **_personal(owner)),
        ChunkRecord(
            chunk_id="c", doc_id="d", content="c", vector=[1.0, 0.0], **_personal(uuid.uuid4())
        ),
    ]
    await store.upsert_chunks(recs)
    hits = await store.search([1.0, 0.0], top_k=10, access=_ctx(user=owner))
    ids = [h.chunk_id for h in hits]
    assert "c" not in ids  # 越权拒见
    assert ids[0] == "a"  # score 最高


async def test_vector_store_top_k_truncation():
    owner = uuid.uuid4()
    store = InMemoryVectorStore()
    await store.upsert_chunks(
        [
            ChunkRecord(chunk_id=f"c{i}", doc_id="d", content="x", vector=[1.0], **_personal(owner))
            for i in range(5)
        ]
    )
    hits = await store.search([1.0], top_k=2, access=_ctx(user=owner))
    assert len(hits) == 2


async def test_vector_store_idempotent_upsert():
    owner = uuid.uuid4()
    store = InMemoryVectorStore()
    await store.upsert_chunks(
        [ChunkRecord(chunk_id="a", doc_id="d", content="v1", vector=[1.0], **_personal(owner))]
    )
    await store.upsert_chunks(
        [ChunkRecord(chunk_id="a", doc_id="d", content="v2", vector=[1.0], **_personal(owner))]
    )
    assert len(store) == 1
    hits = await store.search([1.0], top_k=1, access=_ctx(user=owner))
    assert hits[0].content == "v2"


# ---- GraphStore ----


async def test_graph_store_upsert_and_query():
    owner = uuid.uuid4()
    store = InMemoryGraphStore()
    ents = [
        EntityRecord(
            name="OpenAI", type="org", description="a", template_conforming=True, **_personal(owner)
        ),
        EntityRecord(name="GPT-4", type="model", description="b", **_personal(owner)),
    ]
    rels = [
        RelationRecord(
            source="OpenAI", target="GPT-4", type="developed", description="", **_personal(owner)
        )
    ]
    await store.upsert_graph(ents, rels)
    assert await store.get_entity("OpenAI", access=_ctx(user=owner)) is not None
    assert await store.get_entity("OpenAI", access=_ctx(user=uuid.uuid4())) is None
    neighbors, edges = await store.neighbors("OpenAI", access=_ctx(user=owner))
    assert {n.name for n in neighbors} == {"GPT-4"}
    assert len(edges) == 1


async def test_graph_store_same_name_overwrite():
    owner = uuid.uuid4()
    store = InMemoryGraphStore()
    await store.upsert_graph(
        [EntityRecord(name="X", type="t1", description="old", **_personal(owner))], []
    )
    await store.upsert_graph(
        [EntityRecord(name="X", type="t2", description="new", **_personal(owner))], []
    )
    ent = await store.get_entity("X", access=_ctx(user=owner))
    assert ent.type == "t2"


# ---- CommunityStore ----


async def test_community_store_list_filters_and_sorts():
    owner = uuid.uuid4()
    store = InMemoryCommunityStore()
    await store.upsert_communities(
        [
            CommunityRecord(
                community_id="c1", level=1, title="zeta", summary="s", **_personal(owner)
            ),
            CommunityRecord(
                community_id="c0", level=0, title="alpha", summary="s", **_personal(owner)
            ),
            CommunityRecord(
                community_id="c2", level=0, title="beta", summary="s", **_personal(uuid.uuid4())
            ),
        ]
    )
    listed = await store.list_communities(access=_ctx(user=owner))
    ids = [c.community_id for c in listed]
    assert "c2" not in ids
    assert ids == ["c0", "c1"]
