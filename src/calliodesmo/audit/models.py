"""审计日志表（P0 骨架：谁/何时/做了什么/从哪来；P9 硬化：查询、脱敏、留存策略）。

P9 Task 4 把 ``created_at`` 升为 ``TIMESTAMPTZ``：原列为 ``timestamp without time
zone`` + ``server_default=now()``，在 ``TimeZone=Asia/Shanghai`` 的库里落的是**本地
墙上时间**，与保留期 / 时间窗过滤的 UTC 语义差 8 小时（留存清理会误删）。既有库的
列型回填见 ``db/migrate.py``。查询主路径索引随列一并补齐。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(
        String(64), index=True
    )  # login/query/export/push/approve/merge
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(64))  # cli / api / ip
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        # 审计查询主路径：按动作 / 按操作者 + 时间倒序分页
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_user_created_at", "user_id", "created_at"),
    )
