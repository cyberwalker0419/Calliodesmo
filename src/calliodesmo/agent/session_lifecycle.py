"""Agent 会话生命周期：软删除 / 恢复 / 可见列表（P9 Task 10）。

P7 把会话做成了「能建、能跑、能读」，P8 的条件任务 T8（会话生命周期）留在 W49 重评。
P9 重评结论是**做最小闭环**：用户删不掉自己的历史会话，是「可直接使用」路径上的真实
缺口（隐私收尾 + 列表噪声），而它复用的正是 P8 报告生命周期的软删除范式，风险低。

范围边界（明确移交，见阶段计划「暂缓与移交记录」）：

- **归档 / 共享范围变更不做**：归档只是列表折叠（收益低于删除），共享会改动三维权限
  语义（会话密级 / scope 快照规则全部要重推），成本与风险都超出本阶段；
- **消息与执行记录不硬删**：与报告生命周期同口径——保留可追溯链，删除只是「看不见」；
- **checkpointer 行不清理**：LangGraph checkpoint 由 ``thread_id`` 索引，物理清理需要
  跨表一致性设计，随 P10「持久队列与数据留存」一并处理（已留 TODO 与锚点）。

权限：owner 本人可删 / 可恢复；``manage_users`` 可对他人会话执行同一动作（运维收尾）。
越权与不存在走同一 ``AgentAccessError`` 文案，不泄漏存在性。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.agent.errors import AgentAccessError
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.db.models_agent import AgentSessionORM
from calliodesmo.stores.visibility import visible_to

#: 审计动作名（前端 / 运维查询用，保持稳定）
ACTION_DELETE = "agent_session_delete"
ACTION_RESTORE = "agent_session_restore"


async def soft_delete_session(
    session: AsyncSession, session_id: uuid.UUID, *, access: AccessContext
) -> AgentSessionORM:
    """软删除会话（幂等：已删除的再删返回同一行、不重复写审计）。"""
    # 已删除的会话再删一次是幂等 no-op（故允许带 deleted_at 进入）
    row = await _load_guarded(session, session_id, access=access, allow_deleted=True)
    if row.deleted_at is not None:
        return row
    row.deleted_at = datetime.now(UTC)
    await record_audit(
        session,
        user_id=access.user_id,
        action=ACTION_DELETE,
        resource_type="agent_session",
        resource_id=str(row.id),
        detail={"owner_id": str(row.owner_id)},
        source="api",
    )
    await session.commit()
    return row


async def restore_session(
    session: AsyncSession, session_id: uuid.UUID, *, access: AccessContext
) -> AgentSessionORM:
    """恢复软删除的会话（未删除时幂等返回）。"""
    row = await _load_guarded(session, session_id, access=access, allow_deleted=True)
    if row.deleted_at is None:
        return row
    row.deleted_at = None
    await record_audit(
        session,
        user_id=access.user_id,
        action=ACTION_RESTORE,
        resource_type="agent_session",
        resource_id=str(row.id),
        detail={"owner_id": str(row.owner_id)},
        source="api",
    )
    await session.commit()
    return row


async def list_sessions_for_access(
    session: AsyncSession,
    *,
    access: AccessContext,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[AgentSessionORM]:
    """列出当前视角可见的会话（谓词下推 + 密级不洗白复检）。

    SQL 侧先按「是否含已删除」和「非管理员只看本人」过滤（不把全库读进内存再筛），
    再用 ``verify_session_access`` 做密级不洗白与 scope 复检——后者是 P7 T12 的红线，
    不能因为下推而省掉。
    """
    conditions = []
    if not include_deleted:
        conditions.append(AgentSessionORM.deleted_at.is_(None))
    if not access.has_permission(Permission.MANAGE_USERS):
        conditions.append(AgentSessionORM.owner_id == access.user_id)

    stmt = select(AgentSessionORM)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AgentSessionORM.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(max(limit, 0)).offset(max(offset, 0))
    rows = (await session.execute(stmt)).scalars().all()
    return [row for row in rows if _readable(row, access=access, include_deleted=include_deleted)]


async def _load_guarded(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    access: AccessContext,
    allow_deleted: bool = False,
) -> AgentSessionORM:
    """取会话并做权限守卫：越权 / 不存在 / 已删除（未允许时）统一抛同一文案。"""
    row = await session.get(AgentSessionORM, session_id)
    if row is None:
        raise AgentAccessError
    if not access.has_permission(Permission.MANAGE_USERS) and row.owner_id != access.user_id:
        raise AgentAccessError
    if access.clearance < row.clearance_at_create:
        raise AgentAccessError
    if row.deleted_at is not None and not allow_deleted:
        raise AgentAccessError
    return row


def _readable(row: AgentSessionORM, *, access: AccessContext, include_deleted: bool) -> bool:
    """列表可见性：与 ``verify_session_access`` 同规则，但「已删除」由入参决定。

    ``verify_session_access`` 把已删除会话判为不可用（不能再跑回合），而恢复入口
    恰恰要把这些列出来，故此处复用其两条实质规则（密级不洗白 + 三维 visible_to），
    删除位由 ``include_deleted`` 单独控制。
    """
    if row.deleted_at is not None and not include_deleted:
        return False
    if access.has_permission(Permission.MANAGE_USERS):
        return True
    if access.clearance < row.clearance_at_create:
        return False
    return visible_to(row, access)


__all__ = [
    "ACTION_DELETE",
    "ACTION_RESTORE",
    "list_sessions_for_access",
    "restore_session",
    "soft_delete_session",
]
