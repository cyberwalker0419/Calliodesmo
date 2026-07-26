"""用户 / 角色 / 用户组应用服务与 AccessContext 构建。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    ClearanceLevel,
    LibraryScope,
    Role,
    RolePermission,
    User,
    UserGroup,
    UserGroupMember,
    UserRole,
)
from calliodesmo.auth.security import hash_password, verify_password


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    clearance: ClearanceLevel = ClearanceLevel.INTERNAL,
    email: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        clearance=clearance,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate(session: AsyncSession, *, username: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def seed_default_roles(session: AsyncSession) -> list[Role]:
    """幂等写入 analyst / reviewer / admin 内置角色及细粒度权限。"""
    existing = set((await session.execute(select(Role.name))).scalars())
    created: list[Role] = []
    for name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        if name in existing:
            continue
        role = Role(name=name, description=f"内置角色：{name}")
        role.permissions = [
            RolePermission(permission=p) for p in sorted(permissions, key=lambda p: p.value)
        ]
        session.add(role)
        created.append(role)
    await session.flush()
    return created


async def assign_role(
    session: AsyncSession, *, user: User, role_name: str, scope: LibraryScope
) -> UserRole:
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    link = UserRole(user_id=user.id, role_id=role.id, scope=scope)
    session.add(link)
    await session.flush()
    return link


async def create_group(
    session: AsyncSession,
    *,
    name: str,
    description: str = "",
    scope: LibraryScope = LibraryScope.ORG,
) -> UserGroup:
    group = UserGroup(name=name, description=description, scope=scope)
    session.add(group)
    await session.flush()
    return group


async def add_group_member(
    session: AsyncSession, *, user: User, group: UserGroup, role_in_group: str = "member"
) -> UserGroupMember:
    member = UserGroupMember(user_id=user.id, group_id=group.id, role_in_group=role_in_group)
    session.add(member)
    await session.flush()
    return member


async def get_access_context(session: AsyncSession, user_id: uuid.UUID) -> AccessContext | None:
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(UserRole.role).selectinload(Role.permissions),
            selectinload(User.group_memberships),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    permissions = {rp.permission for ur in user.roles for rp in ur.role.permissions}
    scopes = {ur.scope for ur in user.roles}
    group_ids = {m.group_id for m in user.group_memberships}
    return AccessContext(
        user_id=user.id,
        username=user.username,
        clearance=user.clearance,
        permissions=frozenset(permissions),
        library_scopes=frozenset(scopes),
        group_ids=frozenset(group_ids),
    )
