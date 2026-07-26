"""用户 / 角色 / 团队 / 项目应用服务与 AccessContext 构建。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    ClearanceLevel,
    LibraryScope,
    Project,
    ProjectMember,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
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


async def create_team(session: AsyncSession, *, name: str, description: str = "") -> Team:
    team = Team(name=name, description=description)
    session.add(team)
    await session.flush()
    return team


async def create_project(
    session: AsyncSession, *, name: str, team: Team, description: str = ""
) -> Project:
    project = Project(name=name, description=description, team_id=team.id)
    session.add(project)
    await session.flush()
    return project


async def add_team_member(
    session: AsyncSession, *, user: User, team: Team, role_in_team: str = "member"
) -> TeamMember:
    member = TeamMember(user_id=user.id, team_id=team.id, role_in_team=role_in_team)
    session.add(member)
    await session.flush()
    return member


async def add_project_member(
    session: AsyncSession,
    *,
    user: User,
    project: Project,
    role_name: str,
    role_in_project: str = "member",
) -> ProjectMember:
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    member = ProjectMember(
        user_id=user.id,
        project_id=project.id,
        role_id=role.id,
        role_in_project=role_in_project,
    )
    session.add(member)
    await session.flush()
    return member


async def get_access_context(session: AsyncSession, user_id: uuid.UUID) -> AccessContext | None:
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(UserRole.role).selectinload(Role.permissions),
            selectinload(User.team_memberships),
            selectinload(User.project_memberships)
            .selectinload(ProjectMember.role)
            .selectinload(Role.permissions),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    permissions = {rp.permission for ur in user.roles for rp in ur.role.permissions}
    permissions.update(
        rp.permission for pm in user.project_memberships for rp in pm.role.permissions
    )
    scopes = {ur.scope for ur in user.roles}
    team_ids = {m.team_id for m in user.team_memberships}
    project_ids = {m.project_id for m in user.project_memberships}
    return AccessContext(
        user_id=user.id,
        username=user.username,
        clearance=user.clearance,
        permissions=frozenset(permissions),
        library_scopes=frozenset(scopes),
        team_ids=frozenset(team_ids),
        project_ids=frozenset(project_ids),
    )
