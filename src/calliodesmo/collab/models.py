"""协作推送域 ORM：贡献请求(MR) 与状态机。

贡献请求记录"谁、把什么、从哪个库、推到哪个库、处于何状态"；状态机
``draft -> submitted -> approved/rejected -> merged``（外加 ``closed`` 撤销，
``rejected`` 可 reopen 回 ``submitted`` 复用同一 MR 上下文）。

元数据（状态/审核/指派/版本）走 ORM，与 auth/audit 同库，事务可持久；
被推送的图谱数据走内存 stores（见 ``stores`` / ``providers``）。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.auth.models import LibraryScope
from calliodesmo.db.base import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class ContributionStatus(enum.StrEnum):
    """贡献请求状态机。

    draft -> submitted -> approved/rejected -> merged；外加 closed 终态；
    rejected 可 reopen -> submitted（保留同一 MR 上下文，作者修改重提）。
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    CLOSED = "closed"


class Contribution(Base):
    """贡献请求(MR)：谁、把什么、从哪个库、推到哪个库、处于何状态。"""

    __tablename__ = "contributions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False, validate_strings=True, values_callable=_enum_values),
        nullable=False,
    )
    target_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False, validate_strings=True, values_callable=_enum_values),
        nullable=False,
    )
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    target_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ContributionStatus] = mapped_column(
        Enum(
            ContributionStatus,
            native_enum=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        default=ContributionStatus.DRAFT,
        nullable=False,
    )
    # 推送的文档 id 列表（内容清单的锚）；manifest 由 Task 2 填各类型 id+计数
    doc_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 时间列统一 TIMESTAMPTZ（P6 Task 1 闭环 2026-W31 逾期 TODO）；服务层写 aware UTC。
    # 既有库列型回填（ALTER ... TYPE TIMESTAMPTZ USING <col> AT TIME ZONE 'UTC'）由
    # P6 Task 11 db/migrate.py 承接；全新库经 create_all 直出。
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 【修订】并发：乐观锁版本号，状态机流转事务内校验，防并发重复 approve/merge
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
