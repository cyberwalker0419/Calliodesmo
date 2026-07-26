"""OpenAI 兼容远端 EmbeddingProvider：经 /v1/embeddings 调用自建嵌入服务。

与本地 BGE-M3 同语义，但模型在远端（llama.cpp / vLLM / TEI 等 OpenAI 兼容 server），
无需本地 FlagEmbedding 重依赖。配合 settings.embedding_api_base / embedding_model 使用。

**分片池化**：远端服务常有单条 token 上限（如 llama.cpp 默认物理 batch=512 token，
中文约 400-500 字符即超限）。本 provider 把每条文本按 ``max_chars_per_slice`` 切片，
分别嵌入后取平均（mean pooling）得到该条向量，避免 500。设 0 关闭分片。
"""

from __future__ import annotations

import httpx

from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult


class RemoteEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_base: str,
        model: str,
        dimension: int = 1024,
        api_key: str = "local",
        timeout: float = 60.0,
        max_chars_per_slice: int = 400,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        if not self._api_base.endswith("/v1"):
            self._api_base += "/v1"
        self._model = model
        self._dimension = dimension
        self._api_key = api_key
        self._timeout = timeout
        self._max_chars = max_chars_per_slice

    @property
    def dimension(self) -> int:
        return self._dimension

    def _slice(self, text: str) -> list[str]:
        """按 max_chars 切片（不破坏字词边界时尽量整段切）。"""
        if self._max_chars <= 0 or len(text) <= self._max_chars:
            return [text]
        return [text[i : i + self._max_chars] for i in range(0, len(text), self._max_chars)]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._api_base}/embeddings",
                json={"model": self._model, "input": texts},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data["data"], key=lambda d: d.get("index", 0))
        return [item["embedding"] for item in items]

    @staticmethod
    def _mean_pool(vectors: list[list[float]]) -> list[float]:
        n = len(vectors)
        dim = len(vectors[0])
        out = [0.0] * dim
        for v in vectors:
            for i in range(dim):
                out[i] += v[i]
        return [x / n for x in out]

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        # 展开所有切片，扁平嵌入后按原文本重组（mean pool）
        all_slices: list[str] = []
        groups: list[tuple[int, int]] = []  # (start, count) per original text
        for t in texts:
            slices = self._slice(t)
            groups.append((len(all_slices), len(slices)))
            all_slices.extend(slices)
        flat = await self._embed_batch(all_slices)
        vectors = []
        for start, count in groups:
            slices = flat[start : start + count]
            vectors.append(self._mean_pool(slices) if len(slices) > 1 else slices[0])
        return EmbeddingResult(vectors=vectors, model=self._model, dimension=self._dimension)
