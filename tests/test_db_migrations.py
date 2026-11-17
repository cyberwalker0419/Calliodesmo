"""P9 Task 6：版本化迁移台账（schema_migrations）与 `db migrate`。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from calliodesmo.db.migrate import ensure_missing_columns
from calliodesmo.db.migrations import (
    LEDGER_TABLE,
    MIGRATION_STEPS,
    MigrationStep,
    applied_versions,
    apply_pending,
    migrate_report,
)

_ALL_VERSIONS = {step.version for step in MIGRATION_STEPS}

_LEGACY_AUDIT_DDL = """
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    user_id UUID,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(128),
    detail JSON DEFAULT '{}'::json,
    source VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT now()
)
"""


async def test_apply_pending_records_all_versions_and_is_idempotent(_pg_engine):
    """全新结构：首次补齐全部步骤并记账；再跑为纯 no-op。"""
    await ensure_missing_columns(_pg_engine)  # 既有入口（db init 用），行为不变
    first = await apply_pending(_pg_engine)
    assert _ALL_VERSIONS <= await applied_versions(_pg_engine)
    assert set(first) <= _ALL_VERSIONS
    assert await apply_pending(_pg_engine) == []
    assert await apply_pending(_pg_engine) == []


async def test_migrate_report_shape(_pg_engine):
    await apply_pending(_pg_engine)
    report = await migrate_report(_pg_engine)
    assert [item["version"] for item in report] == [step.version for step in MIGRATION_STEPS]
    assert all(item["applied"] for item in report)
    assert all(item["description"] for item in report)


async def test_failed_step_not_recorded_and_resumable(_pg_engine):
    """步骤抛错：不记账（事务回滚），修好后续跑只补失败步及其之后。"""

    def _boom(conn) -> None:
        raise RuntimeError("炸在步骤里")

    boom = MigrationStep("9001_boom", "故意失败", _boom)
    ok = MigrationStep("9002_ok", "正常步骤（幂等 no-op）", lambda conn: None)
    with pytest.raises(RuntimeError):
        await apply_pending(_pg_engine, steps=(boom, ok))
    done = await applied_versions(_pg_engine)
    assert "9001_boom" not in done
    assert "9002_ok" not in done

    fixed = (
        MigrationStep("9001_boom", "修好的步骤", lambda conn: None),
        ok,
    )
    applied = await apply_pending(_pg_engine, steps=fixed)
    assert applied == ["9001_boom", "9002_ok"]
    # 清理测试用版本，避免污染其它用例的报告断言
    async with _pg_engine.begin() as conn:
        await conn.execute(text(f"DELETE FROM {LEDGER_TABLE} WHERE version LIKE '90%'"))


@pytest.fixture
async def legacy_audit_engine():
    """唯一 schema 内的旧结构 audit_logs（TIMESTAMP WITHOUT TZ），用完 DROP。"""
    from calliodesmo.config import get_settings

    settings = get_settings()
    schema = f"mig_ledger_{uuid.uuid4().hex[:10]}"
    setup = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with setup.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.execute(text(_LEGACY_AUDIT_DDL))
    await setup.dispose()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        yield engine, schema
    finally:
        await engine.dispose()
        cleanup = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            async with cleanup.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await cleanup.dispose()


@pytest.mark.db  # 自建 engine 夹具不在 conftest 名单内，须显式标记（CI 无 PG）
async def test_legacy_audit_table_migrated_and_recorded(legacy_audit_engine):
    """旧结构库：只跑审计步骤即可升级，且版本进台账（下次跳过）。"""
    engine, schema = legacy_audit_engine
    step = next(s for s in MIGRATION_STEPS if s.version == "0005_audit_timestamptz")

    applied = await apply_pending(engine, steps=(step,))
    assert applied == ["0005_audit_timestamptz"]
    async with engine.connect() as conn:
        data_type = (
            await conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = 'audit_logs' "
                    "AND column_name = 'created_at'"
                ),
                {"s": schema},
            )
        ).scalar_one()
    assert data_type == "timestamp with time zone"
    assert await apply_pending(engine, steps=(step,)) == []


def test_db_migrate_cli_after_db_init(cli_db):
    """CLI：`db init` 建表并记账，`db migrate` 随后为纯 no-op（可重复执行）。"""
    from typer.testing import CliRunner

    from calliodesmo.cli import app

    runner = CliRunner()
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    first = runner.invoke(app, ["db", "migrate"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["db", "migrate"])
    assert second.exit_code == 0
    assert "无待应用" in second.output or "no-op" in second.output.lower()
