"""确定性本地 EmbeddingProvider：离线开发/测试用（无语义，不替代真实模型）。"""

import hashlib
import math

from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult


class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._embed_one(t) for t in texts],
            model="hash-embedding",
            dimension=self._dimension,
        )

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 * 2 - 1 for i in range(self._dimension)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]
