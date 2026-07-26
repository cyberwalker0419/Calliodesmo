---
title: P0 地基脚手架 实施计划
type: phase-plan
phase: P0
tags:
  - plan/phase
created: 2026-07-26
---
# P0 地基脚手架 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/monthly/2026-08|2026-08 月计划]]。

**Goal:** 搭起可运行、可测试的系统地基：基础设施（Postgres+pgvector/Neo4j）、配置与密钥、三维权限模型（用户/角色/权限/用户组）+ JWT 认证 + AccessContext + 审计骨架、三大抽象接口（LLMProvider/EmbeddingProvider/DocumentLoader）及默认实现、冒烟测试与 CI。

**Architecture:** `src/` 布局单包 `calliodesmo`；SQLAlchemy 2.0 异步 ORM（开发/测试用 SQLite，生产用 Postgres，P0 不引入 Alembic，建表走 `Base.metadata.create_all`）；FastAPI 仅暴露 `/healthz` + `/auth/token` + `/auth/me` 验证认证链路；Typer CLI 提供 `db init/seed`。接口层与默认实现分离，重依赖（FlagEmbedding）懒加载并列为可选 extra。

**Tech Stack:** Python 3.12 + uv · FastAPI · Typer · SQLAlchemy 2.0 (async) · PyJWT · pwdlib[argon2] · LiteLLM（钉 `>=1.85,<1.91`，>=1.93 无 Windows wheel）· pytest + pytest-asyncio + httpx · Ruff。

---

### Task 0: 仓库骨架（已完成）

提交 `f1d3f0c`：`pyproject.toml`(uv) / `.python-version` / `.gitignore` / `.env.example` / `docker-compose.yml` / `README.md` / `.github/workflows/ci.yml` / `src/calliodesmo/` 包结构 / `tests/`。`uv sync` 已安装 76 个包（litellm 1.90.6 纯 Python wheel）。

- [x] **Step 1:** `uv sync` 通过，`uv run python -c "import calliodesmo"` 成功
- [x] **Step 2:** 提交骨架

---

### Task 1: 配置模块（pydantic-settings）

**Files:**
- Create: `src/calliodesmo/config.py`
- Test: `tests/test_config.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_config.py
from calliodesmo.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_expire_minutes == 60
    assert s.embedding_dimension == 1024
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("CALLIODESMO_JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    s = Settings(_env_file=None)
    assert s.jwt_secret_key == "test-secret"
    assert s.database_url == "sqlite+aiosqlite:///:memory:"
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: calliodesmo.config`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/config.py
"""应用配置：环境变量 / .env 加载（前缀 CALLIODESMO_）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CALLIODESMO_", env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "calliodesmo"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    llm_model: str = "openai/gpt-4o-mini"
    llm_api_key: str | None = None
    llm_api_base: str | None = None

    embedding_provider: str = "bge-m3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024

    admin_username: str = "admin"
    admin_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/config.py tests/test_config.py
git commit -m "feat(config): pydantic-settings 配置模块（CALLIODESMO_ 前缀）"
```

---

### Task 2: 数据库基座（Base / 会话工厂 / 模型注册入口）

**Files:**
- Create: `src/calliodesmo/db/base.py`
- Create: `src/calliodesmo/db/session.py`
- Create: `src/calliodesmo/models.py`

- [x] **Step 1: 实现（纯骨架，测试在 Task 3 随模型一起写）**

```python
# src/calliodesmo/db/base.py
"""SQLAlchemy 声明式基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# src/calliodesmo/db/session.py
"""异步 engine 与请求级会话工厂。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from calliodesmo.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级异步会话。"""
    async with SessionLocal() as session:
        yield session
```

```python
# src/calliodesmo/models.py
"""集中导入全部 ORM 模型，保证 Base.metadata 注册完整（create_all / 未来 Alembic 共用入口）。"""

from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import Role, RolePermission, User, UserGroup, UserGroupMember, UserRole

__all__ = [
    "AuditLog",
    "Role",
    "RolePermission",
    "User",
    "UserGroup",
    "UserGroupMember",
    "UserRole",
]
```

- [x] **Step 2: 提交（随 Task 3 一起提交亦可）**
---

### Task 3: 权限三维模型（users/roles/role_permissions/user_roles/user_groups/user_group_members）

**Files:**
- Create: `src/calliodesmo/auth/models.py`
- Test: `tests/test_db_models.py`
- Create: `tests/conftest.py`

- [x] **Step 1: 写失败测试（含共享夹具）**

```python
# tests/conftest.py
"""pytest 共享夹具：内存 SQLite 会话与 ASGI 测试客户端。"""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.db.base import Base
from calliodesmo.db.session import get_session


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

```python
# tests/test_db_models.py
import pytest
from sqlalchemy import select

from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
    User,
    UserGroup,
    UserGroupMember,
    UserRole,
)
from calliodesmo.db.base import Base


def test_metadata_registers_p0_tables():
    tables = set(Base.metadata.tables)
    assert {
        "users",
        "roles",
        "role_permissions",
        "user_roles",
        "user_groups",
        "user_group_members",
        "audit_logs",
    } <= tables


async def test_user_role_group_roundtrip(session):
    user = User(username="alice", hashed_password="x", clearance=ClearanceLevel.CONFIDENTIAL)
    role = Role(name="analyst", description="分析师")
    role.permissions = [
        RolePermission(permission=Permission.QUERY),
        RolePermission(permission=Permission.INGEST),
    ]
    group = UserGroup(name="X调查组", scope=LibraryScope.ORG)
    session.add_all([user, role, group])
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, scope=LibraryScope.ORG))
    session.add(UserGroupMember(user_id=user.id, group_id=group.id, role_in_group="manager"))
    await session.commit()

    result = (await session.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert result.clearance == ClearanceLevel.CONFIDENTIAL
    assert result.is_active is True


async def test_duplicate_username_rejected(session):
    session.add(User(username="dup", hashed_password="x"))
    await session.flush()
    session.add(User(username="dup", hashed_password="y"))
    with pytest.raises(Exception):
        await session.flush()
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_db_models.py -v`
Expected: FAIL（`ModuleNotFoundError: calliodesmo.auth.models`）

- [x] **Step 3: 实现模型**

```python
# src/calliodesmo/auth/models.py
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
    )  # member / manager / reviewer

    user: Mapped[User] = relationship(back_populates="group_memberships")
    group: Mapped[UserGroup] = relationship(back_populates="members")
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_db_models.py -v`
Expected: 3 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/db src/calliodesmo/models.py src/calliodesmo/auth/models.py tests/conftest.py tests/test_db_models.py
git commit -m "feat(auth): 三维权限模型（RBAC + clearance + scope + 用户组）"
```

---

### Task 4: 密码哈希与 JWT（security）

**Files:**
- Create: `src/calliodesmo/auth/security.py`
- Test: `tests/test_security.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_security.py
import jwt
import pytest

from calliodesmo.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip():
    token = create_access_token("user-123", "secret", "HS256", 30)
    payload = decode_access_token(token, "secret", "HS256")
    assert payload["sub"] == "user-123"
    assert payload["exp"] > payload["iat"]


def test_jwt_expired():
    token = create_access_token("u", "secret", "HS256", -1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, "secret", "HS256")


def test_jwt_wrong_secret():
    token = create_access_token("u", "secret", "HS256", 30)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "other-secret", "HS256")
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/auth/security.py
"""密码哈希（pwdlib/Argon2）与 JWT 编解码（PyJWT）。"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def create_access_token(subject: str, secret_key: str, algorithm: str, expires_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, secret_key: str, algorithm: str) -> dict:
    """解码并校验 JWT；失败抛 jwt.PyJWTError 子类。"""
    return jwt.decode(token, secret_key, algorithms=[algorithm])
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_security.py -v`
Expected: 4 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/auth/security.py tests/test_security.py
git commit -m "feat(auth): Argon2 密码哈希与 JWT 编解码"
```

---

### Task 5: AccessContext 与 auth service

**Files:**
- Create: `src/calliodesmo/auth/context.py`
- Create: `src/calliodesmo/auth/service.py`
- Test: `tests/test_access_context.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_access_context.py
import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.auth.service import (
    add_group_member,
    assign_role,
    authenticate,
    create_group,
    create_user,
    get_access_context,
    seed_default_roles,
)


def test_clearance_ordering():
    assert ClearanceLevel.SECRET > ClearanceLevel.CONFIDENTIAL
    assert ClearanceLevel.CONFIDENTIAL > ClearanceLevel.INTERNAL
    assert ClearanceLevel.INTERNAL > ClearanceLevel.PUBLIC


def test_can_access():
    ctx = AccessContext(user_id=uuid.uuid4(), username="a", clearance=ClearanceLevel.CONFIDENTIAL)
    assert ctx.can_access(ClearanceLevel.PUBLIC)
    assert ctx.can_access(ClearanceLevel.CONFIDENTIAL)
    assert not ctx.can_access(ClearanceLevel.SECRET)


async def test_seed_default_roles_idempotent(session):
    first = await seed_default_roles(session)
    second = await seed_default_roles(session)
    assert len(first) == 3
    assert second == []


async def test_authenticate(session):
    await create_user(session, username="carol", password="right")
    await session.commit()
    user = await authenticate(session, username="carol", password="right")
    assert user is not None and user.username == "carol"
    assert await authenticate(session, username="carol", password="wrong") is None
    assert await authenticate(session, username="ghost", password="x") is None


async def test_get_access_context_aggregates(session):
    await seed_default_roles(session)
    user = await create_user(
        session, username="bob", password="pw", clearance=ClearanceLevel.CONFIDENTIAL
    )
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.PERSONAL)
    await assign_role(session, user=user, role_name="reviewer", scope=LibraryScope.ORG)
    group = await create_group(session, name="X调查组")
    await add_group_member(session, user=user, group=group, role_in_group="reviewer")
    await session.commit()

    ctx = await get_access_context(session, user.id)
    assert ctx is not None
    assert ctx.clearance == ClearanceLevel.CONFIDENTIAL
    assert ctx.has_permission(Permission.PUSH)
    assert ctx.has_permission(Permission.APPROVE)  # analyst ∪ reviewer
    assert not ctx.has_permission(Permission.MANAGE_USERS)
    assert ctx.library_scopes == frozenset({LibraryScope.PERSONAL, LibraryScope.ORG})
    assert group.id in ctx.group_ids


async def test_get_access_context_unknown_user(session):
    assert await get_access_context(session, uuid.uuid4()) is None
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_access_context.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/auth/context.py
"""AccessContext：贯穿请求全生命周期的统一权限上下文，检索器/合成器/Agent 统一接收做过滤。"""

import uuid
from dataclasses import dataclass, field

from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission


@dataclass(frozen=True)
class AccessContext:
    user_id: uuid.UUID
    username: str
    clearance: ClearanceLevel
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    library_scopes: frozenset[LibraryScope] = field(default_factory=frozenset)
    group_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def can_access(self, access_level: ClearanceLevel) -> bool:
        """clearance >= access_level 才可见。"""
        return self.clearance >= access_level

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
```

```python
# src/calliodesmo/auth/service.py
"""用户 / 角色 / 用户组应用服务与 AccessContext 构建。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    ClearanceLevel,
    LibraryScope,
    Role,
    RolePermission,
    User,
    UserGroup,
    UserGroupMember,
    UserRole,
)
from calliodesmo.auth.security import hash_password, verify_password


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    clearance: ClearanceLevel = ClearanceLevel.INTERNAL,
    email: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        clearance=clearance,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate(session: AsyncSession, *, username: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def seed_default_roles(session: AsyncSession) -> list[Role]:
    """幂等写入 analyst / reviewer / admin 内置角色及细粒度权限。"""
    existing = set((await session.execute(select(Role.name))).scalars())
    created: list[Role] = []
    for name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        if name in existing:
            continue
        role = Role(name=name, description=f"内置角色：{name}")
        role.permissions = [
            RolePermission(permission=p) for p in sorted(permissions, key=lambda p: p.value)
        ]
        session.add(role)
        created.append(role)
    await session.flush()
    return created


async def assign_role(
    session: AsyncSession, *, user: User, role_name: str, scope: LibraryScope
) -> UserRole:
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    link = UserRole(user_id=user.id, role_id=role.id, scope=scope)
    session.add(link)
    await session.flush()
    return link


async def create_group(
    session: AsyncSession,
    *,
    name: str,
    description: str = "",
    scope: LibraryScope = LibraryScope.ORG,
) -> UserGroup:
    group = UserGroup(name=name, description=description, scope=scope)
    session.add(group)
    await session.flush()
    return group


async def add_group_member(
    session: AsyncSession, *, user: User, group: UserGroup, role_in_group: str = "member"
) -> UserGroupMember:
    member = UserGroupMember(user_id=user.id, group_id=group.id, role_in_group=role_in_group)
    session.add(member)
    await session.flush()
    return member


async def get_access_context(session: AsyncSession, user_id: uuid.UUID) -> AccessContext | None:
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(UserRole.role).selectinload(Role.permissions),
            selectinload(User.group_memberships),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    permissions = {rp.permission for ur in user.roles for rp in ur.role.permissions}
    scopes = {ur.scope for ur in user.roles}
    group_ids = {m.group_id for m in user.group_memberships}
    return AccessContext(
        user_id=user.id,
        username=user.username,
        clearance=user.clearance,
        permissions=frozenset(permissions),
        library_scopes=frozenset(scopes),
        group_ids=frozenset(group_ids),
    )
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_access_context.py -v`
Expected: 6 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/auth/context.py src/calliodesmo/auth/service.py tests/test_access_context.py
git commit -m "feat(auth): AccessContext 与用户/角色/用户组服务"
```

---

### Task 6: 审计骨架

**Files:**
- Create: `src/calliodesmo/audit/models.py`
- Create: `src/calliodesmo/audit/service.py`
- Test: `tests/test_audit.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_audit.py
from sqlalchemy import select

from calliodesmo.audit.models import AuditLog
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.service import create_user


async def test_record_audit(session):
    user = await create_user(session, username="dave", password="pw")
    entry = await record_audit(
        session,
        user_id=user.id,
        action="login",
        resource_type="session",
        detail={"ip": "127.0.0.1"},
        source="test",
    )
    await session.commit()

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "login"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].id == entry.id
    assert rows[0].user_id == user.id
    assert rows[0].detail == {"ip": "127.0.0.1"}
    assert rows[0].created_at is not None


async def test_record_audit_anonymous(session):
    await record_audit(session, user_id=None, action="failed_login", source="api")
    await session.commit()
    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_audit.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/audit/models.py
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
    )  # login/query/export/push/approve/merge...
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(64))  # cli / api / ip
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
```

```python
# src/calliodesmo/audit/service.py
"""审计写入入口：所有访问/导出/推送/合并/审核动作统一经此记录。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.models import AuditLog


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
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
        source=source,
    )
    session.add(entry)
    await session.flush()
    return entry
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_audit.py -v`
Expected: 2 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/audit tests/test_audit.py
git commit -m "feat(audit): 审计日志表与 record_audit 骨架"
```---

### Task 7: DocumentLoader 接口与默认实现

**Files:**
- Create: `src/calliodesmo/interfaces/document_loader.py`
- Create: `src/calliodesmo/providers/text_loader.py`
- Test: `tests/test_text_loader.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_text_loader.py
from pathlib import Path

import pytest

from calliodesmo.providers.text_loader import TextDocumentLoader


async def test_load_directory(tmp_path):
    (tmp_path / "a.md").write_text("# 标题", encoding="utf-8")
    (tmp_path / "b.txt").write_text("正文", encoding="utf-8")
    (tmp_path / "c.py").write_text("print('skip')", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.md").write_text("子目录文档", encoding="utf-8")

    docs = await TextDocumentLoader().load(tmp_path)

    assert {d.doc_id for d in docs} == {"a.md", "b.txt", str(Path("sub") / "d.md")}
    by_id = {d.doc_id: d for d in docs}
    assert by_id["a.md"].content == "# 标题"
    assert by_id["a.md"].metadata["suffix"] == ".md"
    assert by_id["a.md"].metadata["size_bytes"] > 0


async def test_load_single_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("单文件", encoding="utf-8")
    docs = await TextDocumentLoader().load(f)
    assert len(docs) == 1
    assert docs[0].doc_id == "note.md"


async def test_unsupported_suffix(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        await TextDocumentLoader().load(f)


async def test_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        await TextDocumentLoader().load(tmp_path / "nope")
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_text_loader.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/interfaces/document_loader.py
"""DocumentLoader 抽象接口：把文档源加载为统一文档对象（P1 ECL 的入口）。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoadedDocument:
    doc_id: str  # 稳定标识（相对路径）
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentLoader(ABC):
    @abstractmethod
    async def load(self, source: str | Path) -> list[LoadedDocument]:
        """从文件/目录/URI 加载文档列表。"""
```

```python
# src/calliodesmo/providers/text_loader.py
"""默认 DocumentLoader：从单文件或目录加载 Markdown / 纯文本文档。"""

from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument

SUPPORTED_SUFFIXES = {".md", ".txt"}


class TextDocumentLoader(DocumentLoader):
    async def load(self, source: str | Path) -> list[LoadedDocument]:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"文档源不存在: {source}")
        if source.is_file():
            if source.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(
                    f"不支持的文件类型: {source.suffix}（支持 {sorted(SUPPORTED_SUFFIXES)}）"
                )
            files = [source]
            base = source.parent
        else:
            files = sorted(
                p
                for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
            )
            base = source

        documents = []
        for path in files:
            documents.append(
                LoadedDocument(
                    doc_id=str(path.relative_to(base)),
                    content=path.read_text(encoding="utf-8"),
                    metadata={
                        "source_path": str(path),
                        "suffix": path.suffix.lower(),
                        "size_bytes": path.stat().st_size,
                    },
                )
            )
        return documents
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_text_loader.py -v`
Expected: 4 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/interfaces/document_loader.py src/calliodesmo/providers/text_loader.py tests/test_text_loader.py
git commit -m "feat(providers): DocumentLoader 接口与文本加载默认实现"
```

---

### Task 8: EmbeddingProvider 接口与默认实现（Hash + BGE-M3）

**Files:**
- Create: `src/calliodesmo/interfaces/embedding.py`
- Create: `src/calliodesmo/providers/hash_embedding.py`
- Create: `src/calliodesmo/providers/bge_m3.py`
- Test: `tests/test_embedding.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_embedding.py
import math
import sys

import pytest

from calliodesmo.providers.bge_m3 import BgeM3EmbeddingProvider
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider


async def test_hash_embedding_deterministic_and_normalized():
    provider = HashEmbeddingProvider(dimension=32)
    assert provider.dimension == 32

    r1 = await provider.embed(["情报分析", "知识图谱"])
    r2 = await provider.embed(["情报分析"])

    assert r1.dimension == 32
    assert len(r1.vectors) == 2
    assert r1.vectors[0] == r2.vectors[0]  # 确定性
    norm = math.sqrt(sum(x * x for x in r1.vectors[0]))
    assert norm == pytest.approx(1.0)  # 单位归一化
    assert r1.vectors[0] != r1.vectors[1]  # 不同文本不同向量


async def test_bge_m3_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)  # 模拟未安装可选依赖
    provider = BgeM3EmbeddingProvider()
    assert provider.dimension == 1024
    with pytest.raises(RuntimeError, match="FlagEmbedding"):
        await provider.embed(["x"])
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_embedding.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/interfaces/embedding.py
"""EmbeddingProvider 抽象接口：BGE-M3 本地 / 远端嵌入可切换。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimension: int


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度（建库时与 pgvector 列对齐）。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """批量嵌入文本。"""
```

```python
# src/calliodesmo/providers/hash_embedding.py
"""确定性本地 EmbeddingProvider：离线开发/测试用（无语义，不替代真实模型）。"""

import hashlib
import math

from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult


class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._embed_one(t) for t in texts],
            model="hash-embedding",
            dimension=self._dimension,
        )

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 * 2 - 1 for i in range(self._dimension)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]
```

```python
# src/calliodesmo/providers/bge_m3.py
"""默认 EmbeddingProvider：BGE-M3 本地嵌入（FlagEmbedding 为可选重依赖，懒加载）。"""

import asyncio

from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult


class BgeM3EmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, model_name: str = "BAAI/bge-m3", dimension: int = 1024, use_fp16: bool = True
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._use_fp16 = use_fp16
        self._model = None  # 懒加载

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_model(self):
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:
                raise RuntimeError(
                    "BGE-M3 需要可选依赖 FlagEmbedding：uv sync --extra embedding-local"
                ) from exc
            self._model = BGEM3FlagModel(self._model_name, use_fp16=self._use_fp16)
        return self._model

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        model = self._load_model()
        outputs = await asyncio.to_thread(model.encode, texts, return_dense=True)
        vectors = [v.tolist() for v in outputs["dense_vecs"]]
        return EmbeddingResult(vectors=vectors, model=self._model_name, dimension=self._dimension)
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_embedding.py -v`
Expected: 2 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/interfaces/embedding.py src/calliodesmo/providers/hash_embedding.py src/calliodesmo/providers/bge_m3.py tests/test_embedding.py
git commit -m "feat(providers): EmbeddingProvider 接口与 Hash/BGE-M3 实现"
```

---

### Task 9: LLMProvider 接口与 LiteLLM 默认实现

**Files:**
- Create: `src/calliodesmo/interfaces/llm.py`
- Create: `src/calliodesmo/providers/litellm_provider.py`
- Test: `tests/test_llm_provider.py`

- [x] **Step 1: 写失败测试（sys.modules 桩替代真实 litellm，离线可跑）**

```python
# tests/test_llm_provider.py
import sys
from types import SimpleNamespace

from calliodesmo.interfaces.llm import LLMMessage
from calliodesmo.providers.litellm_provider import LiteLLMProvider


async def test_litellm_provider_complete(monkeypatch):
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="你好，世界"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))

    provider = LiteLLMProvider(
        model="openai/gpt-4o-mini", api_key="k", api_base="https://api.example.com"
    )
    resp = await provider.complete(
        [LLMMessage(role="user", content="hi")], temperature=0.1, max_tokens=16
    )

    assert resp.content == "你好，世界"
    assert resp.model == "openai/gpt-4o-mini"
    assert resp.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert calls["messages"] == [{"role": "user", "content": "hi"}]
    assert calls["temperature"] == 0.1
    assert calls["max_tokens"] == 16
    assert calls["api_key"] == "k"
    assert calls["api_base"] == "https://api.example.com"


async def test_litellm_provider_omits_optional_kwargs(monkeypatch):
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))

    provider = LiteLLMProvider(model="ollama/qwen2.5")
    resp = await provider.complete([LLMMessage(role="user", content="hi")])

    assert resp.usage == {}
    assert "api_key" not in calls
    assert "api_base" not in calls
    assert "max_tokens" not in calls
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_llm_provider.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/interfaces/llm.py
"""LLMProvider 抽象接口：LiteLLM 统一接入 OpenAI/Qwen/DeepSeek/Ollama，可切换。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # system / user / assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """对话补全。"""
```

```python
# src/calliodesmo/providers/litellm_provider.py
"""默认 LLMProvider：LiteLLM 统一后端（模型经 CALLIODESMO_LLM_MODEL 配置切换）。"""

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse


class LiteLLMProvider(LLMProvider):
    def __init__(self, model: str, api_key: str | None = None, api_base: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        import litellm  # 延迟导入：调用点才承担其导入开销

        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
            raw=response,
        )
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_llm_provider.py -v`
Expected: 2 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/interfaces/llm.py src/calliodesmo/providers/litellm_provider.py tests/test_llm_provider.py
git commit -m "feat(providers): LLMProvider 接口与 LiteLLM 默认实现"
```---

### Task 10: FastAPI 应用（/healthz + JWT 认证链路）

**Files:**
- Create: `src/calliodesmo/api/schemas.py`
- Create: `src/calliodesmo/api/deps.py`
- Create: `src/calliodesmo/api/app.py`
- Test: `tests/test_api_smoke.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_api_smoke.py
from sqlalchemy import select

from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_auth_flow(client, session):
    await seed_default_roles(session)
    user = await create_user(
        session, username="erin", password="pw123", clearance=ClearanceLevel.CONFIDENTIAL
    )
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.ORG)
    await session.commit()

    resp = await client.post("/auth/token", data={"username": "erin", "password": "pw123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert resp.json()["token_type"] == "bearer"

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "erin"
    assert body["clearance"] == "CONFIDENTIAL"
    assert "ingest" in body["permissions"]
    assert "org" in body["library_scopes"]

    logs = (await session.execute(select(AuditLog).where(AuditLog.action == "login"))).scalars().all()
    assert len(logs) == 1
    assert logs[0].user_id == user.id


async def test_auth_wrong_password(client, session):
    await create_user(session, username="frank", password="pw")
    await session.commit()
    resp = await client.post("/auth/token", data={"username": "frank", "password": "nope"})
    assert resp.status_code == 401


async def test_me_requires_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_api_smoke.py -v`
Expected: FAIL（`ModuleNotFoundError: calliodesmo.api.app`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/api/schemas.py
"""API 请求/响应模型。"""

import uuid

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    clearance: str
    permissions: list[str]
    library_scopes: list[str]
    group_ids: list[uuid.UUID]
```

```python
# src/calliodesmo/api/deps.py
"""FastAPI 依赖：当前 AccessContext 解析（JWT -> AccessContext）。"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.security import decode_access_token
from calliodesmo.auth.service import get_access_context
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="无效或过期的凭证",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_context(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessContext:
    try:
        payload = decode_access_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc
    context = await get_access_context(session, user_id)
    if context is None:
        raise _CREDENTIALS_EXCEPTION
    return context
```

```python
# src/calliodesmo/api/app.py
"""FastAPI 应用工厂：P0 暴露健康检查与 JWT 认证链路（Q&A 端点属 P2）。"""

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo import __version__
from calliodesmo.api.deps import get_current_context
from calliodesmo.api.schemas import MeResponse, TokenResponse
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import authenticate
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session


def create_app() -> FastAPI:
    app = FastAPI(title="Calliodesmo", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/auth/token", response_model=TokenResponse)
    async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> TokenResponse:
        user = await authenticate(session, username=form_data.username, password=form_data.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await record_audit(session, user_id=user.id, action="login", source="api")
        await session.commit()
        return TokenResponse(
            access_token=create_access_token(
                subject=str(user.id),
                secret_key=settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
                expires_minutes=settings.jwt_expire_minutes,
            )
        )

    @app.get("/auth/me", response_model=MeResponse)
    async def me(context: AccessContext = Depends(get_current_context)) -> MeResponse:
        return MeResponse(
            user_id=context.user_id,
            username=context.username,
            clearance=context.clearance.name,
            permissions=sorted(p.value for p in context.permissions),
            library_scopes=sorted(s.value for s in context.library_scopes),
            group_ids=sorted(context.group_ids, key=str),
        )

    return app


app = create_app()
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_api_smoke.py -v`
Expected: 4 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/api tests/test_api_smoke.py
git commit -m "feat(api): /healthz 与 JWT 登录、/auth/me AccessContext 链路"
```

---

### Task 11: Typer CLI（--version / db init / db seed）

**Files:**
- Create: `src/calliodesmo/cli.py`
- Test: `tests/test_cli.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_cli.py
import sqlite3

from typer.testing import CliRunner

from calliodesmo import __version__
from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_db_init_and_seed(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("CALLIODESMO_ADMIN_PASSWORD", "admin-pw")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["db", "init"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["db", "seed"])
        assert result.exit_code == 0, result.output
    finally:
        get_settings.cache_clear()

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "users",
        "roles",
        "role_permissions",
        "user_roles",
        "user_groups",
        "user_group_members",
        "audit_logs",
    } <= tables
    roles = {r[0] for r in conn.execute("SELECT name FROM roles")}
    assert {"analyst", "reviewer", "admin"} <= roles
    admins = list(conn.execute("SELECT username, clearance FROM users WHERE username='admin'"))
    assert admins == [("admin", "SECRET")]
    conn.close()
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: calliodesmo.cli`）

- [x] **Step 3: 实现**

```python
# src/calliodesmo/cli.py
"""Calliodesmo CLI（Typer）：db init / db seed。"""

import asyncio

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from calliodesmo import __version__
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base

app = typer.Typer(help="Calliodesmo：三层知识图谱驱动的智能情报分析平台。")
db_app = typer.Typer(help="数据库管理命令。")
app.add_typer(db_app, name="db")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"calliodesmo {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="显示版本号。"
    ),
) -> None:
    """Calliodesmo 命令行入口。"""


async def _create_all(database_url: str) -> None:
    import calliodesmo.models  # noqa: F401  注册全部 ORM 模型

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@db_app.command("init")
def db_init() -> None:
    """按 Base.metadata 建表（幂等；未来迁移到 Alembic）。"""
    settings = get_settings()
    asyncio.run(_create_all(settings.database_url))
    typer.echo("数据库表已创建。")


async def _seed(
    database_url: str, admin_username: str, admin_password: str | None
) -> tuple[int, bool]:
    import calliodesmo.models  # noqa: F401
    from calliodesmo.auth.models import ClearanceLevel, LibraryScope, User
    from calliodesmo.auth.service import assign_role, create_user, seed_default_roles

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        roles = await seed_default_roles(session)
        admin_created = False
        if admin_password:
            existing = (
                await session.execute(select(User).where(User.username == admin_username))
            ).scalar_one_or_none()
            if existing is None:
                admin = await create_user(
                    session,
                    username=admin_username,
                    password=admin_password,
                    clearance=ClearanceLevel.SECRET,
                )
                await assign_role(session, user=admin, role_name="admin", scope=LibraryScope.ORG)
                admin_created = True
        await session.commit()
    await engine.dispose()
    return len(roles), admin_created


@db_app.command("seed")
def db_seed() -> None:
    """写入内置角色/权限，并按 CALLIODESMO_ADMIN_* 创建初始管理员（幂等）。"""
    settings = get_settings()
    roles_created, admin_created = asyncio.run(
        _seed(settings.database_url, settings.admin_username, settings.admin_password)
    )
    status = "已创建" if admin_created else "已存在或未提供密码（跳过）"
    typer.echo(f"新建角色 {roles_created} 个；管理员{status}。")
```

- [x] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 passed

- [x] **Step 5: 提交**

```bash
git add src/calliodesmo/cli.py tests/test_cli.py
git commit -m "feat(cli): Typer 入口与 db init/seed 命令"
```

---

### Task 12: 全量验收（Ruff + 全量测试 + compose 校验 + CI）

**Files:**
- Verify: `docker-compose.yml`、`.github/workflows/ci.yml`（Task 0 已建）

- [x] **Step 1: Ruff 格式化与静态检查**

```bash
uv run ruff format .
uv run ruff check --fix .
```
Expected: 无 error（import 排序等自动修复）

- [x] **Step 2: 全量测试**

```bash
uv run pytest -q
```
Expected: 全部通过（约 25 个用例）

- [x] **Step 3: compose 配置校验**

```bash
docker compose config -q
```
Expected: 无输出（配置合法）。本机有 Docker 时可 `docker compose up -d` 实测起库。

- [x] **Step 4: 提交**

```bash
git add -A
git commit -m "chore(p0): ruff 格式化与全量验收"
```

---

## 自查清单（写完计划后对照 roadmap 复核）

- [x] docker-compose(Postgres+pgvector/Neo4j)、配置密钥 -> Task 0/1
- [x] 三接口(LLMProvider/EmbeddingProvider/DocumentLoader)+默认实现 -> Task 7/8/9
- [x] 用户/角色/权限/用户组表 + JWT 认证 + AccessContext + 审计骨架 -> Task 3/4/5/6/10
- [x] CI + 冒烟测试 -> Task 0/10/11/12
- [x] 类型一致性：`AccessContext` 字段、`get_session` 依赖键、`DEFAULT_ROLE_PERMISSIONS` 在测试与实现间一致

## 执行方式

按用户目标 inline 顺序执行（本计划即执行脚本），每 Task 完成后勾选 checkbox 并提交。

> [!success] 执行记录（2026-07-26）
> P0 全部 12 个 Task 当日由 agent inline 执行完毕：ruff 0 error，`pytest` **31 passed**。提交：骨架 `f1d3f0c` -> 计划文档 `936a9c1` -> 全量实现 `6ae3588`（分支 `codex/p0-scaffolding`）。Task 12 Step 3 的 `docker compose up -d` 实测起库因本机未装 Docker 留待学生环境执行（compose/CI YAML 已通过解析校验）。

> [!note] 补充（2026-07-26）：无 Docker 部署路径
> 应用户要求补全非 Docker 部署：`calliodesmo serve`（uvicorn 启动 API）、`scripts/bootstrap.ps1` / `scripts/bootstrap.sh`（幂等一键引导，支持 SQLite 降级模式）、[[docs/deploy/native|原生部署指南]]（三平台 Postgres+pgvector / Neo4j 原生安装、systemd/Windows 服务、生产要点、验证清单）。