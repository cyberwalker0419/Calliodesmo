"""InMemoryCommunityStore：社区摘要内存库（按 visible_to 过滤，按 level/title 排序）。

P3 手动操作（rename/set_access_level/add/remove_member_doc）置 ``metadata["manual"]``
标记，自动派生跳过 manual 社区不覆盖手改。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
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

    def _mark_manual(self, rec: CommunityRecord) -> CommunityRecord:
        md = dict(rec.metadata)
        md["manual"] = True
        rec.metadata = md
        return rec

    async def _edit(self, community_id: str, access: AccessContext) -> CommunityRecord | None:
        rec = self._records.get(community_id)
        if rec is None or not visible_to(rec, access):
            return None
        return self._mark_manual(rec)

    async def rename(self, community_id: str, title: str, *, access: AccessContext) -> bool:
        rec = await self._edit(community_id, access)
        if rec is None:
            return False
        rec.title = title
        return True

    async def set_access_level(
        self, community_id: str, level: ClearanceLevel, *, access: AccessContext
    ) -> bool:
        rec = await self._edit(community_id, access)
        if rec is None:
            return False
        rec.access_level = level
        return True

    async def add_member_doc(
        self, community_id: str, doc_id: str, *, access: AccessContext, note: str = ""
    ) -> bool:
        rec = await self._edit(community_id, access)
        if rec is None:
            return False
        if doc_id not in rec.member_entity_names:
            rec.member_entity_names.append(doc_id)
        return True

    async def remove_member_doc(
        self, community_id: str, doc_id: str, *, access: AccessContext
    ) -> bool:
        rec = await self._edit(community_id, access)
        if rec is None:
            return False
        if doc_id in rec.member_entity_names:
            rec.member_entity_names.remove(doc_id)
        return True

    async def merge(self, target_id: str, source_ids: list[str], *, access: AccessContext) -> bool:
        """合并 source 社区到 target（member 并集、summary 拼接、access 取较严），删 source。"""
        records = {r.community_id: r for r in await self.list_communities(access=access)}
        target = records.get(target_id)
        if target is None:
            return False
        members = list(target.member_entity_names)
        summaries = [target.summary] if target.summary else []
        access_level = target.access_level
        for sid in source_ids:
            s = records.get(sid)
            if s is None or s.community_id == target_id:
                continue
            for m in s.member_entity_names:
                if m not in members:
                    members.append(m)
            if s.summary and s.summary not in summaries:
                summaries.append(s.summary)
            access_level = max(access_level, s.access_level)
            self._records.pop(sid, None)  # 删 source
        target.member_entity_names = members
        target.summary = "；".join(summaries)
        target.access_level = access_level
        self._mark_manual(target)
        return True

    async def split(
        self,
        community_id: str,
        doc_groups: list[list[str]],
        *,
        access: AccessContext,
    ) -> list[str]:
        """按 doc_groups 拆分社区成多社区，返回新社区 id 列表。"""
        rec = self._records.get(community_id)
        if rec is None or not visible_to(rec, access):
            return []
        new_ids: list[str] = []
        for i, group in enumerate(doc_groups):
            new_id = f"{community_id}-split-{i}"
            new_rec = CommunityRecord(
                community_id=new_id,
                level=rec.level,
                title=f"{rec.title}（拆分{i}）",
                summary=rec.summary,
                member_entity_names=list(group),
                metadata=dict(rec.metadata),
                access_level=rec.access_level,
                library_scope=rec.library_scope,
                owner_id=rec.owner_id,
                project_id=rec.project_id,
                team_id=rec.team_id,
            )
            self._mark_manual(new_rec)
            self._records[new_id] = new_rec
            new_ids.append(new_id)
        return new_ids

    def __len__(self) -> int:
        return len(self._records)
