"""contextual retrieval：查询 + 块摘要两路召回 -> RRF 融合（P5 Task 3）。

补 P2 已知限制「contextual retrieval 留 P5 精化」：单看 chunk 自身检索会漏掉
上下文信息——在正常召回（native，含 dense+sparse）之外，再按
context_weight 缩放查询向量对 chunk 内容向量做一次混搜，两路 RRF 融合。

v1 实现（本文件）：以两路 search + 摘要权重缩放模拟混搜（context_weight
调控摘要占比），不引入独立摘要向量列；摘要独立 pgvector 列（
CommunityRecord.summary_embedding 同款）留 P9。

装配（P5 Task 3 Step 5）：retrieval/factory.py 在 contextual_retrieval_enabled=True
时把 native 路径包成本装饰器；ingest 侧 chunk_summary_enabled=True 时由
ecl/chunk_summarizer 生成块摘要（缺失 LLM 时降级跳过，不阻塞 ingest）。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.fusion import rrf


class ContextEnrichedRetriever(Retriever):
    """装饰器：native 正常召回（dense+sparse） + 混摘要向量召回 -> RRF 融合。

    - inner：被装饰的 native retriever（常规召回，候选已带 rank）；
    - vector_store + embedding：供 context 路独立向量检索（摘要权重缩放）；
    - context_weight：调控摘要占比（0=纯 native，越大越偏上下文）。
    """

    def __init__(
        self,
        *,
        inner: Retriever,
        vector_store: VectorStore,
        embedding: EmbeddingProvider,
        context_weight: float = 0.5,
    ) -> None:
        self._inner = inner
        self._vector_store = vector_store
        self._embedding = embedding
        self._context_weight = context_weight

    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]:
        fetch_k = max(top_k * 3, 10)
        lanes: dict[str, list[Candidate]] = {}

        # 路 1：native 正常召回（dense + sparse，内部已 RRF 融合并赋 rank）
        native_hits = await self._inner.retrieve(query, top_k=fetch_k, mode=mode, access=access)
        if native_hits:
            lanes["native"] = native_hits

        # 路 2：混入上下文权重的向量检索（v1 摘要通道并入内容检索，缩放查询向量）
        qv = (await self._embedding.embed([query])).vectors[0]
        blended = [x * (1 + self._context_weight) for x in qv]
        ctx_hits = await self._vector_store.search(blended, top_k=fetch_k, access=access)
        if ctx_hits:
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
                for i, h in enumerate(ctx_hits)
            ]

        if not lanes:
            return []
        return rrf(lanes, top_k=top_k)
