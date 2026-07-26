"""Chunker 抽象接口：把 LoadedDocument 切成带 access 字段的 Chunk（P1 ECL 的切分层）。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.document_loader import LoadedDocument


@dataclass
class Chunk:
    """文本块：携带完整 access 字段，供后续落库与检索过滤。

    ``summary`` 为 L0 分层摘要预留字段（借鉴 OpenViking L0/L1 分层）：
    **P1 不生成**，全程填 ``None``；L0/L1 摘要属 P2/P5 范畴，此处仅预留接口。
    """

    chunk_id: str  # f"{doc_id}#{ordinal}"
    doc_id: str
    content: str
    ordinal: int
    summary: str | None = None  # L0 摘要预留（P2/P5 生成，P1 填 None）
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @classmethod
    def from_document(
        cls,
        doc: LoadedDocument,
        *,
        ordinal: int,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Chunk:
        """从 LoadedDocument 继承 access 字段（缺省 INTERNAL/personal）。

        summary 不在此设置（保持 None）；P1 不生成 chunk 摘要。
        """
        md = doc.metadata or {}
        owner = md.get("owner_id")
        project = md.get("project_id")
        team = md.get("team_id")
        return cls(
            chunk_id=f"{doc.doc_id}#{ordinal}",
            doc_id=doc.doc_id,
            content=content,
            ordinal=ordinal,
            metadata={**md, **(metadata or {})},
            access_level=md.get("access_level", ClearanceLevel.INTERNAL),
            library_scope=md.get("library_scope", LibraryScope.PERSONAL),
            owner_id=owner if isinstance(owner, uuid.UUID) else None,
            project_id=project if isinstance(project, uuid.UUID) else None,
            team_id=team if isinstance(team, uuid.UUID) else None,
        )


class Chunker(ABC):
    @abstractmethod
    async def chunk(self, doc: LoadedDocument) -> list[Chunk]:
        """把单个文档切成有序 Chunk 列表（确定性、无丢失覆盖）。"""
