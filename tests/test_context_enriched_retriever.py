"""Task 3: context-enriched retriever——摘要向量混搜 + 工厂装配（P5 Task 3）。"""

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.config import Settings
from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorHit, VectorStore
from calliodesmo.retrieval.context_enriched_retriever import ContextEnrichedRetriever


class _FakeEmb(EmbeddingProvider):
    @property
    def dimension(self) -> int:
        return 4

    async def embed(self, texts):
        return EmbeddingResult(
            vectors=[[1.0 if i == 0 else 0.0 for i in range(4)] for _ in texts],
            model="test",
            dimension=4,
        )


class _FakeVS(VectorStore):
    """记录所有 search 调用向量，返回固定 hit。"""

    def __init__(self):
        self.calls = []
        self._hits = [
            VectorHit(chunk_id="c1", score=0.9, content="chunk1", metadata={"doc_id": "d"}),
            VectorHit(chunk_id="c2", score=0.8, content="chunk2", metadata={"doc_id": "d"}),
        ]

    async def upsert_chunks(self, chunks): ...

    async def search(self, query_vector, *, top_k, access):
        self.calls.append(query_vector)
        return self._hits

    async def get_chunks_by_ids(self, ids):
        return []

    async def list_chunks(self, *, access):
        return []


class _FakeInner(Retriever):
    """固定返回带 rank 的 native 候选（模拟 HybridRetriever 输出）。"""

    def __init__(self):
        self.queries = []

    async def retrieve(self, query, *, top_k, mode, access):
        self.queries.append(query)
        return [
            Candidate(
                chunk_id="n1", doc_id="d", content="native-c1", score=0.9, rank=1, source="native"
            ),
            Candidate(
                chunk_id="c1", doc_id="d", content="chunk1", score=0.7, rank=2, source="native"
            ),
        ]


def _ctx() -> AccessContext:
    return AccessContext(
        user_id="u",
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_context_enriched_two_lanes_native_plus_context():
    """native 路 + context 路（向量 × (1+w)）两路都发起。"""
    inner = _FakeInner()
    vs = _FakeVS()
    retriever = ContextEnrichedRetriever(
        inner=inner, vector_store=vs, embedding=_FakeEmb(), context_weight=0.5
    )
    await retriever.retrieve("问题", top_k=3, mode=SearchMode.NATIVE_RAG, access=_ctx())
    assert inner.queries == ["问题"]
    assert len(vs.calls) == 1
    # context 路向量 = 查询向量 × (1 + context_weight)
    qv = [1.0, 0.0, 0.0, 0.0]
    assert vs.calls[0][0] == pytest.approx(qv[0] * 1.5)


async def test_context_enriched_fuses_both_lanes():
    """native 与 context 两路候选经 RRF 融合返回（跨路同 chunk 合并）。"""
    inner = _FakeInner()
    vs = _FakeVS()
    retriever = ContextEnrichedRetriever(
        inner=inner, vector_store=vs, embedding=_FakeEmb(), context_weight=0.5
    )
    cands = await retriever.retrieve("问题", top_k=5, mode=SearchMode.NATIVE_RAG, access=_ctx())
    ids = [c.chunk_id for c in cands]
    assert "n1" in ids
    assert "c1" in ids  # context 路命中 c1，与 native 路合并
    assert "c2" in ids
    # c1 双路命中 -> 融合分应高于仅 native 命中的 n1
    fused_c1 = next(c for c in cands if c.chunk_id == "c1")
    fused_n1 = next(c for c in cands if c.chunk_id == "n1")
    assert fused_c1.score > fused_n1.score
    assert "native" in fused_c1.source and "context" in fused_c1.source


def _memory_settings(**overrides):
    base = dict(
        llm_model="test/stub-llm",
        embedding_provider="hash",
        embedding_dimension=64,
        reranker_provider="none",
        multi_query_enabled=False,
        contextual_retrieval_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


async def test_factory_wires_context_enriched_when_enabled():
    """装配测试：contextual_retrieval_enabled=True 时 native 路被包成 ContextEnrichedRetriever。"""
    from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
    from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
    from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
    from calliodesmo.retrieval.factory import build_default_search_engine
    from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

    stores = dict(
        vector_store=InMemoryVectorStore(),
        graph_store=InMemoryGraphStore(),
        community_store=InMemoryCommunityStore(),
        sparse_index=InMemoryBM25Index(),
    )
    engine = build_default_search_engine(
        _memory_settings(contextual_retrieval_enabled=True), **stores
    )
    assert engine._native_retriever.__class__.__name__ == "ContextEnrichedRetriever"

    engine2 = build_default_search_engine(_memory_settings(), **stores)
    assert engine2._native_retriever.__class__.__name__ == "HybridRetriever"
