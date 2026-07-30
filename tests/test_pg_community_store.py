"""PgCommunityStore 契约测试（P4.5 Task 2 Step 4）。

走真实 PG（``session`` 夹具清空 + ``_pg_engine`` factory），验证 upsert/list + P3 手动操作
（rename/set_access_level/add/remove_member_doc，置 manual 标记）+ merge/split，对齐
InMemoryCommunityStore 语义。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.providers.pg_community_store import PgCommunityStore


def _ctx(user_id, *, clearance=ClearanceLevel.SECRET, project_ids=(), team_ids=()) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        project_ids=frozenset(project_ids),
        team_ids=frozenset(team_ids),
    )


def _comm(
    cid,
    owner,
    *,
    title="T",
    summary="S",
    members=("d1",),
    level=1,
    scope=LibraryScope.PERSONAL,
    access=ClearanceLevel.INTERNAL,
) -> CommunityRecord:
    return CommunityRecord(
        community_id=cid,
        level=level,
        title=title,
        summary=summary,
        member_entity_names=list(members),
        metadata={},
        access_level=access,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
        project_id=None,
        team_id=None,
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


async def test_upsert_and_list(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c1", owner, title="B"), _comm("c2", owner, title="A")])
    listed = await store.list_communities(access=_ctx(owner))
    assert [c.community_id for c in listed] == ["c2", "c1"]  # title 排序
    # 别人的 personal 不可见
    other = uuid.uuid4()
    assert await store.list_communities(access=_ctx(other)) == []


async def test_upsert_idempotent(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c1", owner, title="v1")])
    await store.upsert_communities([_comm("c1", owner, title="v2")])
    listed = await store.list_communities(access=_ctx(owner))
    assert len(listed) == 1
    assert listed[0].title == "v2"


async def test_rename_marks_manual(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c1", owner)])
    assert await store.rename("c1", "新名", access=_ctx(owner)) is True
    listed = await store.list_communities(access=_ctx(owner))
    assert listed[0].title == "新名"
    assert listed[0].metadata.get("manual") is True  # 手动标记
    # 不可见 -> False
    assert await store.rename("c1", "x", access=_ctx(uuid.uuid4())) is False


async def test_add_remove_member_doc(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c1", owner, members=["d1"])])
    assert await store.add_member_doc("c1", "d2", access=_ctx(owner)) is True
    listed = await store.list_communities(access=_ctx(owner))
    assert "d2" in listed[0].member_entity_names
    assert await store.remove_member_doc("c1", "d1", access=_ctx(owner)) is True
    listed = await store.list_communities(access=_ctx(owner))
    assert "d1" not in listed[0].member_entity_names


async def test_set_access_level(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c1", owner, access=ClearanceLevel.INTERNAL)])
    assert await store.set_access_level("c1", ClearanceLevel.SECRET, access=_ctx(owner)) is True
    listed = await store.list_communities(access=_ctx(owner, clearance=ClearanceLevel.SECRET))
    assert listed[0].access_level == ClearanceLevel.SECRET


async def test_merge(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities(
        [
            _comm("t", owner, members=["a"], title="T", summary="T-sum"),
            _comm("s1", owner, members=["b"], title="S1", summary="S1-sum"),
            _comm("s2", owner, members=["a", "c"], title="S2", summary="S2-sum"),
        ]
    )
    assert await store.merge("t", ["s1", "s2"], access=_ctx(owner)) is True
    listed = {c.community_id: c for c in await store.list_communities(access=_ctx(owner))}
    assert "s1" not in listed and "s2" not in listed  # source 删
    assert set(listed["t"].member_entity_names) == {"a", "b", "c"}  # 并集
    assert "S1-sum" in listed["t"].summary and "S2-sum" in listed["t"].summary  # summary 拼接


async def test_split(session, factory):
    store = PgCommunityStore(factory)
    owner = uuid.uuid4()
    await store.upsert_communities([_comm("c", owner, members=["a", "b", "c", "d"])])
    new_ids = await store.split("c", [["a", "b"], ["c", "d"]], access=_ctx(owner))
    assert new_ids == ["c-split-0", "c-split-1"]
    listed = {com.community_id: com for com in await store.list_communities(access=_ctx(owner))}
    assert set(listed["c-split-0"].member_entity_names) == {"a", "b"}
    assert set(listed["c-split-1"].member_entity_names) == {"c", "d"}
    assert "c" in listed  # 原社区保留
