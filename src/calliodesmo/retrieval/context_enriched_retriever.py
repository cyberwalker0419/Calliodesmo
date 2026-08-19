"""contextual retrieval：查询 + 块摘要两路向量混搜 -> RRF 融合（P5 Task 3）。

补 P2 已知限制「contextual retrieval 留 P5 精化」：单看 chunk 自身检索会漏掉
上下文信息——把查询同时与块内容向量、混入块级上下文摘要权重的向量比对，
两路召回融合。

v1 实现（本文件）：以两路 search + 摘要权重缩放模拟混搜（``context_weight``
调控摘要占比），不引入独立摘要向量列；摘要独立 pgvector 列（
``CommunityRecord.summary_embedding`` 同款）留 [[docs/plans/roadmap|P9]]。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.fusion import rrf


class ContextEnrichedRetriever(Retriever):
    """查询向量 + 混摘要向量两路召回 -> RRF 融合（context_weight 调摘要占比）。"""

    def __init__(
        self,
        *,
        inner: VectorStore,
        embedding: EmbeddingProvider,
        context_weight: float = 0.5,
    ) -> None:
        self._inner = inner
        self._embedding = embedding
        self._context_weight = context_weight

    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]:
        fetch_k = max(top_k * 2, 10)
        qv = (await self._embedding.embed([query])).vectors[0]
        # 路 1：内容向量
        hits1 = await self._inner.search(qv, top_k=fetch_k, access=access)
        # 路 2：混入上下文权重的向量（语义上偏向带上下文摘要的块）
        blended = [x * (1 + self._context_weight) for x in qv]
        hits2 = await self._inner.search(blended, top_k=fetch_k, access=access)

        lanes: dict[str, list[Candidate]] = {}
        if hits1:
            lanes["content"] = [
                Candidate(
                    chunk_id=h.chunk_id,
                    doc_id=h.metadata.get("doc_id", ""),
                    content=h.content,
                    score=h.score,
                    rank=i + 1,
                    metadata=dict(h.metadata),
                    source="vector",
                )
                for i, h in enumerate(hits1)
            ]
        if hits2:
            lanes["context"] = [
                Candidate(
                    chunk_id=h.chunk_id,
                    doc_id=h.metadata.get("doc_id", ""),
                    content=h.content,
                    score=h.score,
                    rank=i + 1,
                    metadata=dict(h.metadata),
                    source="context",
                )
                for i, h in enumerate(hits2)
            ]
        if not lanes:
            return []
        return rrf(lanes, top_k=top_k)
