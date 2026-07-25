"""审计日志表（P0 骨架：谁/何时/做了什么/从哪来；P9 硬化：查询 UI、留存策略、导出管控）。"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Uuid, func
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
