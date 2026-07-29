"""Task 3：审核(Review)与指派到组 + 自审阻断。"""

import uuid

import pytest
from sqlalchemy import select

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Project,
    ProjectMember,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
    UserRole,
)
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionError, ContributionService

_svc = ContributionService()


async def _user(session, name) -> User:
    u = User(username=name, hashed_password="x", clearance=ClearanceLevel.INTERNAL)
    session.add(u)
    await session.flush()
    return u


async def _role(session, name, permissions) -> Role:
    role = Role(name=name, description="")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    await session.flush()
    return role


async def _project(session) -> Project:
    team = Team(name=f"t-{uuid.uuid4().hex[:6]}", description="")
    session.add(team)
    await session.flush()
    project = Project(name=f"p-{uuid.uuid4().hex[:6]}", description="", team_id=team.id)
    session.add(project)
    await session.flush()
    return project


async def _draft_to_project(session, source, project):
    return await _svc.create(
        session,
        source_user_id=source.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project.id,
        title="t",
        doc_ids=["d#0"],
    )


async def test_submit_auto_assign_project_reviewer(session):
    """project 指派：ProjectMember.role_id 关联的 Role 含 APPROVE。"""
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    role = await _role(session, "reviewer", {Permission.APPROVE})
    project = await _project(session)
    session.add(ProjectMember(user_id=reviewer.id, project_id=project.id, role_id=role.id))
    await session.flush()
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id)
    fetched = await session.get(Contribution, c.id)
    assert fetched.assignee_id == reviewer.id
    assert fetched.status == ContributionStatus.SUBMITTED


async def test_submit_auto_assign_team_reviewer(session):
    """A5：team 指派走 UserRole 全局含 APPROVE（不按 role_in_team 字符串匹配）。"""
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    other_member = await _user(session, "other")  # 团队成员但无 APPROVE
    role = await _role(session, "reviewer", {Permission.APPROVE})
    team = Team(name=f"t-{uuid.uuid4().hex[:6]}", description="")
    session.add(team)
    await session.flush()
    session.add_all(
        [
            TeamMember(user_id=reviewer.id, team_id=team.id, role_in_team="member"),
            TeamMember(user_id=other_member.id, team_id=team.id, role_in_team="reviewer"),
        ]
    )
    # reviewer 全局持 APPROVE（UserRole scope=TEAM），other_member 没有
    session.add(UserRole(user_id=reviewer.id, role_id=role.id, scope=LibraryScope.TEAM))
    await session.flush()
    c = await _svc.create(
        session,
        source_user_id=source.id,
        source_scope=LibraryScope.PROJECT,
        target_scope=LibraryScope.TEAM,
        target_team_id=team.id,
        title="t",
        doc_ids=["d#0"],
    )
    await _svc.submit(session, c.id, user_id=source.id)
    fetched = await session.get(Contribution, c.id)
    # 指派到真正持 APPROVE 的 reviewer，而非 role_in_team="reviewer" 的 other_member
    assert fetched.assignee_id == reviewer.id


async def test_submit_no_reviewer_assignee_none(session):
    source = await _user(session, "source")
    project = await _project(session)
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id)
    fetched = await session.get(Contribution, c.id)
    assert fetched.assignee_id is None  # 无可用 reviewer，待指派


async def test_submit_explicit_assignee(session):
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    project = await _project(session)
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id, assignee_id=reviewer.id)
    fetched = await session.get(Contribution, c.id)
    assert fetched.assignee_id == reviewer.id


async def test_approve_self_review_blocked(session):
    """自审阻断：源用户不能 approve 自己的推送。"""
    source = await _user(session, "source")
    project = await _project(session)
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id)
    with pytest.raises(ContributionError, match="自审阻断"):
        await _svc.approve(session, c.id, user_id=source.id)


async def test_merge_self_review_blocked(session):
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    project = await _project(session)
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id)
    await _svc.approve(session, c.id, user_id=reviewer.id)
    with pytest.raises(ContributionError, match="自审阻断"):
        await _svc.merge(session, c.id, user_id=source.id)


async def test_reject_records_audit(session):
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    project = await _project(session)
    c = await _draft_to_project(session, source, project)
    await _svc.submit(session, c.id, user_id=source.id)
    await _svc.reject(session, c.id, user_id=reviewer.id, reason="证据不足")
    fetched = await session.get(Contribution, c.id)
    assert fetched.status == ContributionStatus.REJECTED
    assert fetched.reviewed_by == reviewer.id
    logs = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "reject", AuditLog.resource_id == str(c.id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail.get("reason") == "证据不足"
