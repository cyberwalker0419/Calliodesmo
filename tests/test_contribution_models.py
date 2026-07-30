"""Task 1：Contribution ORM 模型与建表。"""

import uuid

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.models import LibraryScope, Project, Team
from calliodesmo.collab.models import Contribution, ContributionStatus


def test_library_scope_rank():
    """A4：LibraryScope.rank 有序，校验推送方向。"""
    assert LibraryScope.PERSONAL.rank == 0
    assert LibraryScope.PROJECT.rank == 1
    assert LibraryScope.TEAM.rank == 2
    assert LibraryScope.TEAM.rank > LibraryScope.PERSONAL.rank


def test_contribution_status_values():
    assert ContributionStatus.DRAFT == "draft"
    assert set(ContributionStatus) == {
        ContributionStatus.DRAFT,
        ContributionStatus.SUBMITTED,
        ContributionStatus.APPROVED,
        ContributionStatus.REJECTED,
        ContributionStatus.MERGED,
        ContributionStatus.CLOSED,
    }


async def test_contribution_table_created(session):
    """建表后可插入并读回，version 乐观锁默认 1。"""
    from calliodesmo.auth.models import User

    user = User(username="u", hashed_password="x")
    session.add(user)
    await session.flush()
    # PG 强制 FK：建真实 Team+Project 供 target_project_id 引用
    team = Team(name=f"team-{uuid.uuid4().hex[:8]}")
    session.add(team)
    await session.flush()
    project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", team_id=team.id)
    session.add(project)
    await session.flush()
    contribution = Contribution(
        source_user_id=user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project.id,
        title="推送1",
        doc_ids=["d#0", "d#1"],
        description="描述",
    )
    session.add(contribution)
    await session.commit()
    assert contribution.id is not None
    assert contribution.status == ContributionStatus.DRAFT
    assert contribution.version == 1
    fetched = await session.get(Contribution, contribution.id)
    assert fetched.title == "推送1"
    assert fetched.doc_ids == ["d#0", "d#1"]
