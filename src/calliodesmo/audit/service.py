"""审计写入与查询入口：所有访问/导出/推送/合并/审核动作统一经此记录（P9 硬化）。

P0 骨架只解决「写」；P9 补「查 / 脱敏 / 留存」：

- ``sanitize_audit_detail``：写入前递归脱敏敏感键（``password`` / ``token`` /
  ``secret`` / ``api_key`` / ``authorization`` / ``cookie`` 等），避免凭据经
  detail 落库——``record_audit`` 默认调用，调用方无需自觉；
- ``list_audit_logs``：按 action / user / source / 时间窗过滤 + 分页 + 总数，
  JOIN 出操作者用户名（运维读得懂）；
- ``purge_expired_audit``：按保留天数清理，``retention_days <= 0`` = 永久保留
  （默认），**只在显式调用时删除**，不挂后台任务，避免隐式删证。
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import User

#: 命中即脱敏的键名子串（大小写不敏感）
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
)
#: 脱敏后的占位值
MASK = "***"


@dataclass(frozen=True)
class AuditEntry:
    """审计查询出参：日志行 + 操作者用户名（匿名 / 已删用户为 None）。"""

    id: uuid.UUID
    user_id: uuid.UUID | None
    username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    detail: dict[str, Any]
    source: str | None
    created_at: datetime | None


def sanitize_audit_detail(detail: Any) -> Any:
    """递归脱敏审计 detail：敏感键值替换为 ``***``，其余原样保留（不修改入参）。"""
    if detail is None:
        return {}
    if isinstance(detail, Mapping):
        return {
            key: (MASK if _is_sensitive_key(key) else sanitize_audit_detail(value))
            for key, value in detail.items()
        }
    if isinstance(detail, list):
        return [sanitize_audit_detail(item) for item in detail]
    return detail


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


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
    """写一条审计日志（detail 入库前强制脱敏）。"""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=sanitize_audit_detail(detail or {}),
        source=source,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_audit_logs(
    session: AsyncSession,
    *,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEntry], int]:
    """按条件查询审计日志，返回 ``(当前页条目, 命中总数)``（时间倒序）。"""
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if source:
        conditions.append(AuditLog.source == source)
    if since is not None:
        conditions.append(AuditLog.created_at >= _as_utc(since))
    if until is not None:
        conditions.append(AuditLog.created_at < _as_utc(until))

    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            select(AuditLog, User.username)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(max(limit, 0))
            .offset(max(offset, 0))
        )
    ).all()
    entries = [
        AuditEntry(
            id=log.id,
            user_id=log.user_id,
            username=username,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            detail=dict(log.detail or {}),
            source=log.source,
            created_at=log.created_at,
        )
        for log, username in rows
    ]
    return entries, int(total)


async def purge_expired_audit(session: AsyncSession, *, retention_days: int | None = None) -> int:
    """删除超过保留期的审计行，返回删除条数。

    ``retention_days`` 缺省取配置 ``audit_retention_days``；``<= 0`` 表示永久保留
    （直接返回 0）。删除是外向且不可逆的动作，只由显式调用（CLI / 运维脚本）触发。
    """
    from calliodesmo.config import get_settings

    days = get_settings().audit_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0
    # 与列同一时钟做减法（now() - 保留天数），避免应用与库时区不一致导致误删
    cutoff = func.now() - func.make_interval(0, 0, 0, days)
    result = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    return int(result.rowcount or 0)


def _as_utc(moment: datetime) -> datetime:
    """时间窗入参归一为 aware UTC（naive 输入按 UTC 解释；列已是 TIMESTAMPTZ）。"""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


__all__ = [
    "MASK",
    "AuditEntry",
    "list_audit_logs",
    "purge_expired_audit",
    "record_audit",
    "sanitize_audit_detail",
]
