import sqlite3

from typer.testing import CliRunner

from calliodesmo import __version__
from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_db_init_and_seed(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("CALLIODESMO_ADMIN_PASSWORD", "admin-pw")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["db", "init"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["db", "seed"])
        assert result.exit_code == 0, result.output
    finally:
        get_settings.cache_clear()

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "users",
        "roles",
        "role_permissions",
        "user_roles",
        "user_groups",
        "user_group_members",
        "audit_logs",
    } <= tables
    roles = {r[0] for r in conn.execute("SELECT name FROM roles")}
    assert {"analyst", "reviewer", "admin"} <= roles
    admins = list(conn.execute("SELECT username, clearance FROM users WHERE username='admin'"))
    assert admins == [("admin", "SECRET")]
    conn.close()
