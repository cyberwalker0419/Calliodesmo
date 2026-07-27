"""IdentityReranker：保序降级重排器，缺重模型时默认使用。

按传入顺序保持不变，仅重置 rank 为 1..n、score 不变、top_k 截断。
作为 BgeReranker 缺 FlagEmbedding 依赖时的零依赖降级方案。
"""

from __future__ import annotations

from calliodesmo.interfaces.retriever import Candidate, Reranker


class IdentityReranker(Reranker):
    """保序降级重排器：不改变候选顺序与分数，仅重设 rank 并截断 top_k。"""

    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]:
        result = candidates[:top_k]
        for i, c in enumerate(result, 1):
            c.rank = i
        return result
