"""Task 5：CLI contributions 子命令。

P4.5 Task 1：走真实 PG（``cli_db`` 唯一 schema 隔离），不再用 sqlite 文件。
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

import calliodesmo.models  # noqa: F401
from calliodesmo.auth.models import LibraryScope, Project, Team, User
from calliodesmo.cli import app
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.config import get_settings

runner = CliRunner()


def _init_db() -> None:
    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        # db seed 内建 SYSTEM_USER_ID 账户（contributions submit 等 audit 的 actor FK）
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
    finally:
        get_settings.cache_clear()


def _seed_user_and_contribution(schema: str):
    """在 cli schema 建真实 user/team/project + contribution（满足 PG FK）。返回 (cid, uid)。"""

    async def _go() -> tuple:
        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={"server_settings": {"search_path": schema}},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            u = User(username="u", hashed_password="x")
            s.add(u)
            await s.flush()
            team = Team(name=f"t-{uuid.uuid4().hex[:6]}")
            s.add(team)
            await s.flush()
            project = Project(name=f"p-{uuid.uuid4().hex[:6]}", team_id=team.id)
            s.add(project)
            await s.flush()
            c = Contribution(
                source_user_id=u.id,
                source_scope=LibraryScope.PERSONAL,
                target_scope=LibraryScope.PROJECT,
                target_project_id=project.id,
                title="CLI 测试",
                doc_ids=["d#0"],
                status=ContributionStatus.DRAFT,
            )
            s.add(c)
            await s.flush()
            cid, uid = c.id, u.id
            await s.commit()
        await engine.dispose()
        return cid, uid

    return asyncio.run(_go())


def test_contributions_list_and_show(cli_db):
    _init_db()
    cid, _ = _seed_user_and_contribution(cli_db)
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "list"])
    assert result.exit_code == 0, result.output
    assert "CLI 测试" in result.output
    result = runner.invoke(app, ["contributions", "show", str(cid)])
    assert result.exit_code == 0, result.output
    assert "draft" in result.output


def test_contributions_submit(cli_db):
    _init_db()
    cid, _ = _seed_user_and_contribution(cli_db)
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "submit", str(cid)])
    assert result.exit_code == 0, result.output
    assert "已提交" in result.output
    result = runner.invoke(app, ["contributions", "show", str(cid)])
    assert "submitted" in result.output


def test_contributions_show_nonexistent(cli_db):
    _init_db()
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "show", str(uuid.uuid4())])
    assert result.exit_code == 1
