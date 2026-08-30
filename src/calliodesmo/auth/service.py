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


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def authenticate(session: AsyncSession, *, username: str, password: str) -> User | None:
    user = await get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def change_password(
    session: AsyncSession, *, user_id: uuid.UUID, old_password: str, new_password: str
) -> bool:
    """自助改密：旧密码校验通过才重哈希（Argon2）。用户不存在/已停用/旧密码错 -> False。"""
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return False
    if not verify_password(old_password, user.hashed_password):
        return False
    user.hashed_password = hash_password(new_password)
    await session.flush()
    return True


async def list_users(session: AsyncSession) -> list[User]:
    """全量用户（含角色/团队/项目成员关系，供管理端序列化）。"""
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.roles).selectinload(UserRole.role),
            selectinload(User.team_memberships),
            selectinload(User.project_memberships).selectinload(ProjectMember.role),
        )
        .order_by(User.username)
    )
    return list(result.scalars())


async def update_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    clearance: ClearanceLevel | None = None,
    is_active: bool | None = None,
    email: str | None = None,
) -> User | None:
    """更新 clearance / is_active / email（None 字段不动）。"""
    user = await session.get(User, user_id)
    if user is None:
        return None
    if clearance is not None:
        user.clearance = clearance
    if is_active is not None:
        user.is_active = is_active
    if email is not None:
        user.email = email
    await session.flush()
    return user


async def deactivate_user(session: AsyncSession, *, user_id: uuid.UUID) -> User | None:
    """软删除：is_active=False，保留审计可追溯（不物理删除）。"""
    return await update_user(session, user_id=user_id, is_active=False)


async def list_teams(session: AsyncSession) -> list[Team]:
    result = await session.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .order_by(Team.name)
    )
    return list(result.scalars())


async def list_projects(session: AsyncSession) -> list[Project]:
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.members).selectinload(ProjectMember.role))
        .order_by(Project.name)
    )
    return list(result.scalars())


async def remove_team_member(
    session: AsyncSession, *, team_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    member = await session.get(TeamMember, (user_id, team_id))
    if member is None:
        return False
    await session.delete(member)
    await session.flush()
    return True


async def remove_project_member(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    member = await session.get(ProjectMember, (user_id, project_id))
    if member is None:
        return False
    await session.delete(member)
    await session.flush()
    return True


async def seed_default_roles(session: AsyncSession) -> list[Role]:
    """幂等写入 analyst / reviewer / admin 内置角色及细粒度权限。

    已存在角色走**差集回填**：比对 ``DEFAULT_ROLE_PERMISSIONS`` 补缺失的
    ``RolePermission`` 行（P6 Task 2 修复——原实现对已存在角色直接 ``continue``，
    新增权限后既有部署重跑 ``db seed`` 不回填、全员 403）。只增不删：
    撤销既有权限会把既有部署锁死，回滚只撤代码不撤已写权限数据。
    重复执行不产生重复行（``(role_id, permission)`` 复合主键兜底）。

    返回本次**新建**的角色列表（仅新建；回填不改变返回语义）。
    """
    result = await session.execute(select(Role).options(selectinload(Role.permissions)))
    existing = {role.name: role for role in result.scalars()}
    created: list[Role] = []
    for name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        role = existing.get(name)
        if role is None:
            role = Role(name=name, description=f"内置角色：{name}")
            role.permissions = [
                RolePermission(permission=p) for p in sorted(permissions, key=lambda p: p.value)
            ]
            session.add(role)
            created.append(role)
            continue
        # 差集回填：补缺失权限行，不删既有权限行（幂等，重跑安全）
        have = {rp.permission for rp in role.permissions}
        for p in sorted(permissions - have, key=lambda p: p.value):
            role.permissions.append(RolePermission(permission=p))
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
