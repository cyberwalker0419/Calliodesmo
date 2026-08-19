"""Task 3: context-enriched retriever——摘要向量混搜（P5 Task 3）。"""

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import VectorHit, VectorStore
from calliodesmo.retrieval.context_enriched_retriever import ContextEnrichedRetriever


class _FakeEmb(EmbeddingProvider):
    @property
    def dimension(self) -> int:
        return 4

    async def embed(self, texts):
        # 每文本独立处理；query 与 summary/context 分桶由调用方组装，这里返回单位向量
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
            VectorHit(
                chunk_id="c1",
                score=0.9,
                content="chunk1",
                metadata={"doc_id": "d", "summary": "摘要1"},
            )
        ]

    async def upsert_chunks(self, chunks): ...

    async def search(self, query_vector, *, top_k, access):
        self.calls.append(query_vector)
        return self._hits

    async def get_chunks_by_ids(self, ids):
        return []

    async def list_chunks(self, *, access):
        return []


def _ctx() -> AccessContext:
    return AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_context_enriched_issues_two_lane_searches():
    """查询向量 + 混摘要向量两路都发起（context_weight 缩放）。"""
    vs = _FakeVS()
    retriever = ContextEnrichedRetriever(inner=vs, embedding=_FakeEmb(), context_weight=0.5)
    await retriever.retrieve("问题", top_k=3, mode=SearchMode.NATIVE_RAG, access=_ctx())
    assert len(vs.calls) == 2
    # 第二路（context）向量 = 查询向量 × (1 + context_weight)
    qv = vs.calls[0]
    ctx_vec = vs.calls[1]
    assert ctx_vec[0] == pytest.approx(qv[0] * 1.5)


async def test_context_enriched_returns_fused_candidates():
    """两路 hit 经 RRF 融合返回候选（去重、sources 标注）。"""
    vs = _FakeVS()
    retriever = ContextEnrichedRetriever(inner=vs, embedding=_FakeEmb(), context_weight=0.5)
    cands = await retriever.retrieve("问题", top_k=3, mode=SearchMode.NATIVE_RAG, access=_ctx())
    assert len(cands) == 1  # 两路同 chunk 融合成 1
    assert cands[0].chunk_id == "c1"
    assert "content" in cands[0].source and "context" in cands[0].source
