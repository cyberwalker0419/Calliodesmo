"""三维正交权限模型：角色 RBAC + 访问等级 clearance + 库范围 scope，外加用户组。"""

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
    PERSONAL = "personal"
    ORG = "org"


class Permission(enum.StrEnum):
    INGEST = "ingest"
    QUERY = "query"
    EXPORT = "export"
    PUSH = "push"
    APPROVE = "approve"
    MANAGE_USERS = "manage_users"
    MANAGE_COMMUNITY = "manage_community"


#: 内置角色 -> 细粒度权限
DEFAULT_ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "analyst": {Permission.INGEST, Permission.QUERY, Permission.EXPORT, Permission.PUSH},
    "reviewer": {Permission.QUERY, Permission.EXPORT, Permission.PUSH, Permission.APPROVE},
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
    group_memberships: Mapped[list["UserGroupMember"]] = relationship(
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


class UserGroup(Base):
    __tablename__ = "user_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False, validate_strings=True, values_callable=_enum_values),
        default=LibraryScope.ORG,
    )

    members: Mapped[list["UserGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class UserGroupMember(Base):
    __tablename__ = "user_group_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True
    )
    role_in_group: Mapped[str] = mapped_column(
        String(32), default="member"
    )  # member/manager/reviewer

    user: Mapped[User] = relationship(back_populates="group_memberships")
    group: Mapped[UserGroup] = relationship(back_populates="members")
