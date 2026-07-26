"""CommunityStore 抽象接口：社区摘要存储，按 AccessContext 过滤。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope


@dataclass
class CommunityRecord:
    """社区库记录：镜像 Community + access 字段。"""

    community_id: str
    level: int
    title: str
    summary: str
    member_entity_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class CommunityStore(ABC):
    @abstractmethod
    async def upsert_communities(self, communities: list[CommunityRecord]) -> None: ...

    @abstractmethod
    async def list_communities(self, *, access: AccessContext) -> list[CommunityRecord]: ...
