"""Task 2 测试：HybridRetriever 混合检索编排。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.hybrid_retriever import HybridRetriever
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _access(
    clearance: ClearanceLevel = ClearanceLevel.INTERNAL,
    user_id: uuid.UUID = USER_ID,
) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="analyst",
        clearance=clearance,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


def _chunk(
    chunk_id: str,
    content: str,
    *,
    doc_id: str = "doc1",
    owner_id: uuid.UUID = USER_ID,
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL,
) -> ChunkRecord:
    emb = HashEmbeddingProvider(dimension=64)
    vec = emb._embed_one(content)
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=content,
        vector=vec,
        access_level=access_level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner_id,
    )


async def _setup_stores(chunks: list[ChunkRecord]):
    vs = InMemoryVectorStore()
    bm = InMemoryBM25Index()
    emb = HashEmbeddingProvider(dimension=64)
    await vs.upsert_chunks(chunks)
    await bm.index(chunks)
    return vs, bm, emb


class TestHybridRetrieverOrchestration:
    @pytest.mark.asyncio
    async def test_dense_and_sparse_fused(self):
        """query 经 dense+sparse 两路召回 -> rrf 融合。"""
        chunks = [
            _chunk("c1", "machine learning models for text classification"),
            _chunk("c2", "cooking recipes for dinner"),
            _chunk("c3", "deep learning neural networks"),
        ]
        vs, bm, emb = await _setup_stores(chunks)
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
        results = await retriever.retrieve(
            "machine learning", top_k=3, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert len(results) >= 1
        # c1 含 "machine learning"，BM25 必命中
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        # 融合后 rank 重置
        for i, c in enumerate(results, 1):
            assert c.rank == i
        # source 标注包含 lane
        assert "vector" in results[0].source or "sparse" in results[0].source

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        """空库查询返回空。"""
        vs = InMemoryVectorStore()
        bm = InMemoryBM25Index()
        emb = HashEmbeddingProvider(dimension=64)
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
        results = await retriever.retrieve(
            "anything", top_k=5, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert results == []


class TestHybridRetrieverVisibility:
    @pytest.mark.asyncio
    async def test_clearance_filter(self):
        """低 clearance 用户不可见越权 chunk。"""
        chunks = [
            _chunk("c1", "public content about AI", access_level=ClearanceLevel.PUBLIC),
            _chunk("c2", "secret content about AI", access_level=ClearanceLevel.SECRET),
        ]
        vs, bm, emb = await _setup_stores(chunks)
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
        results = await retriever.retrieve(
            "AI",
            top_k=5,
            mode=SearchMode.NATIVE_RAG,
            access=_access(clearance=ClearanceLevel.PUBLIC),
        )
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        assert "c2" not in ids

    @pytest.mark.asyncio
    async def test_scope_filter_personal(self):
        """非 owner 不可见 personal 库 chunk。"""
        chunks = [
            _chunk("c1", "my content about AI", owner_id=USER_ID),
            _chunk("c2", "other content about AI", owner_id=OTHER_ID),
        ]
        vs, bm, emb = await _setup_stores(chunks)
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
        results = await retriever.retrieve(
            "AI", top_k=5, mode=SearchMode.NATIVE_RAG, access=_access(user_id=USER_ID)
        )
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        assert "c2" not in ids


class TestHybridRetrieverDegradation:
    @pytest.mark.asyncio
    async def test_missing_sparse_index_degrades_to_dense(self):
        """缺 sparse index（注入 None）时仅走 dense，不报错。"""
        chunks = [
            _chunk("c1", "machine learning models"),
            _chunk("c2", "cooking recipes"),
        ]
        vs = InMemoryVectorStore()
        emb = HashEmbeddingProvider(dimension=64)
        await vs.upsert_chunks(chunks)
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=None)
        results = await retriever.retrieve(
            "machine learning", top_k=5, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert len(results) >= 1
        # source 仅含 vector（无 sparse 参与）
        for c in results:
            assert c.source == "vector"
