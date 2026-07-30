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


@dataclass
class SubgraphView:
    """增量子图视图：BFS 扩展结果（nodes/edges/命中的种子/是否截断）。"""

    nodes: list[EntityRecord] = field(default_factory=list)
    edges: list[RelationRecord] = field(default_factory=list)
    expanded_seeds: list[str] = field(default_factory=list)  # 实际入图的种子（可见且存在）
    truncated: bool = False  # 达节点上限被截断


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

    @abstractmethod
    async def subgraph(
        self, seeds: list[str], *, hops: int, limit: int, access: AccessContext
    ) -> SubgraphView:
        """从种子实体出发广度优先扩展 hops 跳，累计节点达 limit 截断。

        全程 visible_to 过滤（越权节点/边不入子图）；返回去重后的节点与边。
        """
        ...

    @abstractmethod
    async def list_entities(self, *, access: AccessContext) -> list[EntityRecord]:
        """枚举当前可见的全部实体（按 visible_to 过滤），供推送收集。"""
        ...

    @abstractmethod
    async def list_relations(self, *, access: AccessContext) -> list[RelationRecord]:
        """枚举当前可见的全部关系（按 visible_to 过滤），供推送收集。"""
        ...

    async def delete_by_doc(self, chunk_ids: list[str]) -> None:
        """P4.5 Task 3：从图剔除 chunk_ids 的引用——来源空的实体删、来源空的边丢（默认 no-op）。"""
        return None
