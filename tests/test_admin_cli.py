"""P3 Task 1 Step 6：CLI 管理命令（users / teams）。"""

import sqlite3

from typer.testing import CliRunner

from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def _setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "admin-cli.db"
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("CALLIODESMO_ADMIN_PASSWORD", "admin-pw")
    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
    finally:
        get_settings.cache_clear()
    return db_path


def test_users_list_create_deactivate(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)

    result = runner.invoke(app, ["users", "list"])
    assert result.exit_code == 0, result.output
    assert "admin" in result.output

    result = runner.invoke(
        app,
        ["users", "create", "analyst1", "--password", "pw-123456", "--clearance", "INTERNAL"],
    )
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT username, clearance, is_active FROM users"))
    assert ("analyst1", "INTERNAL", 1) in rows
    conn.close()

    result = runner.invoke(app, ["users", "deactivate", "analyst1"])
    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT is_active FROM users WHERE username='analyst1'"))
    assert rows == [(0,)]  # 软删除
    conn.close()


def test_users_create_duplicate_fails(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    result = runner.invoke(app, ["users", "create", "admin", "--password", "pw-123456"])
    assert result.exit_code == 1
    assert "已存在" in result.output


def test_teams_create_and_add_member(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    assert (
        runner.invoke(app, ["users", "create", "teammate", "--password", "pw-123456"]).exit_code
        == 0
    )

    result = runner.invoke(app, ["teams", "create", "分析二组"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["teams", "add-member", "分析二组", "teammate"])
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(db_path)
    rows = list(
        conn.execute(
            "SELECT u.username, t.name FROM team_members tm "
            "JOIN users u ON u.id = tm.user_id JOIN teams t ON t.id = tm.team_id"
        )
    )
    assert ("teammate", "分析二组") in rows
    conn.close()


def test_teams_add_member_unknown_user_fails(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    assert runner.invoke(app, ["teams", "create", "空团队"]).exit_code == 0
    result = runner.invoke(app, ["teams", "add-member", "空团队", "nobody"])
    assert result.exit_code == 1
