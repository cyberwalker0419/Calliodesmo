"""InMemoryCommunityStore：社区摘要内存库（按 visible_to 过滤，按 level/title 排序）。"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.community_store import CommunityRecord, CommunityStore
from calliodesmo.stores.visibility import visible_to


class InMemoryCommunityStore(CommunityStore):
    def __init__(self) -> None:
        self._records: dict[str, CommunityRecord] = {}

    async def upsert_communities(self, communities: list[CommunityRecord]) -> None:
        for c in communities:
            self._records[c.community_id] = c  # 同 id 覆盖（幂等）

    async def list_communities(self, *, access: AccessContext) -> list[CommunityRecord]:
        visible = [r for r in self._records.values() if visible_to(r, access)]
        visible.sort(key=lambda r: (r.level, r.title))
        return visible

    def __len__(self) -> int:
        return len(self._records)
