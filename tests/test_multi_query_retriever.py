"""Task 2: MultiQueryRetriever + rag_fusion + mmr_dedup（P5 Task 2）。"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.retrieval.fusion import mmr_dedup, rag_fusion
from calliodesmo.retrieval.multi_query_retriever import MultiQueryRetriever
from calliodesmo.retrieval.rewrite import RewriteRouter


def _cand(chunk_id: str, score: float) -> Candidate:
    return Candidate(chunk_id=chunk_id, doc_id="d", content=chunk_id, score=score)


async def test_rag_fusion_merges_subquery_lanes():
    lanes = {
        "q1": [_cand("a", 0.9), _cand("b", 0.8)],
        "q2": [_cand("b", 0.9), _cand("c", 0.7)],
    }
    fused = rag_fusion(lanes, top_k=3)
    ids = [c.chunk_id for c in fused]
    assert ids == ["b", "a", "c"]  # b 双路命中优先


async def test_mmr_dedup_keeps_diverse():
    cands = [_cand("a", 1.0), _cand("b", 0.9), _cand("c", 0.8)]
    vectors = {"a": [1.0, 0.0], "b": [0.99, 0.01], "c": [0.0, 1.0]}
    result = mmr_dedup(cands, query_vec=[0.5, 0.5], vectors=vectors, top_k=2, lam=0.7)
    assert len(result) == 2
    assert result[0].chunk_id != result[1].chunk_id


class _FixtureRetriever(Retriever):
    """固定返回候选，供 MultiQueryRetriever 联动。"""

    def __init__(self):
        self.queries_seen = []

    async def retrieve(self, query, *, top_k, mode=SearchMode.NATIVE_RAG, access):
        self.queries_seen.append(query)
        if "视角" in query:
            return [_cand("a", 0.9), _cand("b", 0.7)]
        return [_cand("c", 0.8)]


class _FakeRewriter:
    async def generate(self, q):
        return [q + " 视角1", q + " 视角2"]


def _ctx() -> AccessContext:
    return AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_multi_query_retriever_fans_out_and_fuses():
    inner = _FixtureRetriever()
    router = RewriteRouter(_FakeRewriter(), enabled=True)
    mq = MultiQueryRetriever(inner=inner, router=router)
    cands = await mq.retrieve("问题", top_k=5, mode=SearchMode.NATIVE_RAG, access=_ctx())
    assert len(cands) == 2  # a+b 融合后
    assert inner.queries_seen == ["问题 视角1", "问题 视角2"]
