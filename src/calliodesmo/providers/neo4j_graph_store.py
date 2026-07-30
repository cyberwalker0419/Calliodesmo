"""Neo4jGraphStore：语义层实体-关系图真后端（Neo4j + PG 镜像），按 AccessContext 过滤。

P4.5 Task 2 Step 3。对齐 :class:`~calliodesmo.interfaces.graph_store.GraphStore` 契约：
``upsert_graph``（Neo4j MERGE 节点/边 + PG ``entities``/``relations`` 镜像 upsert）/
``get_entity`` / ``neighbors`` / ``subgraph``（BFS）/ ``list_entities`` / ``list_relations``。

- Neo4j 节点标签 ``Entity``（按 ``name`` MERGE，与内存实现一致：同名实体覆盖）；
  关系标签 ``RELATED``，``type`` 为属性，按 (source, target, type) MERGE。
- PG 镜像供 ``visible_to`` 聚合 fallback 与 Task 4 双写一致性；读仍以 Neo4j 为权威。
- ``visible_to`` 在 Python 过滤（与内存实现语义一致；规模留给后续优化）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_content import EntityRecordORM, RelationRecordORM
from calliodesmo.interfaces.graph_store import (
    EntityRecord,
    GraphStore,
    RelationRecord,
    SubgraphView,
)
from calliodesmo.stores.visibility import visible_to


def _entity_props(e: EntityRecord) -> dict[str, Any]:
    """EntityRecord -> Neo4j 节点属性（owner_id/project_id/team_id 转 str，metadata JSON 串）。"""
    return {
        "name": e.name,
        "type": e.type,
        "description": e.description,
        "source_chunk_ids": list(e.source_chunk_ids),
        "template_conforming": e.template_conforming,
        # Neo4j 属性不支持 Map，metadata 序列化为 JSON 串
        "metadata": json.dumps(dict(e.metadata), ensure_ascii=False),
        "access_level": e.access_level.value,
        "library_scope": e.library_scope.value,
        "owner_id": str(e.owner_id) if e.owner_id else None,
        "project_id": str(e.project_id) if e.project_id else None,
        "team_id": str(e.team_id) if e.team_id else None,
    }


def _relation_props(r: RelationRecord) -> dict[str, Any]:
    return {
        "type": r.type,
        "description": r.description,
        "source_chunk_ids": list(r.source_chunk_ids),
        "metadata": json.dumps(dict(r.metadata), ensure_ascii=False),
        "access_level": r.access_level.value,
        "library_scope": r.library_scope.value,
        "owner_id": str(r.owner_id) if r.owner_id else None,
        "project_id": str(r.project_id) if r.project_id else None,
        "team_id": str(r.team_id) if r.team_id else None,
    }


def _node_to_entity(node: dict[str, Any]) -> EntityRecord:
    meta_raw = node.get("metadata")
    metadata = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw or {})
    return EntityRecord(
        name=node["name"],
        type=node.get("type"),
        description=node.get("description", ""),
        source_chunk_ids=list(node.get("source_chunk_ids", [])),
        template_conforming=bool(node.get("template_conforming", False)),
        metadata=metadata,
        access_level=ClearanceLevel(node.get("access_level", ClearanceLevel.INTERNAL.value)),
        library_scope=LibraryScope(node.get("library_scope", LibraryScope.PERSONAL.value)),
        owner_id=uuid.UUID(node["owner_id"]) if node.get("owner_id") else None,
        project_id=uuid.UUID(node["project_id"]) if node.get("project_id") else None,
        team_id=uuid.UUID(node["team_id"]) if node.get("team_id") else None,
    )


def _rel_to_relation(rel: dict[str, Any], source: str, target: str) -> RelationRecord:
    meta_raw = rel.get("metadata")
    metadata = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw or {})
    return RelationRecord(
        source=source,
        target=target,
        type=rel.get("type"),
        description=rel.get("description", ""),
        source_chunk_ids=list(rel.get("source_chunk_ids", [])),
        metadata=metadata,
        access_level=ClearanceLevel(rel.get("access_level", ClearanceLevel.INTERNAL.value)),
        library_scope=LibraryScope(rel.get("library_scope", LibraryScope.PERSONAL.value)),
        owner_id=uuid.UUID(rel["owner_id"]) if rel.get("owner_id") else None,
        project_id=uuid.UUID(rel["project_id"]) if rel.get("project_id") else None,
        team_id=uuid.UUID(rel["team_id"]) if rel.get("team_id") else None,
    )


def _entity_to_orm_values(e: EntityRecord) -> dict[str, Any]:
    return {
        "name": e.name,
        "type": e.type,
        "description": e.description,
        "template_conforming": e.template_conforming,
        "source_chunk_ids": list(e.source_chunk_ids),
        "provenance": dict(e.metadata).get("provenance", {}),
        "merge_decision": e.metadata.get("merge_decision")
        if isinstance(e.metadata, dict)
        else None,
        "owner_id": e.owner_id,
        "library_scope": e.library_scope,
        "project_id": e.project_id,
        "team_id": e.team_id,
        "access_level": e.access_level,
    }


def _relation_to_orm_values(r: RelationRecord) -> dict[str, Any]:
    return {
        "source": r.source,
        "target": r.target,
        "type": r.type,
        "description": r.description,
        "source_chunk_ids": list(r.source_chunk_ids),
        "owner_id": r.owner_id,
        "library_scope": r.library_scope,
        "project_id": r.project_id,
        "team_id": r.team_id,
        "access_level": r.access_level,
    }


class Neo4jGraphStore(GraphStore):
    """Neo4j 图库（权威）+ PG 镜像。经 driver 与 session_factory 自管资源。"""

    def __init__(self, driver, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._driver = driver
        self._session_factory = session_factory

    async def upsert_graph(
        self, entities: list[EntityRecord], relations: list[RelationRecord]
    ) -> None:
        # 1) Neo4j MERGE 节点 + 边
        async with self._driver.session() as s:
            for e in entities:
                props = _entity_props(e)
                await s.run(
                    """
                    MERGE (e:Entity {name: $name})
                    SET e.type = $type, e.description = $description,
                        e.source_chunk_ids = $source_chunk_ids,
                        e.template_conforming = $template_conforming,
                        e.metadata = $metadata, e.access_level = $access_level,
                        e.library_scope = $library_scope, e.owner_id = $owner_id,
                        e.project_id = $project_id, e.team_id = $team_id
                    """,
                    **props,
                )
            for r in relations:
                rprops = _relation_props(r)
                await s.run(
                    """
                    MATCH (src:Entity {name: $source}), (tgt:Entity {name: $target})
                    MERGE (src)-[rel:RELATED {type: $type}]->(tgt)
                    SET rel.description = $description,
                        rel.source_chunk_ids = $source_chunk_ids,
                        rel.metadata = $metadata, rel.access_level = $access_level,
                        rel.library_scope = $library_scope, rel.owner_id = $owner_id,
                        rel.project_id = $project_id, rel.team_id = $team_id
                    """,
                    **{"source": r.source, "target": r.target, **rprops},
                )
        # 2) PG 镜像 upsert（按复合唯一键 ON CONFLICT）
        async with self._session_factory() as session:
            for e in entities:
                vals = _entity_to_orm_values(e)
                await session.execute(
                    pg_insert(EntityRecordORM)
                    .values(**vals)
                    .on_conflict_do_update(
                        index_elements=["name", "library_scope", "owner_id"], set_=vals
                    )
                )
            for r in relations:
                vals = _relation_to_orm_values(r)
                await session.execute(
                    pg_insert(RelationRecordORM)
                    .values(**vals)
                    .on_conflict_do_update(
                        index_elements=["source", "target", "type", "library_scope", "owner_id"],
                        set_=vals,
                    )
                )
            await session.commit()

    async def get_entity(self, name: str, *, access: AccessContext) -> EntityRecord | None:
        async with self._driver.session() as s:
            result = await s.run("MATCH (e:Entity {name: $name}) RETURN e LIMIT 1", name=name)
            records = await result.fetch(1)
            if records:
                return self._filter_entity(records[0]["e"], access)
            # 大小写不敏感回退（档案卡展示名与图库原始名可能大小写不一）
            result = await s.run(
                "MATCH (e:Entity) WHERE toLower(e.name) = toLower($name) RETURN e LIMIT 1",
                name=name,
            )
            records = await result.fetch(1)
            if records:
                return self._filter_entity(records[0]["e"], access)
        return None

    @staticmethod
    def _filter_entity(node, access: AccessContext) -> EntityRecord | None:
        ent = _node_to_entity(dict(node))
        return ent if visible_to(ent, access) else None

    async def neighbors(
        self, name: str, *, access: AccessContext
    ) -> tuple[list[EntityRecord], list[RelationRecord]]:
        ent = await self.get_entity(name, access=access)
        if ent is None:
            return [], []
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (e:Entity {name: $name})-[r:RELATED]-(n:Entity)
                RETURN r, n, startNode(r).name AS source, endNode(r).name AS target
                """,
                name=name,
            )
            records = [r async for r in result]
        neighbor_map: dict[str, EntityRecord] = {}
        rel_hits: list[RelationRecord] = []
        for rec in records:
            rel = _rel_to_relation(dict(rec["r"]), rec["source"], rec["target"])
            if not visible_to(rel, access):
                continue
            rel_hits.append(rel)
            other_name = rec["target"] if rec["source"] == name else rec["source"]
            if other_name not in neighbor_map:
                n_ent = _node_to_entity(dict(rec["n"]))
                if visible_to(n_ent, access):
                    neighbor_map[other_name] = n_ent
        return list(neighbor_map.values()), rel_hits

    async def subgraph(
        self, seeds: list[str], *, hops: int, limit: int, access: AccessContext
    ) -> SubgraphView:
        """BFS 从 seeds 按 hops 扩展，limit 截断，全程 visible_to 过滤（同内存实现语义）。"""
        view = SubgraphView()
        seen: set[str] = set()
        frontier: list[str] = []
        for seed in seeds:
            ent = await self.get_entity(seed, access=access)
            if ent is None or ent.name in seen:
                continue
            seen.add(ent.name)
            view.nodes.append(ent)
            view.expanded_seeds.append(ent.name)
            frontier.append(ent.name)

        truncated = False
        for _ in range(max(hops, 0)):
            if not frontier or truncated:
                break
            next_frontier: list[str] = []
            for name in frontier:
                neighbors, _ = await self.neighbors(name, access=access)
                for n in neighbors:
                    if n.name in seen:
                        continue
                    if len(view.nodes) >= limit:
                        truncated = True
                        break
                    seen.add(n.name)
                    view.nodes.append(n)
                    next_frontier.append(n.name)
                if truncated:
                    break
            frontier = next_frontier
        view.truncated = truncated

        # 末端扫边：两端皆在图内且关系可见
        async with self._driver.session() as s:
            result = await s.run(
                """
                MATCH (src:Entity)-[r:RELATED]->(tgt:Entity)
                WHERE src.name IN $names AND tgt.name IN $names
                RETURN r, src.name AS source, tgt.name AS target
                """,
                names=list(seen),
            )
            records = [r async for r in result]
        for rec in records:
            rel = _rel_to_relation(dict(rec["r"]), rec["source"], rec["target"])
            if visible_to(rel, access):
                view.edges.append(rel)
        view.edges.sort(key=lambda r: (r.source, r.target, r.type or ""))
        return view

    async def list_entities(self, *, access: AccessContext) -> list[EntityRecord]:
        async with self._driver.session() as s:
            result = await s.run("MATCH (e:Entity) RETURN e")
            records = [r async for r in result]
        out = []
        for rec in records:
            ent = _node_to_entity(dict(rec["e"]))
            if visible_to(ent, access):
                out.append(ent)
        return out

    async def list_relations(self, *, access: AccessContext) -> list[RelationRecord]:
        async with self._driver.session() as s:
            result = await s.run(
                "MATCH (src:Entity)-[r:RELATED]->(tgt:Entity) RETURN r, src.name AS source, "
                "tgt.name AS target"
            )
            records = [r async for r in result]
        out = []
        for rec in records:
            rel = _rel_to_relation(dict(rec["r"]), rec["source"], rec["target"])
            if visible_to(rel, access):
                out.append(rel)
        return out
