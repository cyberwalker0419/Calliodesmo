"""InMemoryVectorStore：确定性内存向量库（余弦相似，按 visible_to 过滤）。"""

from __future__ import annotations

import math

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.vector_store import ChunkRecord, VectorHit, VectorStore


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._records: dict[str, ChunkRecord] = {}

    async def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        for c in chunks:
            self._records[c.chunk_id] = c  # 同 chunk_id 覆盖（幂等）

    async def search(
        self, query_vector: list[float], *, top_k: int, access: AccessContext
    ) -> list[VectorHit]:
        from calliodesmo.stores.visibility import visible_to

        scored: list[VectorHit] = []
        for rec in self._records.values():
            if not visible_to(rec, access):
                continue
            score = _cosine(query_vector, rec.vector)
            scored.append(
                VectorHit(
                    chunk_id=rec.chunk_id,
                    score=score,
                    content=rec.content,
                    metadata=dict(rec.metadata),
                )
            )
        # score 降序，平局按 chunk_id 升序（确定性）
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._records)
