"""Agent 会话 ORM 三表（P7 T11，决策 4）：会话 / 消息 / 执行持久为三维权限一等公民。

**ORM 是 system of record，checkpoint 只承载执行态**（checkpoint 格式不可查询 /
不可审计 / 无法 ``visible_to`` 过滤，不能当系统记录）。

- ``AgentSession``：owner + 五 access 字段（默认 personal）+ 创建时 clearance /
  scope 快照（密级不洗白：读须当前 clearance ≥ 建时，T12 复检）+ mode。
- ``AgentMessage``：role / content / run 指针；内容不得含高于会话密级的证据明文
  （落库前密级断言钩子，T12）。
- ``AgentRun``：轨迹 JSON + usage + steps + 状态（pending/running/succeeded/failed）。

五字段齐备 → ``stores/visibility.visible_to`` 的 ``AccessOwned`` 鸭子类型直接生效。
不依赖 pgvector → ``models.py`` 无条件集中导入注册（漏注册 → 测试 schema 缺表即红）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.base import Base


class AgentSessionORM(Base):
    """Agent 会话：system of record 之一；可见性经 visible_to 三维过滤。"""

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)  # = 创建者，visible_to 鸭子字段
    mode: Mapped[str] = mapped_column(String(16), default="react", index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    # 三维权限五字段（默认 personal，同报告口径）
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL, index=True
    )
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 创建时快照（密级不洗白：读须当前 clearance >= 建时；scope 移除后不可见，T12）
    clearance_at_create: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    scope_at_create: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentMessageORM(Base):
    """会话消息：user / assistant 轮次；run_id 指向产出该消息的执行。"""

    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentRunORM(Base):
    """回合执行：轨迹 JSON（前端折叠展示与评估消费）+ usage + 状态。"""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    tool_trace: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


__all__ = ["AgentMessageORM", "AgentRunORM", "AgentSessionORM"]
