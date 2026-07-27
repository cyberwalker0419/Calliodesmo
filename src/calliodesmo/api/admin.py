"""/admin 管理端点：用户/团队/项目 CRUD + 成员管理（manage_users 守卫，全程审计）。

后端为权限唯一真相：每个端点经 require_permission 守卫，前端隐藏仅 UX。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import (
    get_community_store,
    get_current_context,
    require_permission,
)
from calliodesmo.api.schemas import (
    CommunityOut,
    CommunityPatchRequest,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectOut,
    RoleAssign,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberOut,
    TeamOut,
    UserCreate,
    UserOut,
    UserRoleOut,
    UserUpdate,
)
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, User
from calliodesmo.auth.service import (
    add_project_member,
    add_team_member,
    assign_role,
    create_project,
    create_team,
    create_user,
    deactivate_user,
    get_user_by_username,
    list_projects,
    list_teams,
    list_users,
    remove_project_member,
    remove_team_member,
    update_user,
)
from calliodesmo.db.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"])

_GUARD = Permission.MANAGE_USERS


def _parse_clearance(raw: str) -> ClearanceLevel:
    try:
        return ClearanceLevel[raw.upper()]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"未知 clearance：{raw}（可选 {[c.name for c in ClearanceLevel]}）",
        ) from None


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        clearance=user.clearance.name,
        is_active=user.is_active,
        roles=[UserRoleOut(role=ur.role.name, scope=ur.scope.value) for ur in user.roles],
        team_ids=[m.team_id for m in user.team_memberships],
        project_ids=[m.project_id for m in user.project_memberships],
    )


@router.get("/users", response_model=list[UserOut])
async def list_users_endpoint(
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[UserOut]:
    require_permission(ctx, _GUARD)
    return [_user_out(u) for u in await list_users(session)]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user_endpoint(
    req: UserCreate,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    require_permission(ctx, _GUARD)
    if await get_user_by_username(session, req.username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    user = await create_user(
        session,
        username=req.username,
        password=req.password,
        clearance=_parse_clearance(req.clearance),
        email=req.email,
    )
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "create", "target": req.username},
        source="api",
    )
    await session.commit()
    refreshed = next(u for u in await list_users(session) if u.id == user.id)
    return _user_out(refreshed)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user_endpoint(
    user_id: uuid.UUID,
    req: UserUpdate,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    require_permission(ctx, _GUARD)
    user = await update_user(
        session,
        user_id=user_id,
        clearance=_parse_clearance(req.clearance) if req.clearance else None,
        is_active=req.is_active,
        email=req.email,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={
            "op": "update",
            "target": str(user_id),
            "fields": req.model_dump(exclude_none=True),
        },
        source="api",
    )
    await session.commit()
    # 重新取带关系的用户（roles/team/project 序列化需要）
    refreshed = next(u for u in await list_users(session) if u.id == user.id)
    return _user_out(refreshed)


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user_endpoint(
    user_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    require_permission(ctx, _GUARD)
    user = await deactivate_user(session, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "deactivate", "target": str(user_id)},
        source="api",
    )
    await session.commit()


@router.post("/users/{user_id}/roles", response_model=UserOut, status_code=201)
async def assign_role_endpoint(
    user_id: uuid.UUID,
    req: RoleAssign,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    require_permission(ctx, _GUARD)
    from sqlalchemy import select

    from calliodesmo.auth.models import Role

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    role_exists = await session.execute(select(Role).where(Role.name == req.role))
    if role_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"角色不存在：{req.role}")
    try:
        scope = LibraryScope(req.scope)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"未知 scope：{req.scope}"
        ) from None
    await assign_role(session, user=user, role_name=req.role, scope=scope)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "assign_role", "target": str(user_id), "role": req.role, "scope": req.scope},
        source="api",
    )
    await session.commit()
    refreshed = next(u for u in await list_users(session) if u.id == user.id)
    return _user_out(refreshed)


# ---- 团队 ----


def _team_out(team) -> TeamOut:
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        members=[
            TeamMemberOut(user_id=m.user_id, username=m.user.username, role_in_team=m.role_in_team)
            for m in team.members
        ],
    )


@router.get("/teams", response_model=list[TeamOut])
async def list_teams_endpoint(
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[TeamOut]:
    require_permission(ctx, _GUARD)
    return [_team_out(t) for t in await list_teams(session)]


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team_endpoint(
    req: TeamCreate,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    require_permission(ctx, _GUARD)
    team = await create_team(session, name=req.name, description=req.description)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "create_team", "target": req.name},
        source="api",
    )
    await session.commit()
    refreshed = next(t for t in await list_teams(session) if t.id == team.id)
    return _team_out(refreshed)


@router.post("/teams/{team_id}/members", response_model=TeamOut, status_code=201)
async def add_team_member_endpoint(
    team_id: uuid.UUID,
    req: TeamMemberAdd,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    require_permission(ctx, _GUARD)
    from calliodesmo.auth.models import Team

    team = await session.get(Team, team_id)
    user = await session.get(User, req.user_id)
    if team is None or user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="团队或用户不存在")
    await add_team_member(session, user=user, team=team, role_in_team=req.role_in_team)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "add_team_member", "target": str(team_id), "member": str(req.user_id)},
        source="api",
    )
    await session.commit()
    refreshed = next(t for t in await list_teams(session) if t.id == team.id)
    return _team_out(refreshed)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member_endpoint(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    require_permission(ctx, _GUARD)
    if not await remove_team_member(session, team_id=team_id, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成员关系不存在")
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "remove_team_member", "target": str(team_id), "member": str(user_id)},
        source="api",
    )
    await session.commit()


# ---- 项目 ----


def _project_out(project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        team_id=project.team_id,
        members=[
            ProjectMemberOut(
                user_id=m.user_id,
                role=m.role.name if m.role else None,
                role_in_project=m.role_in_project,
            )
            for m in project.members
        ],
    )


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects_endpoint(
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectOut]:
    require_permission(ctx, _GUARD)
    return [_project_out(p) for p in await list_projects(session)]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project_endpoint(
    req: ProjectCreate,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    require_permission(ctx, _GUARD)
    from calliodesmo.auth.models import Team

    team = await session.get(Team, req.team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="团队不存在")
    project = await create_project(session, name=req.name, team=team, description=req.description)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "create_project", "target": req.name},
        source="api",
    )
    await session.commit()
    refreshed = next(p for p in await list_projects(session) if p.id == project.id)
    return _project_out(refreshed)


@router.post("/projects/{project_id}/members", response_model=ProjectOut, status_code=201)
async def add_project_member_endpoint(
    project_id: uuid.UUID,
    req: ProjectMemberAdd,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    require_permission(ctx, _GUARD)
    from calliodesmo.auth.models import Project

    project = await session.get(Project, project_id)
    user = await session.get(User, req.user_id)
    if project is None or user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目或用户不存在")
    await add_project_member(
        session, user=user, project=project, role_name=req.role, role_in_project=req.role_in_project
    )
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "add_project_member", "target": str(project_id), "member": str(req.user_id)},
        source="api",
    )
    await session.commit()
    refreshed = next(p for p in await list_projects(session) if p.id == project.id)
    return _project_out(refreshed)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member_endpoint(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    require_permission(ctx, _GUARD)
    if not await remove_project_member(session, project_id=project_id, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成员关系不存在")
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_user",
        detail={"op": "remove_project_member", "target": str(project_id), "member": str(user_id)},
        source="api",
    )
    await session.commit()


# ---- 文档社区手动管理（Task 7）----

_COMMUNITY_GUARD = Permission.MANAGE_COMMUNITY


@router.get("/document-communities", response_model=list[CommunityOut])
async def list_document_communities(
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_community_store),
) -> list[CommunityOut]:
    """列出 level=1 文档社区（manage_community 守卫）。"""
    require_permission(ctx, _COMMUNITY_GUARD)
    records = [r for r in await store.list_communities(access=ctx) if r.level == 1]
    return [_community_out(r) for r in records]


@router.patch("/document-communities/{community_id}", response_model=CommunityOut)
async def patch_document_community(
    community_id: str,
    req: CommunityPatchRequest,
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_community_store),
    session: AsyncSession = Depends(get_session),
) -> CommunityOut:
    """手动管理：rename / retag / set_access_level（manage_community 守卫，记审计）。

    merge/split 随 P4 版本能力交付，本端点只做可安全重做的操作。
    """
    require_permission(ctx, _COMMUNITY_GUARD)

    records = {r.community_id: r for r in await store.list_communities(access=ctx)}
    rec = records.get(community_id)
    if rec is None or rec.level != 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档社区不存在或不可见")
    op: str | None = None
    if req.title is not None and req.title != rec.title:
        ok = await store.rename(community_id, req.title, access=ctx)
        if ok:
            op = "rename"
    if req.access_level is not None:
        try:
            level = ClearanceLevel[req.access_level.upper()]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知 access_level"
            ) from None
        ok = await store.set_access_level(community_id, level, access=ctx)
        if ok:
            op = op or "set_access"
    if op is None:
        op = "noop"
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="manage_community",
        detail={"op": op, "target": community_id},
        source="api",
    )
    await session.commit()
    all_comms = await store.list_communities(access=ctx)
    refreshed = next((r for r in all_comms if r.community_id == community_id), None)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档社区重查失败")
    return _community_out(refreshed)


def _community_out(c) -> CommunityOut:
    return CommunityOut(
        community_id=c.community_id,
        level=c.level,
        title=c.title,
        summary=c.summary,
        member_entity_names=list(c.member_entity_names),
        metadata=dict(c.metadata),
        access_level=c.access_level.name,
        library_scope=c.library_scope.value,
    )
