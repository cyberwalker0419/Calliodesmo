"""GlobalSearchRetriever：社区摘要向量召回，成员实体归一到 chunk。

摘要层检索：query -> 嵌入 -> 对社区摘要(title+summary)余弦召回 ->
取 top-N 社区 -> 成员实体 source_chunk_ids 归一 chunk。
社区摘要进 LLM 上下文但不进 rerank、不进稠密索引。
"""

from __future__ import annotations

import math

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.community_store import CommunityStore
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class GlobalSearchRetriever(Retriever):
    """社区摘要向量召回检索器（GLOBAL 模式）。"""

    def __init__(
        self,
        *,
        community_store: CommunityStore,
        graph_store: GraphStore,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        top_communities: int = 10,
    ) -> None:
        self._community_store = community_store
        self._graph_store = graph_store
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._top_communities = top_communities

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        mode: SearchMode = SearchMode.GLOBAL,
        access: AccessContext,
    ) -> list[Candidate]:
        communities = await self._community_store.list_communities(access=access)
        if not communities:
            return []

        # 嵌入社区摘要文本（title + summary）
        community_texts = [f"{c.title} {c.summary}" for c in communities]
        emb = await self._embedding_provider.embed([query, *community_texts])
        query_vec = emb.vectors[0]
        community_vecs = emb.vectors[1:]

        # 余弦相似度排序
        scored = [
            (_cosine(query_vec, cv), c) for cv, c in zip(community_vecs, communities, strict=True)
        ]
        scored.sort(key=lambda x: (-x[0], x[1].community_id))
        top = scored[: self._top_communities]

        # 成员实体归一 chunk
        chunk_ids: set[str] = set()
        for _, community in top:
            for member_name in community.member_entity_names:
                entity = await self._graph_store.get_entity(member_name, access=access)
                if entity is not None:
                    chunk_ids.update(entity.source_chunk_ids)

        if not chunk_ids:
            return []

        chunks = await self._vector_store.get_chunks_by_ids(list(chunk_ids))
        chunks.sort(key=lambda c: c.chunk_id)
        result: list[Candidate] = []
        for i, chunk in enumerate(chunks[:top_k], 1):
            result.append(
                Candidate(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    content=chunk.content,
                    score=1.0 / i,
                    rank=i,
                    metadata=dict(chunk.metadata),
                    source="community",
                )
            )
        return result
