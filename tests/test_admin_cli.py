"""P3 Task 1 Step 6：CLI 管理命令（users / teams）。

P4.5 Task 1：走真实 PG（``cli_db`` 唯一 schema 隔离），inspect 经 ``cli_inspect``，
不再用 sqlite3 + sqlite 文件。PG boolean 列返回 Python bool（非 sqlite 的 1/0）。
"""

from typer.testing import CliRunner

from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def _init_and_seed() -> None:
    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        assert runner.invoke(app, ["db", "seed"]).exit_code == 0
    finally:
        get_settings.cache_clear()


def test_users_list_create_deactivate(cli_db, cli_inspect):
    _init_and_seed()

    result = runner.invoke(app, ["users", "list"])
    assert result.exit_code == 0, result.output
    assert "admin" in result.output

    result = runner.invoke(
        app,
        ["users", "create", "analyst1", "--password", "pw-123456", "--clearance", "INTERNAL"],
    )
    assert result.exit_code == 0, result.output

    rows = cli_inspect("SELECT username, clearance, is_active FROM users")
    assert ("analyst1", "INTERNAL", True) in rows

    result = runner.invoke(app, ["users", "deactivate", "analyst1"])
    assert result.exit_code == 0, result.output
    rows = cli_inspect("SELECT is_active FROM users WHERE username='analyst1'")
    assert rows == [(False,)]  # 软删除


def test_users_create_duplicate_fails(cli_db):
    _init_and_seed()
    result = runner.invoke(app, ["users", "create", "admin", "--password", "pw-123456"])
    assert result.exit_code == 1
    assert "已存在" in result.output


def test_teams_create_and_add_member(cli_db, cli_inspect):
    _init_and_seed()
    assert (
        runner.invoke(app, ["users", "create", "teammate", "--password", "pw-123456"]).exit_code
        == 0
    )

    result = runner.invoke(app, ["teams", "create", "分析二组"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["teams", "add-member", "分析二组", "teammate"])
    assert result.exit_code == 0, result.output

    rows = cli_inspect(
        "SELECT u.username, t.name FROM team_members tm "
        "JOIN users u ON u.id = tm.user_id JOIN teams t ON t.id = tm.team_id"
    )
    assert ("teammate", "分析二组") in rows


def test_teams_add_member_unknown_user_fails(cli_db):
    _init_and_seed()
    assert runner.invoke(app, ["teams", "create", "空团队"]).exit_code == 0
    result = runner.invoke(app, ["teams", "add-member", "空团队", "nobody"])
    assert result.exit_code == 1
