import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.auth.service import (
    add_project_member,
    add_team_member,
    assign_role,
    authenticate,
    create_project,
    create_team,
    create_user,
    get_access_context,
    seed_default_roles,
)


def test_clearance_ordering():
    assert ClearanceLevel.SECRET > ClearanceLevel.CONFIDENTIAL
    assert ClearanceLevel.CONFIDENTIAL > ClearanceLevel.INTERNAL
    assert ClearanceLevel.INTERNAL > ClearanceLevel.PUBLIC


def test_can_access():
    ctx = AccessContext(user_id=uuid.uuid4(), username="a", clearance=ClearanceLevel.CONFIDENTIAL)
    assert ctx.can_access(ClearanceLevel.PUBLIC)
    assert ctx.can_access(ClearanceLevel.CONFIDENTIAL)
    assert not ctx.can_access(ClearanceLevel.SECRET)


async def test_seed_default_roles_idempotent(session):
    first = await seed_default_roles(session)
    second = await seed_default_roles(session)
    assert len(first) == 3
    assert second == []


async def test_authenticate(session):
    await create_user(session, username="carol", password="right")
    await session.commit()
    user = await authenticate(session, username="carol", password="right")
    assert user is not None and user.username == "carol"
    assert await authenticate(session, username="carol", password="wrong") is None
    assert await authenticate(session, username="ghost", password="x") is None


async def test_get_access_context_aggregates(session):
    await seed_default_roles(session)
    user = await create_user(
        session, username="bob", password="pw", clearance=ClearanceLevel.CONFIDENTIAL
    )
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.PERSONAL)
    await assign_role(session, user=user, role_name="reviewer", scope=LibraryScope.TEAM)
    team = await create_team(session, name="X调查团队")
    project = await create_project(session, name="项目Alpha", team=team)
    await add_team_member(session, user=user, team=team, role_in_team="reviewer")
    await add_project_member(
        session, user=user, project=project, role_name="reviewer", role_in_project="maintainer"
    )
    await session.commit()

    ctx = await get_access_context(session, user.id)
    assert ctx is not None
    assert ctx.clearance == ClearanceLevel.CONFIDENTIAL
    assert ctx.has_permission(Permission.PUSH)
    assert ctx.has_permission(Permission.APPROVE)  # analyst ∪ reviewer
    assert not ctx.has_permission(Permission.MANAGE_USERS)
    assert ctx.library_scopes == frozenset({LibraryScope.PERSONAL, LibraryScope.TEAM})
    assert team.id in ctx.team_ids
    assert project.id in ctx.project_ids


async def test_get_access_context_unknown_user(session):
    assert await get_access_context(session, uuid.uuid4()) is None
