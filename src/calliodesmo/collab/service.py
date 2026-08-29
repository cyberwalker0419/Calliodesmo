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

# reviewed_at/merged_at 写 aware UTC datetime：ORM 列为 TIMESTAMPTZ（DateTime(timezone=True)，
# P6 Task 1 闭环 2026-W31 逾期 TODO）。
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    LibraryScope,
    Permission,
    ProjectMember,
    RolePermission,
    TeamMember,
    UserRole,
)
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
        self_review_blocked: bool = False,
    ) -> Contribution:
        # 行锁（Postgres）+ 乐观锁 version_id_col（UPDATE WHERE version=?）
        stmt = select(Contribution).where(Contribution.id == contribution_id).with_for_update()
        contribution = (await session.execute(stmt)).scalar_one_or_none()
        if contribution is None:
            raise ContributionNotFoundError(f"贡献 {contribution_id} 不存在")
        if self_review_blocked and contribution.source_user_id == user_id:
            raise ContributionError("不能审核/合并自己的推送（自审阻断）")
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
        assignee_id: uuid.UUID | None = None,
    ) -> Contribution:
        # 自动指派：显式 assignee_id 优先；否则目标 scope 首个持 APPROVE 成员；无则 None（待指派）
        if assignee_id is None:
            contribution = await session.get(Contribution, contribution_id)
            approvers = (
                await self._find_approvers(session, contribution)
                if contribution is not None
                else []
            )
            assignee_id = approvers[0] if approvers else None
        extra = {"assignee_id": assignee_id} if assignee_id else None
        detail = {"assignee_id": str(assignee_id)} if assignee_id else {"assignee": "待指派"}
        return await self._transition(
            session,
            contribution_id,
            from_statuses={ContributionStatus.DRAFT},
            to_status=ContributionStatus.SUBMITTED,
            action="submit",
            user_id=user_id,
            source=source,
            extra_updates=extra,
            detail=detail,
        )

    async def _find_approvers(
        self, session: AsyncSession, contribution: Contribution
    ) -> list[uuid.UUID]:
        """目标 scope 内持 APPROVE 权限的成员。

        A5：team 走 UserRole 全局含 APPROVE（TeamMember 无 RBAC 外键），
        project 走 ProjectMember.role_id 关联的 Role。
        """
        if contribution.target_scope == LibraryScope.PROJECT:
            stmt = (
                select(ProjectMember.user_id)
                .join(RolePermission, ProjectMember.role_id == RolePermission.role_id)
                .where(
                    ProjectMember.project_id == contribution.target_project_id,
                    RolePermission.permission == Permission.APPROVE,
                )
                .order_by(ProjectMember.user_id)
            )
            return list((await session.execute(stmt)).scalars().all())
        if contribution.target_scope == LibraryScope.TEAM:
            # A5：TeamMember 仅有 role_in_team 字符串、无 RBAC 角色外键，
            # 故 team 候选 = 该团队成员中 UserRole 全局含 APPROVE 者（不按 role_in_team 匹配）
            team_member_ids = list(
                (
                    await session.execute(
                        select(TeamMember.user_id).where(
                            TeamMember.team_id == contribution.target_team_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            approvers: list[uuid.UUID] = []
            for uid in team_member_ids:
                hit = (
                    await session.execute(
                        select(UserRole.user_id)
                        .join(RolePermission, UserRole.role_id == RolePermission.role_id)
                        .where(
                            UserRole.user_id == uid,
                            RolePermission.permission == Permission.APPROVE,
                        )
                        .limit(1)
                    )
                ).first()
                if hit:
                    approvers.append(uid)
            approvers.sort()
            return approvers
        return []

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
            extra_updates={
                "reviewed_by": user_id,
                "reviewed_at": datetime.now(UTC),
            },
            self_review_blocked=True,
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
            extra_updates={
                "reviewed_by": user_id,
                "reviewed_at": datetime.now(UTC),
            },
            self_review_blocked=True,
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
            self_review_blocked=True,
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
