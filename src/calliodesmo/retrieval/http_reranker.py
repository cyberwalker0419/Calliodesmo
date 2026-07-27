"""HttpReranker：远端交叉编码器重排（llama.cpp /rerank 兼容服务）。

本地 BgeReranker 需 FlagEmbedding 重依赖（extra: search-rerank）；本 provider 为
零重依赖远端替代（仅 httpx），适合已部署 bge-reranker-v2-m3 的场景（如
``llama-server --rerank -m bge-reranker-v2-m3.gguf --port 8083``）。按
``relevance_score`` 降序，``index`` 映射回原候选。
"""

from __future__ import annotations

import httpx

from calliodesmo.interfaces.retriever import Candidate, Reranker


class HttpReranker(Reranker):
    """远端 HTTP 重排器：POST {api_base}{endpoint}，按 relevance_score 降序。"""

    def __init__(
        self,
        api_base: str,
        *,
        model: str | None = None,
        api_key: str | None = None,
        endpoint: str = "/rerank",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout
        self._transport = transport  # 测试注入 MockTransport

    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]:
        if not candidates:
            return []
        payload: dict[str, object] = {
            "query": query,
            "documents": [c.content for c in candidates],
        }
        if self._model:
            payload["model"] = self._model
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            resp = await client.post(
                f"{self._api_base}{self._endpoint}", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])

        def _score(r: dict) -> float:
            # 兼容 relevance_score（llama.cpp）与 score（Cohere/Jina）
            return float(r.get("relevance_score", r.get("score", 0.0)))

        ordered = sorted(results, key=_score, reverse=True)
        out: list[Candidate] = []
        for rank, r in enumerate(ordered[:top_k], 1):
            idx = r.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
                continue
            c = candidates[idx]
            out.append(
                Candidate(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    content=c.content,
                    score=round(_score(r), 6),
                    rank=rank,
                    metadata=dict(c.metadata),
                    source=c.source,
                )
            )
        return out
