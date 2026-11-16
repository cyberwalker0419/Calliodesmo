"""幂等补列与列型回填工具（P6 Task 11）。

SQLAlchemy ``create_all`` 不给既有表加列 / 改列型：既有库（dev / 生产）升级到
P6 结构靠 ``ensure_missing_columns(engine)`` —— ``inspect`` 探测 ``jobs`` /
``contributions`` 表，缺列则 ``ALTER TABLE ADD COLUMN``；旧型时间列回填
``TIMESTAMPTZ``（承接 P6 Task 1 留痕：``contributions`` 四个时间列统一
``DateTime(timezone=True)`` 后，既有库仍为 TIMESTAMP WITHOUT TZ，写 aware
datetime 即报错）。挂进 ``cli db init``（``create_all`` 之后）；全新库由
``create_all`` 直出完整结构，本路径纯 no-op。

幂等纪律：全部语句可重复执行（已补列跳过 / 已回填列型跳过 / 索引 ``IF NOT EXISTS``）。

P9 Task 6：本模块的补齐函数被 ``db/migrations.MIGRATION_STEPS`` 引用为有序步骤 +
``schema_migrations`` 台账（``calliodesmo db migrate`` 据此判断哪台库升到哪个版本）；
本模块函数保持可直接调用，旧调用点（``ensure_missing_columns``）行为不变。
**新增结构变更只在 ``migrations.MIGRATION_STEPS`` 末尾追加一步**，不要在
``ensure_missing_columns`` 里再加 run_sync。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

#: jobs 表补列规格：列名 -> ADD COLUMN 子句（P6 Task 11 泛化扩列）。
#: task_type NOT NULL DEFAULT 'ingest'：存量行经 server_default 回填，与 ORM 定义一致。
_JOBS_COLUMN_SPECS: tuple[tuple[str, str], ...] = (
    ("task_type", "VARCHAR(16) NOT NULL DEFAULT 'ingest'"),
    ("task_payload", "JSON"),
)

#: P8 列规格：表名 -> 补列规格（侧车 JSON 可空 + 报告生命周期列带 server_default）
_SIDECAR_COLUMN_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "analysis_reports": (
        ("verification", "JSON"),
        ("current_version", "INTEGER NOT NULL DEFAULT 1"),
        ("lock_version", "INTEGER NOT NULL DEFAULT 0"),
        ("deleted_at", "TIMESTAMPTZ"),
        ("review_status", "VARCHAR(16) NOT NULL DEFAULT 'draft'"),
        ("reviewed_by", "UUID"),
        ("reviewed_at", "TIMESTAMPTZ"),
        ("review_note", "TEXT"),
    ),
    "agent_runs": (("verification", "JSON"),),
    # P9 Task 10：会话软删除列（带 server_default NULL）+ 列表过滤索引
    "agent_sessions": (("deleted_at", "TIMESTAMPTZ"),),
}

#: contributions 需回填列型的时间列（P6 Task 1 统一为 DateTime(timezone=True)）。
_TSTZ_COLUMNS: tuple[str, ...] = ("reviewed_at", "merged_at", "created_at", "updated_at")

#: audit_logs 需回填列型的时间列（P9 Task 4：留存 / 时间窗按 UTC 语义）。
#: 存量值来自 ``now()::timestamp``（会话时区的墙上时间），故按
#: ``current_setting('TimeZone')`` 解释——与 contributions 的「按 UTC 解释」不同，
#: 因为那批值由应用侧写入（aware UTC），这批值由数据库默认值写入（本地时区）。
_AUDIT_TSTZ_COLUMNS: tuple[str, ...] = ("created_at",)


async def ensure_missing_columns(engine: AsyncEngine) -> None:
    """幂等补齐既有库结构（不记账的复跑路径）。

    全新库经 ``create_all`` 直出完整结构，本函数为纯 no-op。步骤清单与台账版迁移
    同源（``db/migrations.MIGRATION_STEPS``）：**新增结构变更只改那一处**，
    避免两套清单漂移。需要「哪台库升到哪个版本」的答案时用
    ``migrations.apply_pending``（``calliodesmo db migrate``）。
    """
    from calliodesmo.db.migrations import structural_steps

    async with engine.begin() as conn:
        for step in structural_steps():
            await conn.run_sync(step.apply)


def _backfill_jobs_columns(conn: Connection) -> None:
    """jobs 表缺 ``task_type`` / ``task_payload`` 则补列，并幂等建 ``task_type`` 索引。"""
    insp = inspect(conn)
    if not insp.has_table("jobs"):
        return  # 防御：表尚不存在（create_all 未跑）则跳过，不做无依据建表
    existing = {c["name"] for c in insp.get_columns("jobs")}
    for name, clause in _JOBS_COLUMN_SPECS:
        if name not in existing:
            conn.execute(text(f'ALTER TABLE jobs ADD COLUMN "{name}" {clause}'))
            logger.info("db/migrate：jobs 补列 %s", name)
    # 与 create_all 的 index=True 同名（ix_<table>_<column>），IF NOT EXISTS 幂等
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_task_type ON jobs (task_type)"))


def _backfill_sidecar_columns(conn: Connection) -> None:
    """P8 侧车列幂等补齐（analysis_reports / agent_runs 的 verification JSON 列）。"""
    insp = inspect(conn)
    for table, specs in _SIDECAR_COLUMN_SPECS.items():
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, clause in specs:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {clause}'))
                logger.info("db/migrate：%s 补列 %s", table, name)
    if insp.has_table("analysis_reports"):
        # 软删除 / 复核列表过滤索引（幂等）
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_analysis_reports_deleted_at "
                "ON analysis_reports (deleted_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_analysis_reports_review_status "
                "ON analysis_reports (review_status)"
            )
        )


def _backfill_contribution_timestamptz(conn: Connection) -> None:
    """contributions 旧型时间列（TIMESTAMP WITHOUT TZ）回填 TIMESTAMPTZ。

    ``USING <col> AT TIME ZONE 'UTC'``：存量 naive 时刻按 UTC 解释，回填后时刻不漂移
    （P6 Task 1 服务层已改写 aware UTC，此处闭环既有库迁移缺口）。已是
    timestamptz 的列跳过（幂等）。
    """
    insp = inspect(conn)
    if not insp.has_table("contributions"):
        return
    # 列名为模块内常量，拼接安全（非外部输入）
    names = ", ".join(f"'{c}'" for c in _TSTZ_COLUMNS)
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'contributions' "
            f"AND column_name IN ({names}) AND data_type = 'timestamp without time zone'"
        )
    ).fetchall()
    for (column_name,) in rows:
        conn.execute(
            text(
                f'ALTER TABLE contributions ALTER COLUMN "{column_name}" '
                f"TYPE TIMESTAMPTZ USING \"{column_name}\" AT TIME ZONE 'UTC'"
            )
        )
        logger.info("db/migrate：contributions.%s 回填 TIMESTAMPTZ", column_name)


def _backfill_audit_timestamptz(conn: Connection) -> None:
    """audit_logs.created_at 回填 TIMESTAMPTZ + 补齐查询索引（P9 Task 4，幂等）。"""
    insp = inspect(conn)
    if not insp.has_table("audit_logs"):
        return
    names = ", ".join(f"'{c}'" for c in _AUDIT_TSTZ_COLUMNS)
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'audit_logs' "
            f"AND column_name IN ({names}) AND data_type = 'timestamp without time zone'"
        )
    ).fetchall()
    for (column_name,) in rows:
        # 存量值为会话时区墙上时间：按 current_setting('TimeZone') 解释，时刻不漂移
        conn.execute(
            text(
                f'ALTER TABLE audit_logs ALTER COLUMN "{column_name}" TYPE TIMESTAMPTZ '
                f"USING \"{column_name}\" AT TIME ZONE current_setting('TimeZone')"
            )
        )
        logger.info("db/migrate：audit_logs.%s 回填 TIMESTAMPTZ", column_name)
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_created_at "
            "ON audit_logs (action, created_at)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_user_created_at "
            "ON audit_logs (user_id, created_at)"
        )
    )
