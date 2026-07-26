import pytest
from sqlalchemy import select

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
from calliodesmo.db.base import Base


def test_metadata_registers_p0_tables():
    tables = set(Base.metadata.tables)
    assert {
        "users",
        "roles",
        "role_permissions",
        "user_roles",
        "teams",
        "projects",
        "team_members",
        "project_members",
        "audit_logs",
    } <= tables


async def test_user_role_team_project_roundtrip(session):
    user = User(username="alice", hashed_password="x", clearance=ClearanceLevel.CONFIDENTIAL)
    role = Role(name="analyst", description="分析师")
    role.permissions = [
        RolePermission(permission=Permission.QUERY),
        RolePermission(permission=Permission.INGEST),
    ]
    team = Team(name="X调查团队")
    session.add_all([user, role, team])
    await session.flush()
    project = Project(name="项目Alpha", team_id=team.id)
    session.add(project)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, scope=LibraryScope.TEAM))
    session.add(TeamMember(user_id=user.id, team_id=team.id, role_in_team="manager"))
    session.add(
        ProjectMember(
            user_id=user.id,
            project_id=project.id,
            role_id=role.id,
            role_in_project="maintainer",
        )
    )
    await session.commit()

    result = (await session.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert result.clearance == ClearanceLevel.CONFIDENTIAL
    assert result.is_active is True


async def test_duplicate_username_rejected(session):
    session.add(User(username="dup", hashed_password="x"))
    await session.flush()
    session.add(User(username="dup", hashed_password="y"))
    with pytest.raises(Exception):  # noqa: B017  IntegrityError 后端相关，不断言具体类型
        await session.flush()
