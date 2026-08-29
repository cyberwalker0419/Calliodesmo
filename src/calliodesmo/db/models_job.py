"""异步任务 ORM（P4.5 Task 5 摄入 job 泛化，P6 Task 11 扩列）。

P4.5 Task 5：文件上传 -> 建 job 行（pending）-> BackgroundTasks 起进程内
worker 异步跑 ECL -> 终态落库（succeeded + result 统计 / failed + error）。
``serve`` 重启丢 running job（内存 worker 无持久队列）：job 表落 running 终态不清，
重启后遗留 running 可由 ``reset_stale_running_jobs()`` 启动清残留（省持久队列——
Celery+Redis 留 roadmap P9，见 P4.5 计划 §依赖与风险）。

P6 Task 11 泛化：追加 ``task_type``（ingest / analyze，默认 ingest）与
``task_payload``（AnalysisSpec 序列化，写入前过 ``utils/json.py`` ``json_safe``），
复用同一套轮询 / 进度状态机 / 清残留机械，不建第二套 worker；ingest 链路不读不写
新列、零回归。既有库补列经 ``db/migrate.py`` ``ensure_missing_columns``（挂 cli db init）。
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
    """异步任务状态机：pending -> running -> succeeded/failed。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(Base):
    """异步任务：谁提交、任务类型、状态、进度、结果统计或错误。

    ``task_type`` 泛化（P6 Task 11）：``ingest``（摄入，默认）/ ``analyze``（LLM 分析）；
    ``task_payload`` 存 analyze 的 AnalysisSpec 序列化（写入前过 ``json_safe``），ingest 恒空。
    ``result`` 语义按类型分：ingest 存 IngestStats.as_dict()；analyze 存最小指针
    ``{report_id, status}``（报告全文在 analysis_reports 表，决策 2）。
    """

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
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # result 语义按 task_type 分：ingest=IngestStats.as_dict()；analyze={report_id, status} 最小指针
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # P6 Task 11 泛化扩列：任务类型 + 载荷（ingest 链路不读不写，零回归）。
    # 既有库经 db/migrate.py ensure_missing_columns 幂等补齐（挂 cli db init）。
    task_type: Mapped[str] = mapped_column(
        String(16), default="ingest", server_default="ingest", index=True
    )
    task_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


__all__ = ["Job", "JobStatus"]
