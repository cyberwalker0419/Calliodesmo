"""GraphStore 抽象接口：实体-关系图存储，按 AccessContext 过滤。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope


@dataclass
class EntityRecord:
    """图库实体记录：镜像 Entity（含 template_conforming）+ access 字段。"""

    name: str
    type: str | None
    description: str
    source_chunk_ids: list[str] = field(default_factory=list)
    template_conforming: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


@dataclass
class RelationRecord:
    """图库关系记录：source->target 边 + access 字段。"""

    source: str
    target: str
    type: str | None
    description: str
    source_chunk_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class GraphStore(ABC):
    @abstractmethod
    async def upsert_graph(
        self, entities: list[EntityRecord], relations: list[RelationRecord]
    ) -> None: ...

    @abstractmethod
    async def get_entity(self, name: str, *, access: AccessContext) -> EntityRecord | None: ...

    @abstractmethod
    async def neighbors(
        self, name: str, *, access: AccessContext
    ) -> tuple[list[EntityRecord], list[RelationRecord]]: ...
