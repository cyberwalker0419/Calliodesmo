"""Task 4: CRAG——检索置信自知与重写兜底（P5 Task 4）。"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.config import Settings
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode
from calliodesmo.retrieval.corrective_rag import CorrectiveRagEngine, _confidence


def _ctx() -> AccessContext:
    return AccessContext(
        user_id="u",
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


class _FakeEngine(SearchEngine):
    """第 1 次查询返回低置信（无来源），第 2 次返回有来源答案。"""

    def __init__(self):
        self.count = 0
        self.seen_questions = []

    async def query(self, question, *, mode, top_k, access):
        self.count += 1
        self.seen_questions.append(question)
        if self.count == 1:
            return Answer(text="低置信答案", source_chunk_ids=[], mode=mode)
        return Answer(text="重写后答案", source_chunk_ids=["c1"], mode=mode)


async def test_confidence_low_when_no_sources():
    assert _confidence(Answer(text="x", source_chunk_ids=[], mode=SearchMode.NATIVE_RAG)) < 0.5
    assert (
        _confidence(Answer(text="x", source_chunk_ids=["c1", "c2"], mode=SearchMode.NATIVE_RAG))
        > 0.5
    )


async def test_crag_keeps_high_confidence_answer():
    """高置信（来源充足）不重查，直接返回。"""

    class _High(SearchEngine):
        async def query(self, question, *, mode, top_k, access):
            return Answer(text="好答案", source_chunk_ids=["c1", "c2", "c3"], mode=mode)

    engine = CorrectiveRagEngine(inner=_High(), threshold=0.5)
    ans = await engine.query("问题", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert ans.text == "好答案"


async def test_crag_rewrites_once_on_low_confidence():
    inner = _FakeEngine()
    engine = CorrectiveRagEngine(inner=inner, threshold=0.5)
    ans = await engine.query("问题", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.count == 2  # 低置信触发 1 轮重写重查
    assert "重写后答案" in ans.text
    assert "邻近" in inner.seen_questions[1]


async def test_crag_rewrite_keeps_mode():
    inner = _FakeEngine()
    engine = CorrectiveRagEngine(inner=inner, threshold=0.5)
    ans = await engine.query("问题", mode=SearchMode.LOCAL, top_k=5, access=_ctx())
    assert ans.mode == SearchMode.LOCAL


def _memory_settings(**overrides):
    base = dict(
        llm_model="test/stub-llm",
        embedding_provider="hash",
        embedding_dimension=64,
        reranker_provider="none",
        multi_query_enabled=False,
        contextual_retrieval_enabled=False,
        crag_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


async def test_factory_wires_crag_when_enabled():
    """装配测试：crag_enabled=True 时引擎被包成 CorrectiveRagEngine。"""
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
    engine = build_default_search_engine(_memory_settings(crag_enabled=True), **stores)
    assert engine.__class__.__name__ == "CorrectiveRagEngine"
    engine2 = build_default_search_engine(_memory_settings(crag_enabled=False), **stores)
    assert engine2.__class__.__name__ == "DefaultSearchEngine"
