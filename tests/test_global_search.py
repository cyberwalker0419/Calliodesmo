"""Task 4 测试：GlobalSearchRetriever 社区摘要向量召回。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.global_search import GlobalSearchRetriever

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _access(clearance=ClearanceLevel.INTERNAL, user_id=USER_ID):
    return AccessContext(
        user_id=user_id,
        username="analyst",
        clearance=clearance,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


def _community(cid, title, summary, members, level=ClearanceLevel.INTERNAL, owner=USER_ID):
    return CommunityRecord(
        community_id=cid,
        level=0,
        title=title,
        summary=summary,
        member_entity_names=members,
        access_level=level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
    )


async def _setup():
    comm_store = InMemoryCommunityStore()
    graph = InMemoryGraphStore()
    vs = InMemoryVectorStore()
    emb = HashEmbeddingProvider(dimension=64)
    # 社区
    communities = [
        _community("cm1", "AI Research", "OpenAI and GPT models", ["OpenAI", "GPT-4"]),
        _community("cm2", "Cooking", "Recipes and food", ["Chef"]),
    ]
    await comm_store.upsert_communities(communities)
    # 实体
    entities = [
        EntityRecord(
            name="OpenAI",
            type="org",
            description="AI company",
            source_chunk_ids=["c1"],
            owner_id=USER_ID,
        ),
        EntityRecord(
            name="GPT-4", type="model", description="LLM", source_chunk_ids=["c2"], owner_id=USER_ID
        ),
        EntityRecord(
            name="Chef",
            type="person",
            description="cook",
            source_chunk_ids=["c3"],
            owner_id=USER_ID,
        ),
    ]
    await graph.upsert_graph(entities, [])
    # chunks
    chunks = [
        ChunkRecord(
            chunk_id="c1", doc_id="d", content="OpenAI content", vector=[0.1], owner_id=USER_ID
        ),
        ChunkRecord(
            chunk_id="c2", doc_id="d", content="GPT-4 content", vector=[0.1], owner_id=USER_ID
        ),
        ChunkRecord(
            chunk_id="c3", doc_id="d", content="cooking content", vector=[0.1], owner_id=USER_ID
        ),
    ]
    await vs.upsert_chunks(chunks)
    retriever = GlobalSearchRetriever(
        community_store=comm_store,
        graph_store=graph,
        vector_store=vs,
        embedding_provider=emb,
        top_communities=10,
    )
    return retriever


class TestGlobalSearchRetriever:
    @pytest.mark.asyncio
    async def test_returns_related_chunks(self):
        retriever = await _setup()
        results = await retriever.retrieve(
            "AI research GPT", top_k=10, mode=SearchMode.GLOBAL, access=_access()
        )
        assert len(results) >= 1
        # 应包含 AI 相关社区成员的 chunk
        ids = {c.chunk_id for c in results}
        assert "c1" in ids or "c2" in ids
        assert all(c.source == "community" for c in results)

    @pytest.mark.asyncio
    async def test_empty_communities(self):
        comm_store = InMemoryCommunityStore()
        graph = InMemoryGraphStore()
        vs = InMemoryVectorStore()
        emb = HashEmbeddingProvider(dimension=64)
        retriever = GlobalSearchRetriever(
            community_store=comm_store,
            graph_store=graph,
            vector_store=vs,
            embedding_provider=emb,
            top_communities=10,
        )
        results = await retriever.retrieve(
            "test", top_k=10, mode=SearchMode.GLOBAL, access=_access()
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_clearance_filter(self):
        """越权社区被 CommunityStore 过滤不可见。"""
        comm_store = InMemoryCommunityStore()
        graph = InMemoryGraphStore()
        vs = InMemoryVectorStore()
        emb = HashEmbeddingProvider(dimension=64)
        communities = [
            _community("cm1", "Public Topic", "public info", ["E1"], level=ClearanceLevel.PUBLIC),
            _community("cm2", "Secret Topic", "secret info", ["E2"], level=ClearanceLevel.SECRET),
        ]
        await comm_store.upsert_communities(communities)
        entities = [
            EntityRecord(
                name="E1",
                type="t",
                description="d",
                source_chunk_ids=["c1"],
                owner_id=USER_ID,
                access_level=ClearanceLevel.PUBLIC,
            ),
            EntityRecord(
                name="E2",
                type="t",
                description="d",
                source_chunk_ids=["c2"],
                owner_id=USER_ID,
                access_level=ClearanceLevel.SECRET,
            ),
        ]
        await graph.upsert_graph(entities, [])
        chunks = [
            ChunkRecord(
                chunk_id="c1",
                doc_id="d",
                content="public",
                vector=[0.1],
                owner_id=USER_ID,
                access_level=ClearanceLevel.PUBLIC,
            ),
            ChunkRecord(
                chunk_id="c2",
                doc_id="d",
                content="secret",
                vector=[0.1],
                owner_id=USER_ID,
                access_level=ClearanceLevel.SECRET,
            ),
        ]
        await vs.upsert_chunks(chunks)
        retriever = GlobalSearchRetriever(
            community_store=comm_store,
            graph_store=graph,
            vector_store=vs,
            embedding_provider=emb,
            top_communities=10,
        )
        results = await retriever.retrieve(
            "topic",
            top_k=10,
            mode=SearchMode.GLOBAL,
            access=_access(clearance=ClearanceLevel.PUBLIC),
        )
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        assert "c2" not in ids
