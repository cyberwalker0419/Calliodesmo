"""审计写入入口：所有访问/导出/推送/合并/审核动作统一经此记录。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    source: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
        source=source,
    )
    session.add(entry)
    await session.flush()
    return entry
