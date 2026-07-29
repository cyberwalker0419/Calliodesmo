"""Task 5：CLI contributions 子命令。"""

import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

import calliodesmo.models  # noqa: F401
from calliodesmo.auth.models import User
from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def _setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    runner.invoke(app, ["db", "init"])
    return db_path


async def _create_contribution(session, source_id, project_id, title="CLI 测试"):
    from calliodesmo.auth.models import LibraryScope
    from calliodesmo.collab.models import Contribution, ContributionStatus

    c = Contribution(
        source_user_id=source_id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project_id,
        title=title,
        doc_ids=["d#0"],
        status=ContributionStatus.DRAFT,
    )
    session.add(c)
    await session.commit()
    return c.id


def _seed_user_and_contribution(db_path):
    import asyncio

    async def _go():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            u = User(username="u", hashed_password="x")
            s.add(u)
            await s.flush()
            cid = await _create_contribution(s, u.id, uuid.uuid4())
            uid = u.id
        await engine.dispose()
        return cid, uid

    return asyncio.run(_go())


def test_contributions_list_and_show(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    cid, _ = _seed_user_and_contribution(db_path)
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "list"])
    assert result.exit_code == 0, result.output
    assert "CLI 测试" in result.output
    result = runner.invoke(app, ["contributions", "show", str(cid)])
    assert result.exit_code == 0, result.output
    assert "draft" in result.output


def test_contributions_submit(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    cid, _ = _seed_user_and_contribution(db_path)
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "submit", str(cid)])
    assert result.exit_code == 0, result.output
    assert "已提交" in result.output
    # show 确认状态
    result = runner.invoke(app, ["contributions", "show", str(cid)])
    assert "submitted" in result.output


def test_contributions_show_nonexistent(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    get_settings.cache_clear()
    result = runner.invoke(app, ["contributions", "show", str(uuid.uuid4())])
    assert result.exit_code == 1
