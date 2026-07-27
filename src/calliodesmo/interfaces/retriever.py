"""检索域抽象接口：SparseIndex / Reranker / Retriever / SearchEngine。

与 P1 的 VectorStore / GraphStore / CommunityStore 同构，全程接收 AccessContext
并复用 visible_to 做越权过滤。默认实现保持确定性、零重依赖、离线可测。

Candidate 统一承载多路召回结果（向量/稀疏/图三路产出同一类型），便于 RRF 融合。
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.vector_store import ChunkRecord


class SearchMode(enum.StrEnum):
    NATIVE_RAG = "native_rag"  # 情景层：向量+稀疏混合，查原始文本块
    LOCAL = "local"  # 语义层：图邻居子图
    GLOBAL = "global"  # 摘要层：社区摘要主题


@dataclass
class Candidate:
    """多路召回的统一候选：chunk 为最小粒度（图/社区召回最终也归一到关联 chunk）。"""

    chunk_id: str
    doc_id: str
    content: str
    score: float  # 融合前的单路分数（相似度/BM25/图亲和）
    rank: int | None = None  # 单路秩（1-based），RRF 融合用
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # "vector" / "sparse" / "graph" / "community"


@dataclass
class Answer:
    text: str
    source_chunk_ids: list[str]  # 来源标注（证据溯源，供 UI 高亮与审计）
    mode: SearchMode
    context_chunks: list[dict[str, Any]] = field(default_factory=list)  # 喂模型的上下文摘要
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class SparseIndex(ABC):
    @abstractmethod
    async def index(self, chunks: list[ChunkRecord]) -> None: ...

    @abstractmethod
    async def search(self, query: str, *, top_k: int, access: AccessContext) -> list[Candidate]: ...


class Reranker(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]: ...


class Retriever(ABC):
    @abstractmethod
    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]: ...


class SearchEngine(ABC):
    @abstractmethod
    async def query(
        self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext
    ) -> Answer: ...
