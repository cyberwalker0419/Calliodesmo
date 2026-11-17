"""CLI 冒烟：version / db init / db seed / serve。

P4.5 Task 1：走真实 PG（``cli_db`` 夹具唯一 schema 隔离），inspect 经 ``cli_inspect``，
不再用 sqlite3 + sqlite 文件。
"""

from typer.testing import CliRunner

from calliodesmo import __version__
from calliodesmo.cli import app
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_db_init_and_seed(cli_db, cli_inspect):
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["db", "init"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["db", "seed"])
        assert result.exit_code == 0, result.output
    finally:
        get_settings.cache_clear()

    schema = cli_db
    tables = {
        r[0]
        for r in cli_inspect(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = :s",
            {"s": schema},
        )
    }
    # P0 元数据表（Base.metadata 注册的全部表都应被 create_all 建出）
    assert set(Base.metadata.tables) <= tables
    roles = {r[0] for r in cli_inspect("SELECT name FROM roles")}
    assert {"analyst", "reviewer", "admin"} <= roles
    admins = list(cli_inspect("SELECT username, clearance FROM users WHERE username='admin'"))
    assert admins == [("admin", "SECRET")]


def test_serve_invokes_uvicorn(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls: dict = {}

    def fake_run(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0, result.output
    assert calls["args"] == ("calliodesmo.api.app:app",)
    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 9000
    assert calls["reload"] is False


def test_serve_defaults(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls: dict = {}
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *a, **kw: calls.update({"args": a, **kw})),
    )

    result = runner.invoke(app, ["serve", "--reload"])

    assert result.exit_code == 0, result.output
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert calls["reload"] is True


def test_db_migrate_show_and_run(cli_db, cli_inspect):
    """P9 Task 9：db init 记账后，db migrate 为 no-op；--show 列清单。"""
    from calliodesmo.config import get_settings

    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
        shown = runner.invoke(app, ["db", "migrate", "--show"])
        assert shown.exit_code == 0, shown.output
        assert "0005_audit_timestamptz" in shown.output
        again = runner.invoke(app, ["db", "migrate"])
        assert again.exit_code == 0, again.output
        assert "无待应用" in again.output
    finally:
        get_settings.cache_clear()
    rows = list(cli_inspect("SELECT version FROM schema_migrations ORDER BY version"))
    assert [r[0] for r in rows][:1] == ["0001_baseline"]


def test_doctor_reports_config_without_db(cli_db, monkeypatch):
    """doctor --no-check-db：只看配置面，error 级问题非零退出（monkeypatch 自动复原）。"""
    from calliodesmo.config import get_settings

    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "ollama/qwen2.5")
    monkeypatch.setenv("CALLIODESMO_JWT_SECRET_KEY", "y" * 40)
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["doctor", "--no-check-db"])
        assert result.exit_code == 0, result.output
        assert "配置校验" in result.output
    finally:
        get_settings.cache_clear()
