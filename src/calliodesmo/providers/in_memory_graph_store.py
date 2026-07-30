"""InMemoryGraphStore：实体-关系图内存库（按 visible_to 过滤）。

upsert 幂等：实体按 name 覆盖；关系按 (source, target, type) 合并去重——
多次 ingest（增量建库/演示 seed）不互相清边。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.graph_store import (
    EntityRecord,
    GraphStore,
    RelationRecord,
    SubgraphView,
)
from calliodesmo.stores.visibility import visible_to


class InMemoryGraphStore(GraphStore):
    def __init__(self) -> None:
        self._entities: dict[str, EntityRecord] = {}
        self._relations: dict[tuple[str, str, str | None], RelationRecord] = {}

    async def upsert_graph(
        self, entities: list[EntityRecord], relations: list[RelationRecord]
    ) -> None:
        for e in entities:
            self._entities[e.name] = e  # 同 name 覆盖（幂等）
        for r in relations:
            self._relations[(r.source, r.target, r.type)] = r  # 同边覆盖（增量合并）

    async def get_entity(self, name: str, *, access: AccessContext) -> EntityRecord | None:
        rec = self._entities.get(name)
        if rec is None:
            # 大小写不敏感回退：档案卡展示名与图库原始名可能大小写不一
            key = name.strip().lower()
            rec = next((e for e in self._entities.values() if e.name.strip().lower() == key), None)
        if rec is None or not visible_to(rec, access):
            return None
        return rec

    async def neighbors(
        self, name: str, *, access: AccessContext
    ) -> tuple[list[EntityRecord], list[RelationRecord]]:
        ent = await self.get_entity(name, access=access)
        if ent is None:
            return [], []
        rel_hits: list[RelationRecord] = []
        neighbor_names: set[str] = set()
        for r in self._relations.values():
            if r.source == ent.name or r.target == ent.name:
                if visible_to(r, access):
                    rel_hits.append(r)
                    neighbor_names.add(r.target if r.source == ent.name else r.source)
        neighbors = [
            self._entities[n]
            for n in neighbor_names
            if n in self._entities and visible_to(self._entities[n], access)
        ]
        return neighbors, rel_hits

    async def subgraph(
        self, seeds: list[str], *, hops: int, limit: int, access: AccessContext
    ) -> SubgraphView:
        """BFS 从 seeds 按 hops 扩展，limit 截断，全程 visible_to 过滤。

        两阶段：先 BFS 收集节点（去重、达上限截断），再扫关系表收两端皆在
        图内的可见边（避免悬空边）。命中的种子（可见且存在）记入 expanded_seeds。
        """
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

        # 末端扫边：两端皆在图内且关系本身可见
        for r in self._relations.values():
            if r.source in seen and r.target in seen and visible_to(r, access):
                view.edges.append(r)
        view.edges.sort(key=lambda r: (r.source, r.target, r.type or ""))  # 确定性
        return view

    async def list_entities(self, *, access: AccessContext) -> list[EntityRecord]:
        """枚举当前可见的全部实体（按 visible_to 过滤）。"""
        return [e for e in self._entities.values() if visible_to(e, access)]

    async def list_relations(self, *, access: AccessContext) -> list[RelationRecord]:
        """枚举当前可见的全部关系（按 visible_to 过滤）。"""
        return [r for r in self._relations.values() if visible_to(r, access)]

    async def delete_by_doc(self, chunk_ids: list[str]) -> None:
        """P4.5 Task 3：prune_source_chunks 剔除 chunk_ids 引用，孤儿实体删、空边丢。"""
        from calliodesmo.collab.graph_merge import prune_source_chunks

        _kept_e, kept_r, _orphans = prune_source_chunks(
            list(self._entities.values()),
            list(self._relations.values()),
            remove_chunk_ids=set(chunk_ids),
        )
        # prune 已丢弃孤儿实体与空边；按 name / (source,target,type) 重建索引
        self._entities = {e.name: e for e in _kept_e}
        self._relations = {(r.source, r.target, r.type): r for r in kept_r}

    def __len__(self) -> int:
        return len(self._entities)
