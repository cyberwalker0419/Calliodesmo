"""PgCommunityStore：摘要层社区库真后端（Postgres + 摘要向量），按 AccessContext 过滤。

P4.5 Task 2 Step 4。对齐 :class:`~calliodesmo.interfaces.community_store.CommunityStore`
契约：``upsert_communities`` / ``list_communities``（visible_to + level/title 排序）/ P3 手动操作
（rename / set_access_level / add_member_doc / remove_member_doc，置 ``metadata["manual"]=True``）/
P4 ``merge`` / ``split``。rollback 真后端适配见 Task 4。
"""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_content import CommunityRecordORM
from calliodesmo.interfaces.community_store import CommunityRecord, CommunityStore
from calliodesmo.stores.visibility import visible_to


def _visible_filter(access: AccessContext):
    """复刻 visible_to 为 SQL 谓词。"""
    allowed_levels = [lvl for lvl in ClearanceLevel if lvl.value <= access.clearance.value]
    return and_(
        CommunityRecordORM.access_level.in_(allowed_levels),
        or_(
            and_(
                CommunityRecordORM.library_scope == LibraryScope.PERSONAL,
                CommunityRecordORM.owner_id == access.user_id,
            ),
            and_(
                CommunityRecordORM.library_scope == LibraryScope.PROJECT,
                CommunityRecordORM.project_id.in_(access.project_ids),
            ),
            and_(
                CommunityRecordORM.library_scope == LibraryScope.TEAM,
                CommunityRecordORM.team_id.in_(access.team_ids),
            ),
        ),
    )


def _row_to_record(row: CommunityRecordORM) -> CommunityRecord:
    md = dict(row.metadata_) if row.metadata_ is not None else {}
    return CommunityRecord(
        community_id=row.community_id,
        level=row.level,
        title=row.title,
        summary=row.summary,
        member_entity_names=list(row.member_entity_names) if row.member_entity_names else [],
        metadata=md,
        access_level=row.access_level,
        library_scope=row.library_scope,
        owner_id=row.owner_id,
        project_id=row.project_id,
        team_id=row.team_id,
    )


class PgCommunityStore(CommunityStore):
    """PG 社区库。经 session factory 自管会话。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_communities(self, communities: list[CommunityRecord]) -> None:
        if not communities:
            return
        async with self._session_factory() as session:
            for c in communities:
                row = {
                    "community_id": c.community_id,
                    "level": c.level,
                    "title": c.title,
                    "summary": c.summary,
                    "summary_embedding": None,
                    "member_doc_ids": [],
                    "member_entity_names": list(c.member_entity_names),
                    "owner_id": c.owner_id,
                    "library_scope": c.library_scope,
                    "project_id": c.project_id,
                    "team_id": c.team_id,
                    "access_level": c.access_level,
                }
                set_ = {**row, CommunityRecordORM.metadata_: c.metadata}
                values = {**row, CommunityRecordORM.metadata_: c.metadata}
                await session.execute(
                    pg_insert(CommunityRecordORM)
                    .values(values)
                    .on_conflict_do_update(index_elements=["community_id"], set_=set_)
                )
            await session.commit()

    async def list_communities(self, *, access: AccessContext) -> list[CommunityRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(CommunityRecordORM)
                .where(_visible_filter(access))
                .order_by(CommunityRecordORM.level, CommunityRecordORM.title)
            )
            return [_row_to_record(row) for row in result.scalars()]

    async def _get_visible(
        self, session: AsyncSession, community_id: str, access: AccessContext
    ) -> CommunityRecordORM | None:
        row = (
            await session.execute(
                select(CommunityRecordORM)
                .where(CommunityRecordORM.community_id == community_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or not visible_to(_row_to_record(row), access):
            return None
        return row

    async def _edit(self, community_id: str, access: AccessContext) -> CommunityRecordORM | None:
        """取可见社区并置 metadata["manual"]=True（P3 手动标记）。"""
        async with self._session_factory() as session:
            row = await self._get_visible(session, community_id, access)
            if row is None:
                return None
            md = dict(row.metadata_) if row.metadata_ is not None else {}
            md["manual"] = True
            row.metadata_ = md
            await session.commit()
            return row

    async def rename(self, community_id: str, title: str, *, access: AccessContext) -> bool:
        row = await self._edit(community_id, access)
        if row is None:
            return False
        async with self._session_factory() as session:
            db_row = await session.get(CommunityRecordORM, community_id)
            if db_row is not None:
                db_row.title = title
                await session.commit()
        return True

    async def set_access_level(
        self, community_id: str, level: ClearanceLevel, *, access: AccessContext
    ) -> bool:
        row = await self._edit(community_id, access)
        if row is None:
            return False
        async with self._session_factory() as session:
            db_row = await session.get(CommunityRecordORM, community_id)
            if db_row is not None:
                db_row.access_level = level
                await session.commit()
        return True

    async def add_member_doc(
        self, community_id: str, doc_id: str, *, access: AccessContext, note: str = ""
    ) -> bool:
        row = await self._edit(community_id, access)
        if row is None:
            return False
        async with self._session_factory() as session:
            db_row = await session.get(CommunityRecordORM, community_id)
            if db_row is None:
                return False
            members = list(db_row.member_entity_names or [])
            if doc_id not in members:
                members.append(doc_id)
                db_row.member_entity_names = members
                await session.commit()
        return True

    async def remove_member_doc(
        self, community_id: str, doc_id: str, *, access: AccessContext
    ) -> bool:
        row = await self._edit(community_id, access)
        if row is None:
            return False
        async with self._session_factory() as session:
            db_row = await session.get(CommunityRecordORM, community_id)
            if db_row is None:
                return False
            members = list(db_row.member_entity_names or [])
            if doc_id in members:
                members.remove(doc_id)
                db_row.member_entity_names = members
                await session.commit()
        return True

    async def merge(self, target_id: str, source_ids: list[str], *, access: AccessContext) -> bool:
        """合并 source 到 target（member 并集、summary 拼接、access 取较严），删 source。"""
        async with self._session_factory() as session:
            target = await self._get_visible(session, target_id, access)
            if target is None:
                return False
            members = list(target.member_entity_names or [])
            summaries = [target.summary] if target.summary else []
            access_level = target.access_level
            for sid in source_ids:
                src = (
                    await session.execute(
                        select(CommunityRecordORM).where(CommunityRecordORM.community_id == sid)
                    )
                ).scalar_one_or_none()
                if src is None or src.community_id == target_id:
                    continue
                if not visible_to(_row_to_record(src), access):
                    continue
                for m in src.member_entity_names or []:
                    if m not in members:
                        members.append(m)
                if src.summary and src.summary not in summaries:
                    summaries.append(src.summary)
                access_level = max(access_level, src.access_level)
                await session.delete(src)
            target.member_entity_names = members
            target.summary = "；".join(summaries)
            target.access_level = access_level
            md = dict(target.metadata_) if target.metadata_ is not None else {}
            md["manual"] = True
            target.metadata_ = md
            await session.commit()
        return True

    async def split(
        self, community_id: str, doc_groups: list[list[str]], *, access: AccessContext
    ) -> list[str]:
        """按 doc_groups 拆分社区成多社区，返回新社区 id 列表（原社区保留）。"""
        async with self._session_factory() as session:
            rec = await self._get_visible(session, community_id, access)
            if rec is None:
                return []
            new_ids: list[str] = []
            for i, group in enumerate(doc_groups):
                new_id = f"{community_id}-split-{i}"
                new_row = CommunityRecordORM(
                    community_id=new_id,
                    level=rec.level,
                    title=f"{rec.title}（拆分{i}）",
                    summary=rec.summary,
                    summary_embedding=None,
                    member_doc_ids=[],
                    member_entity_names=list(group),
                    owner_id=rec.owner_id,
                    library_scope=rec.library_scope,
                    project_id=rec.project_id,
                    team_id=rec.team_id,
                    access_level=rec.access_level,
                    metadata_={**dict(rec.metadata_ or {}), "manual": True},
                )
                session.add(new_row)
                new_ids.append(new_id)
            await session.commit()
            return new_ids
