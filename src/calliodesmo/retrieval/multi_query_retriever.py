"""MultiQueryRetriever：查询改写 + 多子查询串联内层 retriever + RRF 融合（P5 Task 2）。

装饰现有 ``HybridRetriever``（native）等任意 ``Retriever``：RewriteRouter 产出
多视角子查询 -> 逐个子查询调用 inner.retrieve -> ``rag_fusion`` 融合。子查询均继承
同一 ``access``，越权过滤由各层 store 保证。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.retrieval.fusion import rag_fusion
from calliodesmo.retrieval.rewrite import RewriteRouter


class MultiQueryRetriever(Retriever):
    """查询改写 + 多子查询 -> 内层 retriever -> RRF 融合的装饰器。"""

    def __init__(self, *, inner: Retriever, router: RewriteRouter) -> None:
        self._inner = inner
        self._router = router

    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]:
        sub_queries = await self._router.rewrite(query)
        lanes: dict[str, list[Candidate]] = {}
        for i, sub in enumerate(sub_queries):
            hits = await self._inner.retrieve(sub, top_k=top_k * 2, mode=mode, access=access)
            if hits:
                lanes[f"mq{i}"] = hits
        if not lanes:
            return []
        return rag_fusion(lanes, top_k=top_k)
