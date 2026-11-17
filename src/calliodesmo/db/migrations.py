"""版本化迁移台账（P9 Task 6）：既有库升级可重复、可审计、可续跑。

现状与取舍：``create_all`` 只建缺失表，不给既有表加列 / 改列型；P6 起的
``db/migrate.py`` 用「幂等补列函数」补齐，但没有记录「哪一步跑过」——每次启动都全量
重探一遍，也无法回答「这台库升到哪个版本了」。本模块加一张 ``schema_migrations``
台账表 + 有序步骤清单，把补齐动作变成**可续跑的迁移**：

- 每个步骤在自己的事务里执行，成功才记版本；失败不记账，重跑即续跑；
- 步骤本身仍要求幂等（沿用 ``db/migrate.py`` 的 IF NOT EXISTS / 缺列才补 纪律），
  台账是「跑没跑过」的凭证，不是「可以不幂等」的免死金牌；
- 全新库由 ``create_all`` 直出完整结构，全部步骤为纯 no-op，但仍记账（版本即结构版本）。

**Alembic 引入结论（P9 决策，锚点见计划关键决策 5）**：不引入。判据是出现列改名 /
降级回滚 / 数据回填类需求 ≥2 次——目前全部需求都是「加可空列 / 补索引 / 列型 widening」，
台账 30 行代码即可覆盖且零新依赖、离线可测；引入 Alembic 需先为 P0–P8 的历史结构写出
完整基线 DDL（易错且不可验证），收益不抵成本。判据触发时再切，届时台账表可直接作为
Alembic ``stamp`` 的输入。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from calliodesmo.db import migrate as legacy_migrate

logger = logging.getLogger(__name__)

#: 台账表名（结构版本 = 已记版本号集合）
LEDGER_TABLE = "schema_migrations"

_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
    version VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class MigrationStep:
    """单个迁移步骤：版本号 + 描述 + 在事务内执行的可重入函数（同步 SQLAlchemy）。"""

    version: str
    description: str
    apply: Callable[[Connection], None]


def _create_all(conn: Connection) -> None:
    """基线步骤：按当前 ORM 元数据建缺失表（既有表不动）。"""
    import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
    from calliodesmo.db.base import Base

    Base.metadata.create_all(conn)


def _agent_session_lifecycle(conn: Connection) -> None:
    """P9 Task 10：既有库补 ``agent_sessions.deleted_at`` 与索引（幂等）。"""
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(conn)
    if not insp.has_table("agent_sessions"):
        return
    existing = {c["name"] for c in insp.get_columns("agent_sessions")}
    if "deleted_at" not in existing:
        conn.execute(text('ALTER TABLE agent_sessions ADD COLUMN "deleted_at" TIMESTAMPTZ'))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_sessions_deleted_at ON agent_sessions (deleted_at)"
        )
    )


#: 有序步骤清单（新增结构变更只在末尾追加，禁止改写历史条目）
MIGRATION_STEPS: tuple[MigrationStep, ...] = (
    MigrationStep("0001_baseline", "按 ORM 元数据建表（create_all 幂等）", _create_all),
    MigrationStep(
        "0002_jobs_task_type",
        "jobs 泛化扩列（task_type / task_payload）",
        legacy_migrate._backfill_jobs_columns,
    ),
    MigrationStep(
        "0003_p8_sidecar_and_lifecycle",
        "P8 侧车列与报告生命周期列 + 索引",
        legacy_migrate._backfill_sidecar_columns,
    ),
    MigrationStep(
        "0004_contributions_timestamptz",
        "contributions 时间列回填 TIMESTAMPTZ",
        legacy_migrate._backfill_contribution_timestamptz,
    ),
    MigrationStep(
        "0005_audit_timestamptz",
        "audit_logs.created_at 回填 TIMESTAMPTZ + 查询索引",
        legacy_migrate._backfill_audit_timestamptz,
    ),
    MigrationStep(
        "0006_agent_session_lifecycle",
        "agent_sessions.deleted_at 软删除列 + 列表过滤索引",
        _agent_session_lifecycle,
    ),
)


def structural_steps() -> tuple[MigrationStep, ...]:
    """除基线建表外的结构步骤（供 ``ensure_missing_columns`` 复跑而不记账）。"""
    return tuple(step for step in MIGRATION_STEPS if not step.version.endswith("baseline"))


async def ensure_ledger(engine: AsyncEngine) -> None:
    """建台账表（幂等）。"""
    async with engine.begin() as conn:
        await conn.execute(text(_LEDGER_DDL))


async def applied_versions(engine: AsyncEngine) -> set[str]:
    """已记账的版本号集合；台账表不存在（首次）返回空集。"""
    async with engine.connect() as conn:
        exists = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(LEDGER_TABLE))
        if not exists:
            return set()
        rows = (await conn.execute(text(f"SELECT version FROM {LEDGER_TABLE}"))).fetchall()
    return {str(row[0]) for row in rows}


async def apply_pending(
    engine: AsyncEngine, *, steps: Sequence[MigrationStep] | None = None
) -> list[str]:
    """应用所有未记账步骤，返回本次实际应用的版本号（按序）。

    每步独立事务：步骤函数 + 记账同生共死——半途失败既不留下「已记账但没改结构」，
    也不会留下「改了结构但没记账」，重跑从失败步续上。
    """
    plan = tuple(steps if steps is not None else MIGRATION_STEPS)
    # 先建台账再读版本：search_path 里若另有他 schema 的旧台账（测试多 schema 场景），
    # 先建自己的表才能让「本库没跑过迁移」不被别人的台账冒充。
    await ensure_ledger(engine)
    done = await applied_versions(engine)
    applied: list[str] = []
    for step in plan:
        if step.version in done:
            continue
        async with engine.begin() as conn:
            await conn.run_sync(step.apply)
            await conn.execute(
                text(
                    f"INSERT INTO {LEDGER_TABLE} (version, description) VALUES (:v, :d) "
                    "ON CONFLICT (version) DO NOTHING"
                ),
                {"v": step.version, "d": step.description},
            )
        logger.info("db/migrations：应用 %s（%s）", step.version, step.description)
        applied.append(step.version)
    return applied


async def migrate_report(engine: AsyncEngine) -> list[dict[str, Any]]:
    """步骤清单 + 是否已记账（``doctor`` / 排障用；不回显数据内容）。"""
    done = await applied_versions(engine)
    return [
        {
            "version": step.version,
            "description": step.description,
            "applied": step.version in done,
        }
        for step in MIGRATION_STEPS
    ]


__all__ = [
    "LEDGER_TABLE",
    "MIGRATION_STEPS",
    "MigrationStep",
    "applied_versions",
    "apply_pending",
    "ensure_ledger",
    "migrate_report",
    "structural_steps",
]
