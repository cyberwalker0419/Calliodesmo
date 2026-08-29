"""CRAG：检索置信自知，低置信触发重写重查（P5 Task 4）。

v1 不引 LLM 决策路由（不做「网络兜底/声明」分支），低置信统一走重写重查 1 轮；
真正的 LLM 决策路由留 P8（自适应 RAG）。

confidence 基于来源 chunk 数（v1：最多 3 条即满置信）；低于 threshold 时以
「补充邻近信息」提示重写问题重查 1 轮，命中来源后返回。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode


def _confidence(answer: Answer) -> float:
    """基于来源 chunk 数的简单置信分（v1：最多 3 条即满置信）。"""
    if not answer.source_chunk_ids:
        return 0.0
    return min(1.0, len(answer.source_chunk_ids) / 3.0)


class CorrectiveRagEngine(SearchEngine):
    """包装 SearchEngine：低置信 -> 重写问题重查 1 轮。

    - 检索后算置信分（来源 chunk 覆盖率）；
    - >= threshold 直接返回；
    - < threshold 以补充提示重写问题重查 1 轮（v1 不引 LLM 决策路由）。
    """

    def __init__(self, *, inner: SearchEngine, threshold: float = 0.5) -> None:
        self._inner = inner
        self._threshold = threshold

    async def query(
        self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext
    ) -> Answer:
        answer = await self._inner.query(question, mode=mode, top_k=top_k, access=access)
        if _confidence(answer) >= self._threshold:
            return answer
        rewritten = f"{question}（补充：请同时考虑相关实体的邻近信息）"
        answer2 = await self._inner.query(rewritten, mode=mode, top_k=top_k, access=access)
        answer2.mode = mode  # 重查结果仍归属原检索模式
        return answer2
