"""摄入任务 ORM（P4.5 Task 5）：异步 /ingest job 状态与结果落 PG。

Task 5 异步 job 化：文件上传 -> 建 job 行（pending）-> BackgroundTasks 起进程内
worker 异步跑 ECL -> 终态落库（succeeded + result 统计 / failed + error）。
``serve`` 重启丢 running job（内存 worker 无持久队列）：job 表落 running 终态不清，
重启后遗留 running 可由运维巡检或后续版本补启动扫描（省启动扫描——Celery+Redis
留 roadmap P9，见 P4.5 计划 §依赖与风险）。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.db.base import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class JobStatus(enum.StrEnum):
    """摄入任务状态机：pending -> running -> succeeded/failed。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(Base):
    """异步摄入任务：谁提交、状态、进度、结果统计或错误。"""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, index=True
    )  # 不建 FK：worker 与请求解耦，用户可能已被删（表现与审计一致：SET NULL 语义）
    filename: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            native_enum=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    progress_stage: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # queued/extract/cognify/load/done
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # IngestStats.as_dict()
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


__all__ = ["Job", "JobStatus"]
