"""Cognify 抽象接口：建图 / 实体消解 / 社区检测 / 社区摘要 + Community 共享类型。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.extractor import ExtractionResult


@dataclass
class Community:
    """社区：实体社区（level=0）或文档社区（level=1），携带 access 字段。"""

    community_id: str
    level: int  # 0=实体社区，1=文档社区
    title: str
    summary: str
    member_entity_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class GraphBuilder(ABC):
    @abstractmethod
    def build(self, result: ExtractionResult) -> dict:
        """把 ExtractionResult 建成实体-关系图（节点/边），返回图结构。"""


class EntityResolver(ABC):
    @abstractmethod
    def resolve(self, graph: dict) -> dict:
        """实体消解：名归一化 + 别名合并 + 多 chunk 描述汇总，返回消解后的图。"""


class CommunityDetector(ABC):
    @abstractmethod
    def detect(self, graph: dict, *, access: AccessContext) -> list[Community]:
        """在消解后的图上做社区检测，返回实体社区（level=0）。"""


class CommunitySummarizer(ABC):
    @abstractmethod
    async def summarize(self, communities: list[Community], graph: dict) -> list[Community]:
        """对每个社区生成 LLM 摘要（title/summary），原地填充后返回。"""
