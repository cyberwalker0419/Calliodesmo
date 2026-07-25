"""EmbeddingProvider 抽象接口：BGE-M3 本地 / 远端嵌入可切换。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimension: int


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度（建库时与 pgvector 列对齐）。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """批量嵌入文本。"""
