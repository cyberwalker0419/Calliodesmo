"""分析报告 ORM（P6 Task 12，决策 2）：报告持久化为三维权限一等公民。

报告是派生情报资产：``Job.result`` 只存 ``{report_id, status}`` 最小指针，报告全文
（信封 ``payload`` + 运行记录）落本表，行级访问控制经 ``stores/visibility.py``
``visible_to`` 三维过滤（clearance + scope + owner），可审计、可列历史。

三维权限五字段齐备（access_level / library_scope / owner_id / project_id / team_id）→
``visible_to`` 的 ``AccessOwned`` Protocol 鸭子类型直接生效：personal 报告他人不可见；
低 clearance 看不到高密报告（本人亦不可见，密级不洗白）。

密级继承（决策 4）：``access_level = max(材料各级, INTERNAL)``，由 worker 经
``analysis/access.compute_report_access_level`` 算得传入；``library_scope`` 固定
``personal``、``owner_id`` = 提交者、``project_id`` / ``team_id`` 恒 None——报告默认
个人库，不进协作审批流。

**报告落库口径**（计划「报告落库口径」）：仅 ``ok`` / ``partial`` 落报告行（用户可见
降级原因而非黑洞）；解析彻底失败 / LLM 调用异常等完全失败走 ``job failed`` + 可读
``error`` + 审计记 failed，不落空报告（``AnalysisReportStore.create`` 拒 ``failed``，
Task 13 worker 消费本口径）。

不依赖 pgvector → ``models.py`` 无条件集中导入注册（不进 try/except 分支；漏注册 →
``cli db init`` / 测试 schema 缺表，测试即红）。复合索引
``ix_analysis_reports_owner_created(owner_id, created_at)`` 服务历史列表主查询。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.base import Base


class AnalysisReportORM(Base):
    """分析报告：谁提交、哪类分析、状态、完整信封、密级继承与三维权限五字段。

    - ``job_id`` 可空且不建 FK（同 ``Job.user_id`` 无 FK 决策：worker 与请求解耦，
      job 行可能已被清）；``user_id`` 为提交者，同样不建 FK。
    - ``payload`` 为完整信封（``AnalysisEnvelope.model_dump()``，Task 13 worker 装配），
      写入前必过 ``utils/json.py`` ``json_safe``（``AnalysisReportStore.create`` 边界执行）。
    - ``status`` 仅 ``ok`` / ``partial``（落库口径见模块 docstring；``failed`` 不落行）。
    - ``usage_`` 为 token 用量运行记录（列名带下划线，避免与保留字 / 惯用名冲突，
      同 ``metadata_`` 先例但此处列名与属性名一致）。
    """

    __tablename__ = "analysis_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, index=True
    )  # 提交者（不建 FK，同 Job.user_id）
    task_type: Mapped[str] = mapped_column(String(32), index=True)  # AnalysisType 值
    status: Mapped[str] = mapped_column(String(16))  # ok / partial（落库口径见模块 docstring）
    subject_label: Mapped[str] = mapped_column(String(512))  # 分析对象描述（文档标题拼接 / 问题）
    payload: Mapped[dict] = mapped_column(JSON)  # 完整信封（写入前必过 json_safe）
    source_doc_ids: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    source_chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # 材料块数
    # 三维权限五字段：密级继承（决策 4）+ visible_to 的 AccessOwned 鸭子类型直接生效
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL, index=True
    )
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)  # = 提交者
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # personal 下恒 None
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # personal 下恒 None
    # 运行记录：模型 / 提示词版本 / token 用量
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    usage_: Mapped[dict] = mapped_column(JSON, default=dict)
    # P8 接地度侧车（可空：历史报告无此列值，读取端按 None 兼容）
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # P8 生命周期（版本 / 软删除 / 复核状态机）
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lock_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # 乐观锁：并发写版本链时由 SQLAlchemy 在 UPDATE 上带 lock_version 条件
    __mapper_args__: ClassVar[dict] = {"version_id_col": lock_version}

    __table_args__ = (
        # 历史列表主查询（list_visible 按 owner 过滤 + created_at 降序分页）
        Index("ix_analysis_reports_owner_created", "owner_id", "created_at"),
    )


class AnalysisReportVersionORM(Base):
    """报告版本快照（append-only）：编辑 / 重分析 / 回滚各追加一行，旧行不可变。

    ``snapshot`` 保存报告行当时的完整可恢复状态（信封 + verification + 运行记录），
    回滚采用 append 式（同 P4 社区版本先例）：不以旧行覆盖新行，而是追加一个
    内容等于目标版本的新行，保证版本链可审计。
    """

    __tablename__ = "analysis_report_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        # 版本号唯一：并发写时由 DB 兜底（配合 ORM 乐观锁）
        UniqueConstraint("report_id", "version", name="uq_analysis_report_versions_report_version"),
    )


__all__ = ["AnalysisReportORM", "AnalysisReportVersionORM"]
