import pytest
from sqlalchemy import select

from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
    User,
    UserGroup,
    UserGroupMember,
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
        "user_groups",
        "user_group_members",
        "audit_logs",
    } <= tables


async def test_user_role_group_roundtrip(session):
    user = User(username="alice", hashed_password="x", clearance=ClearanceLevel.CONFIDENTIAL)
    role = Role(name="analyst", description="分析师")
    role.permissions = [
        RolePermission(permission=Permission.QUERY),
        RolePermission(permission=Permission.INGEST),
    ]
    group = UserGroup(name="X调查组", scope=LibraryScope.ORG)
    session.add_all([user, role, group])
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, scope=LibraryScope.ORG))
    session.add(UserGroupMember(user_id=user.id, group_id=group.id, role_in_group="manager"))
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
