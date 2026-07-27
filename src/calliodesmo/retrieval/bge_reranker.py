"""BgeReranker：bge-reranker-v2-m3 交叉编码器重排（extra: search-rerank）。

打 chunk 原文（Candidate.content），不打摘要；缺依赖抛友好错误并提示
``uv sync --extra search-rerank``。离线测试用 sys.modules 桩 FlagEmbedding。
"""

from __future__ import annotations

from calliodesmo.interfaces.retriever import Candidate, Reranker


class BgeReranker(Reranker):
    """bge-reranker-v2-m3 交叉编码器重排。"""

    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3") -> None:
        self._model_name = model
        self._model = None  # 懒加载

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("重排需 FlagEmbedding：uv sync --extra search-rerank") from exc
        self._model = FlagReranker(self._model_name, use_fp16=True)

    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]:
        if not candidates:
            return []
        self._ensure_model()
        # 打原文（Candidate.content），不打摘要
        pairs = [[query, c.content] for c in candidates]
        scores = self._model.compute_score(pairs, normalize=True)
        # compute_score 返回单个 float 或 list[float]
        if isinstance(scores, (int, float)):
            scores = [float(scores)]
        else:
            scores = [float(s) for s in scores]
        # 按重排分降序，平局按 chunk_id 确定性排序
        indexed = list(zip(scores, candidates, strict=True))
        indexed.sort(key=lambda x: (-x[0], x[1].chunk_id))
        result: list[Candidate] = []
        for rank, (score, c) in enumerate(indexed[:top_k], 1):
            result.append(
                Candidate(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    content=c.content,
                    score=round(score, 6),
                    rank=rank,
                    metadata=dict(c.metadata),
                    source=c.source,
                )
            )
        return result
