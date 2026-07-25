"""默认 EmbeddingProvider：BGE-M3 本地嵌入（FlagEmbedding 为可选重依赖，懒加载）。"""

import asyncio

from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult


class BgeM3EmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, model_name: str = "BAAI/bge-m3", dimension: int = 1024, use_fp16: bool = True
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._use_fp16 = use_fp16
        self._model = None  # 懒加载

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_model(self):
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:
                raise RuntimeError(
                    "BGE-M3 需要可选依赖 FlagEmbedding：uv sync --extra embedding-local"
                ) from exc
            self._model = BGEM3FlagModel(self._model_name, use_fp16=self._use_fp16)
        return self._model

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        model = self._load_model()
        outputs = await asyncio.to_thread(model.encode, texts, return_dense=True)
        vectors = [v.tolist() for v in outputs["dense_vecs"]]
        return EmbeddingResult(vectors=vectors, model=self._model_name, dimension=self._dimension)
