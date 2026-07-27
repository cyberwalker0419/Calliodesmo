"""Task 1 测试：检索域抽象接口与确定性默认实现。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.retriever import (
    Answer,
    Candidate,
    Reranker,
    Retriever,
    SearchEngine,
    SearchMode,
    SparseIndex,
)
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.retrieval.identity_reranker import IdentityReranker
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _access(
    clearance: ClearanceLevel = ClearanceLevel.INTERNAL,
    user_id: uuid.UUID = USER_ID,
    scopes: frozenset[LibraryScope] = frozenset({LibraryScope.PERSONAL}),
) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="analyst",
        clearance=clearance,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=scopes,
    )


def _chunk(
    chunk_id: str,
    content: str,
    *,
    doc_id: str = "doc1",
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL,
    library_scope: LibraryScope = LibraryScope.PERSONAL,
    owner_id: uuid.UUID = USER_ID,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=content,
        vector=[0.1],
        access_level=access_level,
        library_scope=library_scope,
        owner_id=owner_id,
    )


# --- Step 1: 数据模型 ---


class TestCandidateAnswerSearchMode:
    def test_search_mode_values(self):
        assert SearchMode.NATIVE_RAG == "native_rag"
        assert SearchMode.LOCAL == "local"
        assert SearchMode.GLOBAL == "global"
        assert len(SearchMode) == 3

    def test_candidate_fields_and_defaults(self):
        c = Candidate(chunk_id="c1", doc_id="d1", content="hello", score=0.5)
        assert c.chunk_id == "c1"
        assert c.doc_id == "d1"
        assert c.content == "hello"
        assert c.score == 0.5
        assert c.rank is None
        assert c.metadata == {}
        assert c.source == ""

    def test_answer_fields_and_defaults(self):
        a = Answer(
            text="answer",
            source_chunk_ids=["c1"],
            mode=SearchMode.NATIVE_RAG,
        )
        assert a.text == "answer"
        assert a.source_chunk_ids == ["c1"]
        assert a.mode == SearchMode.NATIVE_RAG
        assert a.context_chunks == []
        assert a.model == ""
        assert a.usage == {}


# --- Step 2: InMemoryBM25Index 基本检索 ---


class TestInMemoryBM25Index:
    @pytest.mark.asyncio
    async def test_empty_index_returns_empty(self):
        idx = InMemoryBM25Index()
        results = await idx.search("test", top_k=5, access=_access())
        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_ranked_candidates(self):
        idx = InMemoryBM25Index()
        await idx.index(
            [
                _chunk("c1", "machine learning models for text classification"),
                _chunk("c2", "cooking recipes for dinner"),
                _chunk("c3", "deep learning and neural networks"),
            ]
        )
        results = await idx.search("machine learning", top_k=3, access=_access())
        assert len(results) >= 1
        assert results[0].chunk_id == "c1"
        assert results[0].source == "sparse"
        assert results[0].rank == 1
        # rank 递增
        for i in range(1, len(results)):
            assert results[i].rank == i + 1
            assert results[i - 1].score >= results[i].score

    @pytest.mark.asyncio
    async def test_chinese_tokenization(self):
        idx = InMemoryBM25Index()
        await idx.index(
            [
                _chunk("c1", "深度学习在自然语言处理中的应用"),
                _chunk("c2", "天气预报说明天有雨"),
            ]
        )
        results = await idx.search("深度学习", top_k=2, access=_access())
        assert len(results) >= 1
        assert results[0].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        idx = InMemoryBM25Index()
        await idx.index([_chunk("c1", "cooking recipes")])
        results = await idx.search("quantum physics", top_k=5, access=_access())
        assert results == []


# --- Step 3: visible_to 过滤 ---


class TestBM25Visibility:
    @pytest.mark.asyncio
    async def test_clearance_filter(self):
        idx = InMemoryBM25Index()
        await idx.index(
            [
                _chunk("c1", "public content about AI", access_level=ClearanceLevel.PUBLIC),
                _chunk("c2", "secret content about AI", access_level=ClearanceLevel.SECRET),
            ]
        )
        # 低 clearance 用户只能看到 public
        results = await idx.search("AI", top_k=5, access=_access(clearance=ClearanceLevel.PUBLIC))
        ids = [r.chunk_id for r in results]
        assert "c1" in ids
        assert "c2" not in ids

    @pytest.mark.asyncio
    async def test_scope_filter_personal(self):
        idx = InMemoryBM25Index()
        await idx.index(
            [
                _chunk("c1", "my content about AI", owner_id=USER_ID),
                _chunk("c2", "other content about AI", owner_id=OTHER_ID),
            ]
        )
        results = await idx.search("AI", top_k=5, access=_access(user_id=USER_ID))
        ids = [r.chunk_id for r in results]
        assert "c1" in ids
        assert "c2" not in ids


# --- Step 4: IdentityReranker ---


class TestIdentityReranker:
    @pytest.mark.asyncio
    async def test_preserves_order_and_resets_rank(self):
        reranker = IdentityReranker()
        candidates = [
            Candidate(chunk_id="c3", doc_id="d", content="b", score=0.9),
            Candidate(chunk_id="c1", doc_id="d", content="a", score=0.8),
            Candidate(chunk_id="c2", doc_id="d", content="c", score=0.7),
        ]
        result = await reranker.rerank("query", candidates, top_k=10)
        assert len(result) == 3
        assert result[0].chunk_id == "c3"
        assert result[1].chunk_id == "c1"
        assert result[2].chunk_id == "c2"
        # rank 重置为 1..n
        for i, c in enumerate(result, 1):
            assert c.rank == i
        # score 不变
        assert result[0].score == 0.9
        assert result[1].score == 0.8
        assert result[2].score == 0.7

    @pytest.mark.asyncio
    async def test_top_k_truncation(self):
        reranker = IdentityReranker()
        candidates = [
            Candidate(chunk_id=f"c{i}", doc_id="d", content=f"text{i}", score=float(i))
            for i in range(5)
        ]
        result = await reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        reranker = IdentityReranker()
        result = await reranker.rerank("query", [], top_k=5)
        assert result == []


# --- Step 5: ABC 不可直接实例化 ---


class TestABCEnforcement:
    def test_sparse_index_abc(self):
        with pytest.raises(TypeError):
            SparseIndex()  # type: ignore[abstract]

    def test_reranker_abc(self):
        with pytest.raises(TypeError):
            Reranker()  # type: ignore[abstract]

    def test_retriever_abc(self):
        with pytest.raises(TypeError):
            Retriever()  # type: ignore[abstract]

    def test_search_engine_abc(self):
        with pytest.raises(TypeError):
            SearchEngine()  # type: ignore[abstract]

    def test_incomplete_subclass_fails(self):
        class IncompleteSparse(SparseIndex):
            async def index(self, chunks):
                pass

        with pytest.raises(TypeError):
            IncompleteSparse()  # type: ignore[abstract]
