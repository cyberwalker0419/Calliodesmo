"""InMemoryGraphStore：实体-关系图内存库（按 visible_to 过滤）。"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.graph_store import EntityRecord, GraphStore, RelationRecord
from calliodesmo.stores.visibility import visible_to


class InMemoryGraphStore(GraphStore):
    def __init__(self) -> None:
        self._entities: dict[str, EntityRecord] = {}
        self._relations: list[RelationRecord] = []

    async def upsert_graph(
        self, entities: list[EntityRecord], relations: list[RelationRecord]
    ) -> None:
        for e in entities:
            self._entities[e.name] = e  # 同 name 覆盖（幂等）
        self._relations = list(relations)

    async def get_entity(self, name: str, *, access: AccessContext) -> EntityRecord | None:
        rec = self._entities.get(name)
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
        for r in self._relations:
            if r.source == name or r.target == name:
                if visible_to(r, access):
                    rel_hits.append(r)
                    neighbor_names.add(r.target if r.source == name else r.source)
        neighbors = [
            self._entities[n]
            for n in neighbor_names
            if n in self._entities and visible_to(self._entities[n], access)
        ]
        return neighbors, rel_hits

    def __len__(self) -> int:
        return len(self._entities)
