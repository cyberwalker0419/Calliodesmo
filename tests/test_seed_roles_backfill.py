"""P6 Task 2：``seed_default_roles`` 差集回填幂等回归。

背景（决策 1）：原实现对已存在角色直接 ``continue``，新增权限（analyze）后既有部署
重跑 ``db seed`` 不回填 → 全员 403（生产事故级）。本文件锁定修复后的行为：

- 以旧权限集（无 analyze）预建三角色 → 重跑种子：权限**并集**含 analyze、
  不丢旧权限、不产生重复行；
- 二次 seed 权限集不变（幂等）；
- 三角色权限集合与决策 1 一致：
  analyst = {ingest, query, export, push, analyze}、
  reviewer = {query, export, push, approve, analyze}、
  admin = set(Permission) 自动全集。

回滚纪律（计划 Task 2）：回填只增不删——回收权限会把既有部署锁死在 403，
故任何情况下种子不撤销角色已有权限。
"""

from sqlalchemy import func, select

from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.service import seed_default_roles

#: 模拟「P6 之前的旧部署」权限集——无 analyze。
LEGACY_ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "analyst": {Permission.INGEST, Permission.QUERY, Permission.EXPORT, Permission.PUSH},
    "reviewer": {Permission.QUERY, Permission.EXPORT, Permission.PUSH, Permission.APPROVE},
    "admin": {p for p in Permission if p.value != "analyze"},
}


async def _role_permissions(session, role_name: str) -> set[Permission]:
    """读库取某角色当前权限集合（直查，不走 ORM 关系缓存）。"""
    rows = await session.execute(
        select(RolePermission.permission)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.name == role_name)
    )
    return set(rows.scalars())


async def _seed_legacy_roles(session) -> None:
    """按旧权限集建三角色，模拟升级前的既有部署。"""
    for name, permissions in LEGACY_ROLE_PERMISSIONS.items():
        role = Role(name=name, description=f"内置角色：{name}")
        role.permissions = [
            RolePermission(permission=p) for p in sorted(permissions, key=lambda p: p.value)
        ]
        session.add(role)
    await session.commit()


async def test_backfill_existing_roles_union_contains_analyze(session):
    """旧权限集建角色 → 重跑种子：并集含 analyze、不丢旧权限、无重复行。"""
    await _seed_legacy_roles(session)
    created = await seed_default_roles(session)
    await session.commit()

    # 角色已存在 → 不新建角色
    assert created == []
    role_count = (await session.execute(select(func.count()).select_from(Role))).scalar_one()
    assert role_count == 3

    for name, legacy in LEGACY_ROLE_PERMISSIONS.items():
        perms = await _role_permissions(session, name)
        # 并集含新权限
        assert Permission.ANALYZE in perms, f"{name} 未回填 analyze"
        # 不丢旧权限（并集 = 旧集 ∪ 目标集）
        assert perms == legacy | DEFAULT_ROLE_PERMISSIONS[name]
        # 不重复：行数 == 去重后权限数（复合主键兜底，显式断言防回归）
        row_count = (
            await session.execute(
                select(func.count())
                .select_from(RolePermission)
                .join(Role, Role.id == RolePermission.role_id)
                .where(Role.name == name)
            )
        ).scalar_one()
        assert row_count == len(perms)


async def test_second_seed_permission_sets_unchanged(session):
    """二次 seed 幂等：权限集与行数均不变。"""
    await _seed_legacy_roles(session)
    await seed_default_roles(session)
    await session.commit()
    first = {name: await _role_permissions(session, name) for name in LEGACY_ROLE_PERMISSIONS}

    created = await seed_default_roles(session)
    await session.commit()
    second = {name: await _role_permissions(session, name) for name in LEGACY_ROLE_PERMISSIONS}

    assert created == []
    assert first == second
    total_rows = (
        await session.execute(select(func.count()).select_from(RolePermission))
    ).scalar_one()
    assert total_rows == sum(len(p) for p in first.values())


async def test_fresh_seed_roles_carry_full_default_sets(session):
    """全新库首跑种子：三角色直出完整目标权限集（analyze 在内）。"""
    created = await seed_default_roles(session)
    await session.commit()
    assert {role.name for role in created} == {"analyst", "reviewer", "admin"}
    for name in DEFAULT_ROLE_PERMISSIONS:
        assert await _role_permissions(session, name) == DEFAULT_ROLE_PERMISSIONS[name]


def test_permission_analyze_member_and_default_role_sets():
    """Permission.ANALYZE 取值与三角色分配（决策 1）离线断言。"""
    assert Permission.ANALYZE.value == "analyze"
    assert DEFAULT_ROLE_PERMISSIONS["analyst"] == {
        Permission.INGEST,
        Permission.QUERY,
        Permission.EXPORT,
        Permission.PUSH,
        Permission.ANALYZE,
    }
    assert DEFAULT_ROLE_PERMISSIONS["reviewer"] == {
        Permission.QUERY,
        Permission.EXPORT,
        Permission.PUSH,
        Permission.APPROVE,
        Permission.ANALYZE,
    }
    # admin = set(Permission) 自动全集：新增枚举成员后无需手改
    assert DEFAULT_ROLE_PERMISSIONS["admin"] == set(Permission)
    assert Permission.ANALYZE in DEFAULT_ROLE_PERMISSIONS["admin"]
