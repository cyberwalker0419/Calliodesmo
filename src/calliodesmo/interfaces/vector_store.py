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

    @abstractmethod
    async def list_chunks(self, *, access: AccessContext) -> list[ChunkRecord]:
        """枚举当前可见的全部 chunk（按 visible_to 过滤），供推送收集。"""
        ...

    # ---- P4.5 Task 3：增量索引指纹（默认无操作，子类按持久化覆写）----

    async def get_content_hash(self, doc_id: str, *, access: AccessContext) -> str | None:
        """返回 doc 当前已记录的内容指纹；无记录返回 None（视作新文档需抽取）。"""
        return None

    async def record_content_hash(
        self, doc_id: str, content_hash: str, *, access: AccessContext
    ) -> None:
        """记录文档内容指纹（增量索引：下次 ingest 据此判定是否短路）。"""
        return None

    async def delete_by_doc(self, doc_id: str) -> None:
        """P4.5 Task 3：删除某文档的全部 chunk（默认 no-op，子类按持久化覆写）。"""
        return None
