"""三维正交权限模型：角色 RBAC + 访问等级 clearance + 库范围 scope，外加团队与项目。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from calliodesmo.db.base import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class ClearanceLevel(enum.IntEnum):
    """访问等级（有序）：检索需 clearance >= access_level 才可见。"""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    SECRET = 3


class LibraryScope(enum.StrEnum):
    """库范围（三层）：个人库 / 项目库 / 团队库。一个团队有多个项目，一个项目由多人维护。"""

    PERSONAL = "personal"
    PROJECT = "project"
    TEAM = "team"

    @property
    def rank(self) -> int:
        """库范围层级（personal=0 < project=1 < team=2），校验推送方向（target 须高于 source）。"""
        return _SCOPE_RANK[self]


_SCOPE_RANK: dict[LibraryScope, int] = {
    LibraryScope.PERSONAL: 0,
    LibraryScope.PROJECT: 1,
    LibraryScope.TEAM: 2,
}


class Permission(enum.StrEnum):
    INGEST = "ingest"
    QUERY = "query"
    EXPORT = "export"
    PUSH = "push"
    APPROVE = "approve"
    ANALYZE = "analyze"  # P6：提交 LLM 分析任务（高 token 成本派生生产动作，独立于 query）
    MANAGE_USERS = "manage_users"
    MANAGE_COMMUNITY = "manage_community"


#: 内置角色 -> 细粒度权限（P6 决策 1：analyze 授予 analyst / reviewer / admin 三角色）
DEFAULT_ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "analyst": {
        Permission.INGEST,
        Permission.QUERY,
        Permission.EXPORT,
        Permission.PUSH,
        Permission.ANALYZE,
    },
    "reviewer": {
        Permission.QUERY,
        Permission.EXPORT,
        Permission.PUSH,
        Permission.APPROVE,
        Permission.ANALYZE,
    },
    "admin": set(Permission),
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    clearance: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    team_memberships: Mapped[list["TeamMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    project_memberships: Mapped[list["ProjectMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[Permission] = mapped_column(
        Enum(Permission, native_enum=False, validate_strings=True, values_callable=_enum_values),
        primary_key=True,
    )

    role: Mapped[Role] = relationship(back_populates="permissions")


class UserRole(Base):
    """用户在某库范围的角色（scope 为 project/team 时表示项目/团队级角色）。"""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False, validate_strings=True, values_callable=_enum_values),
        primary_key=True,
    )

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class Team(Base):
    """团队：一个团队有多个项目。"""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class Project(Base):
    """项目：属于一个团队，由多人维护。"""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    team: Mapped[Team] = relationship(back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    """团队成员：用户加入团队，组内角色（member/manager/reviewer）。"""

    __tablename__ = "team_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    role_in_team: Mapped[str] = mapped_column(String(32), default="member")

    user: Mapped[User] = relationship(back_populates="team_memberships")
    team: Mapped[Team] = relationship(back_populates="members")


class ProjectMember(Base):
    """项目成员：用户在某项目的 RBAC 角色与项目内角色。"""

    __tablename__ = "project_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    role_in_project: Mapped[str] = mapped_column(String(32), default="member")

    user: Mapped[User] = relationship(back_populates="project_memberships")
    project: Mapped[Project] = relationship(back_populates="members")
    role: Mapped[Role] = relationship()
