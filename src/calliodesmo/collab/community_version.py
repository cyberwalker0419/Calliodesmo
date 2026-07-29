"""社区版本快照（ORM）+ 版本服务（create/list/rollback，append 式回滚）。

版本快照走 ORM（JSON snapshot，与 auth/audit 同库，可查询可追溯）；社区记录本身走内存
CommunityStore（单进程）。rollback 用旧版本快照恢复 store 并**创建一个新版本**（git revert
思路，回滚也是新提交），保留完整审计链，非"栈式只回滚上一版"（B3 修订）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.base import Base
from calliodesmo.interfaces.community_store import CommunityRecord


class CommunityVersion(Base):
    """社区版本快照：某社区某版本的 CommunityRecord 快照（JSON）。"""

    __tablename__ = "community_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    community_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


def snapshot_record(rec: CommunityRecord) -> dict:
    """CommunityRecord -> 可 JSON 序列化的快照 dict（enum 转 value，UUID 转 str）。"""
    return {
        "community_id": rec.community_id,
        "level": rec.level,
        "title": rec.title,
        "summary": rec.summary,
        "member_entity_names": list(rec.member_entity_names),
        "metadata": dict(rec.metadata),
        "access_level": int(rec.access_level),
        "library_scope": rec.library_scope.value,
        "owner_id": str(rec.owner_id) if rec.owner_id else None,
        "project_id": str(rec.project_id) if rec.project_id else None,
        "team_id": str(rec.team_id) if rec.team_id else None,
    }


def restore_record(snapshot: dict) -> CommunityRecord:
    """快照 dict -> CommunityRecord（value 转 enum，str 转 UUID）。"""
    access = snapshot["access_level"]
    access_level = ClearanceLevel(access) if isinstance(access, int) else ClearanceLevel[access]
    return CommunityRecord(
        community_id=snapshot["community_id"],
        level=snapshot["level"],
        title=snapshot["title"],
        summary=snapshot["summary"],
        member_entity_names=list(snapshot.get("member_entity_names", [])),
        metadata=dict(snapshot.get("metadata", {})),
        access_level=access_level,
        library_scope=LibraryScope(snapshot["library_scope"]),
        owner_id=uuid.UUID(snapshot["owner_id"]) if snapshot.get("owner_id") else None,
        project_id=uuid.UUID(snapshot["project_id"]) if snapshot.get("project_id") else None,
        team_id=uuid.UUID(snapshot["team_id"]) if snapshot.get("team_id") else None,
    )


class CommunityVersionService:
    """社区版本快照服务：create / list / rollback（append 式）。"""

    async def create_version(
        self,
        session: AsyncSession,
        *,
        community_id: str,
        snapshot: dict,
        created_by: uuid.UUID | None,
    ) -> CommunityVersion:
        existing = (
            await session.execute(
                select(CommunityVersion)
                .where(CommunityVersion.community_id == community_id)
                .order_by(CommunityVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        next_version = (existing.version + 1) if existing else 1
        version = CommunityVersion(
            community_id=community_id,
            version=next_version,
            snapshot=snapshot,
            created_by=created_by,
        )
        session.add(version)
        await session.flush()
        return version

    async def list_versions(
        self, session: AsyncSession, community_id: str
    ) -> list[CommunityVersion]:
        result = await session.execute(
            select(CommunityVersion)
            .where(CommunityVersion.community_id == community_id)
            .order_by(CommunityVersion.version)
        )
        return list(result.scalars().all())

    async def rollback(
        self,
        session: AsyncSession,
        community_id: str,
        version: int,
        *,
        store,
        created_by: uuid.UUID | None,
    ) -> CommunityVersion:
        """用旧版本快照恢复 store + 创建新版本（append 式，不删历史，B3 修订）。"""
        old = (
            await session.execute(
                select(CommunityVersion).where(
                    CommunityVersion.community_id == community_id,
                    CommunityVersion.version == version,
                )
            )
        ).scalar_one_or_none()
        if old is None:
            raise ValueError(f"版本 {version} 不存在（社区 {community_id}）")
        record = restore_record(old.snapshot)
        await store.upsert_communities([record])  # 覆盖恢复
        # 创建新版本（回滚也是新提交，保留完整审计链）
        return await self.create_version(
            session,
            community_id=community_id,
            snapshot=old.snapshot,
            created_by=created_by,
        )
