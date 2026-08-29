"""Task 1: 查询改写接口 + MultiQuery 确定性生成（StubLLM 桩，离线可测）。"""

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse
from calliodesmo.retrieval.rewrite import MultiQueryGenerator, RewriteRouter


class _StubLLM(LLMProvider):
    """返回 JSON 数组，个数与 num_queries 请求一致（模拟多视角子查询）。"""

    def __init__(self, num: int = 3) -> None:
        self._num = num

    async def complete(
        self, messages: list[LLMMessage], *, temperature: float = 0.0, max_tokens: int | None = None
    ) -> LLMResponse:
        items = [f"查询 视角{i + 1}" for i in range(self._num)]
        import json

        return LLMResponse(content=json.dumps(items, ensure_ascii=False), model="test", usage={})


async def test_multi_query_generator_returns_subqueries():
    gen = MultiQueryGenerator(llm=_StubLLM(num=3), num_queries=3)
    queries = await gen.generate("原始问题")
    assert queries == ["查询 视角1", "查询 视角2", "查询 视角3"]


async def test_rewrite_router_passthrough_when_disabled():
    gen = MultiQueryGenerator(llm=_StubLLM(num=3), num_queries=3)
    router = RewriteRouter(rewriter=gen, enabled=False)
    queries = await router.rewrite("只问一遍")
    assert queries == ["只问一遍"]


async def test_rewrite_router_delegates_when_enabled():
    gen = MultiQueryGenerator(llm=_StubLLM(num=2), num_queries=2)
    router = RewriteRouter(rewriter=gen, enabled=True)
    queries = await router.rewrite("原始问题")
    assert len(queries) == 2


async def test_parse_queries_handles_bad_json():
    assert MultiQueryGenerator._parse_queries("not-json") == []
    assert MultiQueryGenerator._parse_queries('["a", "b"]') == ["a", "b"]


class _EmptyGen:
    """永不产出子查询的 rewriter（模拟 LLM 吐非法 JSON 的空生成）。"""

    async def generate(self, query):
        return []


async def test_rewrite_router_falls_back_when_generation_empty():
    """enabled 但空生成 -> 回退原查询（防 MultiQuery 空召回，P5 Task 2 收尾）。"""
    router = RewriteRouter(rewriter=_EmptyGen(), enabled=True)
    assert await router.rewrite("原始问题") == ["原始问题"]
