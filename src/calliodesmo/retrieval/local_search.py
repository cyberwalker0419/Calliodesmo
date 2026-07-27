"""LocalSearchRetriever：从种子实体出发 K 跳图邻居子图，归一到关联 chunk。

语义层检索：query -> 抽种子实体 -> 沿 GraphStore.neighbors 扩 K 跳 ->
收集 source_chunk_ids -> 归一到 chunk -> 去重。
越权邻居由 GraphStore 按 visible_to 过滤不可见。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.seed_extractor import SeedExtractor


class LocalSearchRetriever(Retriever):
    """图邻居 K 跳检索器（LOCAL 模式）。"""

    def __init__(
        self,
        *,
        seed_extractor: SeedExtractor,
        graph_store: GraphStore,
        vector_store: VectorStore,
        hops: int = 1,
    ) -> None:
        self._seed_extractor = seed_extractor
        self._graph_store = graph_store
        self._vector_store = vector_store
        self._hops = hops

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        mode: SearchMode = SearchMode.LOCAL,
        access: AccessContext,
    ) -> list[Candidate]:
        seeds = await self._seed_extractor.extract(query, access=access, graph=self._graph_store)
        if not seeds:
            return []

        # K 跳 BFS 扩展
        visited_entities: set[str] = set()
        frontier: set[str] = set(seeds)
        chunk_ids: set[str] = set()

        for _hop in range(self._hops + 1):
            if not frontier:
                break
            new_frontier: set[str] = set()
            for name in frontier:
                if name in visited_entities:
                    continue
                visited_entities.add(name)
                entity = await self._graph_store.get_entity(name, access=access)
                if entity is not None:
                    chunk_ids.update(entity.source_chunk_ids)
                neighbors, relations = await self._graph_store.neighbors(name, access=access)
                for nb in neighbors:
                    new_frontier.add(nb.name)
                    chunk_ids.update(nb.source_chunk_ids)
                for rel in relations:
                    chunk_ids.update(rel.source_chunk_ids)
            frontier = new_frontier - visited_entities

        if not chunk_ids:
            return []

        # 归一到 chunk
        chunks = await self._vector_store.get_chunks_by_ids(list(chunk_ids))
        # 去重、按 chunk_id 排序（确定性），取 top_k
        chunks.sort(key=lambda c: c.chunk_id)
        result: list[Candidate] = []
        for i, chunk in enumerate(chunks[:top_k], 1):
            result.append(
                Candidate(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    content=chunk.content,
                    score=1.0 / i,  # 图召回无相似度，用 rank 逆序作伪分
                    rank=i,
                    metadata=dict(chunk.metadata),
                    source="graph",
                )
            )
        return result
