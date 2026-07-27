"""HybridRetriever：native_rag 模式，编排 dense + sparse 两路召回 -> RRF 融合。

dense（VectorStore 余弦）+ sparse（SparseIndex BM25）两路召回，
各路按分排序赋 rank，再经 RRF 倒数秩融合合并。
缺 sparse index（注入 None）时仅走 dense，不报错（容错降级）。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode, SparseIndex
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.fusion import rrf


class HybridRetriever(Retriever):
    """混合检索器：dense（向量余弦）+ sparse（BM25）-> RRF 融合。"""

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        sparse_index: SparseIndex | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.sparse_index = sparse_index
        self.rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        mode: SearchMode = SearchMode.NATIVE_RAG,
        access: AccessContext,
    ) -> list[Candidate]:
        # 召回 top_k * 扩展因子，给 RRF 更多候选后截断
        fetch_k = max(top_k * 3, 10)
        lanes: dict[str, list[Candidate]] = {}

        # dense 路
        embed_result = await self.embedding_provider.embed([query])
        query_vector = embed_result.vectors[0]
        hits = await self.vector_store.search(query_vector, top_k=fetch_k, access=access)
        dense_candidates = [
            Candidate(
                chunk_id=h.chunk_id,
                doc_id=h.metadata.get("doc_id", ""),
                content=h.content,
                score=h.score,
                rank=i + 1,
                metadata=dict(h.metadata),
                source="vector",
            )
            for i, h in enumerate(hits)
        ]
        if dense_candidates:
            lanes["vector"] = dense_candidates

        # sparse 路（降级：缺 index 时跳过）
        if self.sparse_index is not None:
            sparse_candidates = await self.sparse_index.search(query, top_k=fetch_k, access=access)
            if sparse_candidates:
                lanes["sparse"] = sparse_candidates

        if not lanes:
            return []

        return rrf(lanes, k=self.rrf_k, top_k=top_k)
