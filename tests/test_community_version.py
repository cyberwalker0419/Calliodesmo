"""Task 8：社区版本快照 + 回滚（append 式）+ merge/split。"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, User
from calliodesmo.collab.community_version import (
    CommunityVersionService,
    restore_record,
    snapshot_record,
)
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore


def _ctx(user_id):
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(),
    )


async def _user(session) -> User:
    """建真实 User（PG 强制 FK，CommunityVersion.created_by 须引用已存在行）。"""
    u = User(username=f"u-{uuid.uuid4().hex[:8]}", hashed_password="x")
    session.add(u)
    await session.flush()
    return u


def _record(community_id="c1", title="社区1", members=None, owner=None):
    return CommunityRecord(
        community_id=community_id,
        level=1,
        title=title,
        summary="s",
        member_entity_names=members or ["d1"],
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
    )


async def test_create_and_list_versions(session):
    """create_version 递增 version，list_versions 按序。"""
    uid = (await _user(session)).id
    svc = CommunityVersionService()
    store = InMemoryCommunityStore()
    rec = _record(owner=uid)
    await store.upsert_communities([rec])
    v1 = await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    rec.title = "改名"
    await store.upsert_communities([rec])
    v2 = await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    assert v1.version == 1
    assert v2.version == 2
    versions = await svc.list_versions(session, "c1")
    assert [v.version for v in versions] == [1, 2]


async def test_rollback_append_creates_new_version(session):
    """B3：rollback 用旧快照恢复 + 创建新版本（不删历史）。"""
    uid = (await _user(session)).id
    svc = CommunityVersionService()
    store = InMemoryCommunityStore()
    rec = _record(owner=uid)
    await store.upsert_communities([rec])
    await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    rec.title = "改名"
    await store.upsert_communities([rec])
    await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    # rollback 到 v1（恢复原标题）+ 创建新版本 v3
    v3 = await svc.rollback(session, "c1", 1, store=store, created_by=uid)
    assert v3.version == 3  # append 新版本
    restored = store._records["c1"]
    assert restored.title == "社区1"
    # 历史版本仍可查（v1/v2/v3，不删）
    versions = await svc.list_versions(session, "c1")
    assert [v.version for v in versions] == [1, 2, 3]


async def test_rollback_nonexistent_version_raises(session):
    uid = (await _user(session)).id
    svc = CommunityVersionService()
    store = InMemoryCommunityStore()
    with pytest.raises(ValueError, match="不存在"):
        await svc.rollback(session, "c1", 99, store=store, created_by=uid)


def test_snapshot_restore_roundtrip():
    """snapshot -> restore 还原 CommunityRecord（enum/UUID 往返）。"""
    uid = uuid.uuid4()
    rec = _record(members=["d1", "d2"], owner=uid)
    rec.metadata["manual"] = True
    snap = snapshot_record(rec)
    restored = restore_record(snap)
    assert restored.community_id == rec.community_id
    assert restored.title == rec.title
    assert restored.member_entity_names == ["d1", "d2"]
    assert restored.access_level == ClearanceLevel.INTERNAL
    assert restored.library_scope == LibraryScope.PERSONAL
    assert restored.owner_id == uid
    assert restored.metadata.get("manual") is True


async def test_merge_combines_members_and_deletes_source(session):
    uid = (await _user(session)).id
    store = InMemoryCommunityStore()
    await store.upsert_communities(
        [
            _record("c1", "目标", members=["d1"], owner=uid),
            _record("c2", "源", members=["d2"], owner=uid),
        ]
    )
    ok = await store.merge("c1", ["c2"], access=_ctx(uid))
    assert ok is True
    target = store._records["c1"]
    assert set(target.member_entity_names) == {"d1", "d2"}
    assert "c2" not in store._records  # source 删


async def test_split_creates_new_communities(session):
    uid = (await _user(session)).id
    store = InMemoryCommunityStore()
    await store.upsert_communities([_record("c1", "原", members=["d1", "d2", "d3"], owner=uid)])
    new_ids = await store.split("c1", [["d1", "d2"], ["d3"]], access=_ctx(uid))
    assert len(new_ids) == 2
    assert all(nid in store._records for nid in new_ids)
    members_all: set[str] = set()
    for nid in new_ids:
        members_all |= set(store._records[nid].member_entity_names)
    assert members_all == {"d1", "d2", "d3"}


# ---- P4.5 Task 4 Step 3：PgCommunityStore 持久化贯通（merge/split/rollback 重启不丢）----
# 证明社区手动操作经 PgCommunityStore 真后端落库，进程重启（新 store 实例 + 新 session，
# 同一 PG）后状态与预期一致——不残留半写。与 InMemory 用例对照（同一契约）。


@pytest.fixture
def factory(_pg_engine):
    """PgCommunityStore 用的 session factory（复用会话级 _pg_engine）。"""
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


def _pg_community_store(factory):
    """构造 PgCommunityStore（lazy import：模块顶层 import 需 pgvector，CI 未装时跳过）。"""
    pytest.importorskip("pgvector")
    from calliodesmo.providers.pg_community_store import PgCommunityStore

    return PgCommunityStore(factory)


async def test_pg_merge_persists_across_restart(session, factory):
    """merge 落库：c2 并入 c1 -> 重启 store -> c1 成员并集、c2 已删。"""
    uid = (await _user(session)).id
    await session.commit()  # user 落库（后续 CommunityVersion.created_by FK 依赖）

    access = _ctx(uid)
    store = _pg_community_store(factory)
    await store.upsert_communities(
        [
            _record("c1", "目标", members=["d1"], owner=uid),
            _record("c2", "源", members=["d2"], owner=uid),
        ]
    )
    assert await store.merge("c1", ["c2"], access=access) is True

    # 重启：新 store 实例（同一 PG）
    store2 = _pg_community_store(factory)
    comms = {c.community_id: c for c in await store2.list_communities(access=access)}
    assert "c1" in comms and "c2" not in comms
    assert set(comms["c1"].member_entity_names) == {"d1", "d2"}


async def test_pg_split_persists_across_restart(session, factory):
    """split 落库：拆分 c1 -> 重启 store -> 原社区保留 + 新社区成员全覆盖。"""
    uid = (await _user(session)).id
    await session.commit()

    access = _ctx(uid)
    store = _pg_community_store(factory)
    await store.upsert_communities([_record("c1", "原", members=["d1", "d2", "d3"], owner=uid)])
    new_ids = await store.split("c1", [["d1", "d2"], ["d3"]], access=access)
    assert len(new_ids) == 2

    store2 = _pg_community_store(factory)
    comms = {c.community_id: c for c in await store2.list_communities(access=access)}
    assert "c1" in comms  # 原社区保留
    assert all(nid in comms for nid in new_ids)
    members_all: set[str] = set()
    for nid in new_ids:
        members_all |= set(comms[nid].member_entity_names)
    assert members_all == {"d1", "d2", "d3"}


async def test_pg_rollback_persists_across_restart(session, factory):
    """rollback 真后端适配：改名建版本 -> rollback + commit -> 重启 store + 新 session，
    社区恢复旧版本 + 版本历史完整（store 写与 version 写两轨都落库，不残留半写）。"""
    uid = (await _user(session)).id
    await session.commit()

    access = _ctx(uid)
    svc = CommunityVersionService()
    store = _pg_community_store(factory)

    rec = _record("c1", "原标题", members=["d1"], owner=uid)
    await store.upsert_communities([rec])
    await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    await session.commit()  # v1 落库

    rec.title = "改名"
    await store.upsert_communities([rec])
    await svc.create_version(
        session, community_id="c1", snapshot=snapshot_record(rec), created_by=uid
    )
    await session.commit()  # v2 落库

    # rollback 到 v1 + commit（store 恢复 + 新版本 v3 两轨都落库）
    v3 = await svc.rollback(session, "c1", 1, store=store, created_by=uid)
    await session.commit()
    assert v3.version == 3

    # 重启：新 store + 新 session（模拟进程重启）
    store2 = _pg_community_store(factory)
    comms = {c.community_id: c for c in await store2.list_communities(access=access)}
    assert comms["c1"].title == "原标题"  # 恢复旧版本
    async with factory() as session2:
        versions = await svc.list_versions(session2, "c1")
        assert [v.version for v in versions] == [1, 2, 3]  # 版本历史完整（含回滚新版本）
