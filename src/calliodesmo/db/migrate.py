"""幂等补列与列型回填工具（P6 Task 11）。

SQLAlchemy ``create_all`` 不给既有表加列 / 改列型：既有库（dev / 生产）升级到
P6 结构靠 ``ensure_missing_columns(engine)`` —— ``inspect`` 探测 ``jobs`` /
``contributions`` 表，缺列则 ``ALTER TABLE ADD COLUMN``；旧型时间列回填
``TIMESTAMPTZ``（承接 P6 Task 1 留痕：``contributions`` 四个时间列统一
``DateTime(timezone=True)`` 后，既有库仍为 TIMESTAMP WITHOUT TZ，写 aware
datetime 即报错）。挂进 ``cli db init``（``create_all`` 之后）；全新库由
``create_all`` 直出完整结构，本路径纯 no-op。

幂等纪律：全部语句可重复执行（已补列跳过 / 已回填列型跳过 / 索引 ``IF NOT EXISTS``）。

未竟：复杂迁移场景（列改名 / 降级回滚 / 数据回填脚本）需引入 Alembic，
锚点 2026-W49（P9，与持久队列同批评估；cli db init docstring 早已注明去向）。
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

#: contributions 需回填列型的时间列（P6 Task 1 统一为 DateTime(timezone=True)）。
_TSTZ_COLUMNS: tuple[str, ...] = ("reviewed_at", "merged_at", "created_at", "updated_at")


async def ensure_missing_columns(engine: AsyncEngine) -> None:
    """幂等补齐既有库结构：jobs 补列 + contributions 时间列型回填。

    全新库经 ``create_all`` 直出完整结构，本函数为纯 no-op；既有库升级 P6 结构后
    重跑 ``calliodesmo db init`` 即触发。全部操作幂等，重复执行安全。
    """
    async with engine.begin() as conn:
        await conn.run_sync(_backfill_jobs_columns)
        await conn.run_sync(_backfill_contribution_timestamptz)


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
