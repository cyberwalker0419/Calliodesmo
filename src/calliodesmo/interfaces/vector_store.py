"""VectorStore 抽象接口：向量存储 + 余弦检索，按 AccessContext 过滤。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope


@dataclass
class ChunkRecord:
    """向量库记录：Chunk 内容 + 嵌入向量 + access 字段。"""

    chunk_id: str
    doc_id: str
    content: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


@dataclass
class VectorHit:
    chunk_id: str
    score: float
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    @abstractmethod
    async def upsert_chunks(self, chunks: list[ChunkRecord]) -> None: ...

    @abstractmethod
    async def search(
        self, query_vector: list[float], *, top_k: int, access: AccessContext
    ) -> list[VectorHit]: ...

    @abstractmethod
    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[ChunkRecord]: ...
