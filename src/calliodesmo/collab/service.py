"""ContributionService：贡献请求状态机驱动（create/submit/approve/reject/merge/close/reopen/list/get）。

状态机：``draft -> submitted -> approved/rejected -> merged``；外加 ``closed`` 终态；
``rejected`` 可 ``reopen -> submitted``（保留同一 MR 上下文）。权限守卫与自审阻断在 Task 3 接入。

并发【修订】：``version`` 乐观锁（SQLAlchemy ``version_id_col``，UPDATE WHERE version=?，
冲突抛 ``StaleDataError``）+ 流转内 ``with_for_update`` 行锁（Postgres 生效，SQLite no-op）。

审计：全程 ``record_audit``（push/submit/approve/reject/merge/close）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import LibraryScope, Permission
from calliodesmo.collab.models import Contribution, ContributionStatus


class ContributionError(Exception):
    """贡献状态机非法操作（非法跳转 / 校验失败）。"""


class ContributionNotFoundError(Exception):
    """贡献不存在或越权不可见。"""


class ContributionService:
    async def create(
        self,
        session: AsyncSession,
        *,
        source_user_id: uuid.UUID,
        source_scope: LibraryScope,
        target_scope: LibraryScope,
        title: str,
        doc_ids: list[str],
        description: str = "",
        target_project_id: uuid.UUID | None = None,
        target_team_id: uuid.UUID | None = None,
        source: str | None = None,
    ) -> Contribution:
        # 校验推送方向：target 须高于 source（防降向推送）
        if target_scope.rank <= source_scope.rank:
            raise ContributionError(
                f"目标 scope 须高于源 scope：{source_scope.value} -> {target_scope.value}"
            )
        # 校验目标 id 与 target_scope 匹配
        if target_scope == LibraryScope.PROJECT and target_project_id is None:
            raise ContributionError("target_scope=project 须带 target_project_id")
        if target_scope == LibraryScope.TEAM and target_team_id is None:
            raise ContributionError("target_scope=team 须带 target_team_id")
        contribution = Contribution(
            source_user_id=source_user_id,
            source_scope=source_scope,
            target_scope=target_scope,
            target_project_id=target_project_id,
            target_team_id=target_team_id,
            title=title,
            description=description,
            status=ContributionStatus.DRAFT,
            doc_ids=list(doc_ids),
        )
        session.add(contribution)
        await session.flush()
        await record_audit(
            session,
            user_id=source_user_id,
            action="push",
            resource_type="contribution",
            resource_id=str(contribution.id),
            detail={
                "status": ContributionStatus.DRAFT.value,
                "source_scope": source_scope.value,
                "target_scope": target_scope.value,
                "doc_ids": list(doc_ids),
            },
            source=source,
        )
        await session.flush()
        return contribution

    async def _transition(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        from_statuses: set[ContributionStatus],
        to_status: ContributionStatus,
        action: str,
        user_id: uuid.UUID,
        detail: dict | None = None,
        source: str | None = None,
        extra_updates: dict | None = None,
    ) -> Contribution:
        # 行锁（Postgres）+ 乐观锁 version_id_col（UPDATE WHERE version=?）
        stmt = select(Contribution).where(Contribution.id == contribution_id).with_for_update()
        contribution = (await session.execute(stmt)).scalar_one_or_none()
        if contribution is None:
            raise ContributionNotFoundError(f"贡献 {contribution_id} 不存在")
        if contribution.status not in from_statuses:
            raise ContributionError(
                f"非法状态跳转：{contribution.status.value} -> {to_status.value}"
                f"（须从 {sorted(s.value for s in from_statuses)} 起）"
            )
        contribution.status = to_status
        if extra_updates:
            for key, value in extra_updates.items():
                setattr(contribution, key, value)
        await session.flush()
        await record_audit(
            session,
            user_id=user_id,
            action=action,
            resource_type="contribution",
            resource_id=str(contribution.id),
            detail=detail or {},
            source=source,
        )
        await session.flush()
        return contribution

    async def submit(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> Contribution:
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.DRAFT},
            to_status=ContributionStatus.SUBMITTED,
            action="submit",
            user_id=user_id,
            source=source,
        )

    async def approve(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> Contribution:
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.SUBMITTED},
            to_status=ContributionStatus.APPROVED,
            action="approve",
            user_id=user_id,
            source=source,
            extra_updates={"reviewed_by": user_id, "reviewed_at": datetime.now(UTC)},
        )

    async def reject(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        reason: str | None = None,
        source: str | None = None,
    ) -> Contribution:
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.SUBMITTED},
            to_status=ContributionStatus.REJECTED,
            action="reject",
            user_id=user_id,
            source=source,
            detail={"reason": reason} if reason else None,
            extra_updates={"reviewed_by": user_id, "reviewed_at": datetime.now(UTC)},
        )

    async def reopen(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> Contribution:
        # 【修订】rejected -> submitted，保留同一 MR 上下文（作者修改重提，非新建 MR）
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.REJECTED},
            to_status=ContributionStatus.SUBMITTED,
            action="submit",
            user_id=user_id,
            source=source,
            detail={"reopen": True},
        )

    async def merge(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> Contribution:
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.APPROVED},
            to_status=ContributionStatus.MERGED,
            action="merge",
            user_id=user_id,
            source=source,
            extra_updates={"merged_at": datetime.now(UTC)},
        )

    async def close(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> Contribution:
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.DRAFT, ContributionStatus.SUBMITTED},
            to_status=ContributionStatus.CLOSED,
            action="close",
            user_id=user_id,
            source=source,
        )

    async def get(
        self, session: AsyncSession, contribution_id: uuid.UUID, *, access: AccessContext
    ) -> Contribution | None:
        contribution = await session.get(Contribution, contribution_id)
        if contribution is None:
            return None
        return contribution if self._visible(contribution, access) else None

    async def list(
        self,
        session: AsyncSession,
        *,
        access: AccessContext,
        status: ContributionStatus | None = None,
        target_scope: LibraryScope | None = None,
    ) -> list[Contribution]:
        stmt = select(Contribution)
        if status is not None:
            stmt = stmt.where(Contribution.status == status)
        if target_scope is not None:
            stmt = stmt.where(Contribution.target_scope == target_scope)
        result = await session.execute(stmt)
        return [c for c in result.scalars().all() if self._visible(c, access)]

    @staticmethod
    def _visible(contribution: Contribution, access: AccessContext) -> bool:
        """可见性：源用户本人 或 目标 scope 内持 APPROVE 权限的成员。"""
        if contribution.source_user_id == access.user_id:
            return True
        if contribution.target_scope == LibraryScope.PROJECT:
            return contribution.target_project_id in access.project_ids and access.has_permission(
                Permission.APPROVE
            )
        if contribution.target_scope == LibraryScope.TEAM:
            return contribution.target_team_id in access.team_ids and access.has_permission(
                Permission.APPROVE
            )
        return False
