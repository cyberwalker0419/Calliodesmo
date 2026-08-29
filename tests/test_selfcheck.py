"""Task 5: SelfCheck——答案-上下文一致性重答（P5 Task 5）。"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.config import Settings
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode
from calliodesmo.retrieval.selfcheck import SelfCheckEngine


class _Done:
    def __init__(self, content, model="test", usage=None):
        self.content = content
        self.model = model
        self.usage = usage


class _Judge(LLMProvider):
    """固定分数 judge（0-1）。"""

    def __init__(self, score):
        self._score = score

    async def complete(self, messages, **kw):
        return _Done(content=str(self._score))


class _Engine(SearchEngine):
    """第 1 次返回答案一，之后返回答案二（记录重答次数）。"""

    def __init__(self):
        self.calls = 0

    async def query(self, question, *, mode, top_k, access):
        self.calls += 1
        return Answer(
            text="答案一" if self.calls == 1 else "答案二",
            source_chunk_ids=["c1"],
            mode=mode,
        )


def _ctx() -> AccessContext:
    return AccessContext(
        user_id="u",
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_selfcheck_keeps_good_answer():
    """高一致性（score>=threshold）不重答。"""
    inner = _Engine()
    engine = SelfCheckEngine(inner=inner, judge=_Judge(0.9), threshold=0.5)
    ans = await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 1
    assert "答案一" in ans.text


async def test_selfcheck_rewrites_once_on_low_score():
    """低一致性触发 1 轮重答。"""
    inner = _Engine()
    engine = SelfCheckEngine(inner=inner, judge=_Judge(0.2), threshold=0.5)
    ans = await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 2
    assert "答案二" in ans.text


async def test_selfcheck_parse_error_defaults_zero():
    """judge 返回非数字 -> 0 分 -> 重答。"""
    inner = _Engine()
    engine = SelfCheckEngine(inner=inner, judge=_Judge("不是数字"), threshold=0.5)
    await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 2


async def test_selfcheck_empty_answer_retries():
    """空答案 -> 0 分 -> 重答。"""

    class _Empty(SearchEngine):
        def __init__(self):
            self.calls = 0

        async def query(self, question, *, mode, top_k, access):
            self.calls += 1
            text = "" if self.calls == 1 else "非空答案"
            return Answer(text=text, source_chunk_ids=["c1"], mode=mode)

    inner = _Empty()
    engine = SelfCheckEngine(inner=inner, judge=_Judge(0.8), threshold=0.5)
    ans = await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 2
    assert ans.text == "非空答案"


def _memory_settings(**overrides):
    base = dict(
        llm_model="test/stub-llm",
        embedding_provider="hash",
        embedding_dimension=64,
        reranker_provider="none",
        multi_query_enabled=False,
        contextual_retrieval_enabled=False,
        crag_enabled=False,
        selfcheck_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


async def test_factory_wires_selfcheck_when_enabled():
    """装配测试：selfcheck_enabled=True 时引擎被包成 SelfCheckEngine。"""
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
    engine = build_default_search_engine(_memory_settings(selfcheck_enabled=True), **stores)
    assert engine.__class__.__name__ == "SelfCheckEngine"
    engine2 = build_default_search_engine(_memory_settings(selfcheck_enabled=False), **stores)
    assert engine2.__class__.__name__ == "DefaultSearchEngine"
