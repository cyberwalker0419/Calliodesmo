"""Task 2：PushService 收集与差异清单(manifest)。"""

import types
import uuid

from sqlalchemy import select

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, User
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.push import PushService
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

_svc = PushService()


def _ctx(user_id, *, permissions=None, project_ids=None, team_ids=None) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=permissions or frozenset(),
        project_ids=frozenset(project_ids or []),
        team_ids=frozenset(team_ids or []),
    )


def _stores():
    return types.SimpleNamespace(
        vector_store=InMemoryVectorStore(),
        graph_store=InMemoryGraphStore(),
        community_store=InMemoryCommunityStore(),
    )


async def _user(session, name="u") -> User:
    u = User(username=name, hashed_password="x")
    session.add(u)
    await session.flush()
    return u


async def _seed_source(stores, user_id):
    """灌源 personal 库：doc d 的 chunk/entity/relation/community。"""
    await stores.vector_store.upsert_chunks(
        [
            ChunkRecord(
                chunk_id="d#0",
                doc_id="d",
                content="c0",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
            ChunkRecord(
                chunk_id="d#1",
                doc_id="d",
                content="c1",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
            # 另一份文档，不应被收集
            ChunkRecord(
                chunk_id="e#0",
                doc_id="e",
                content="other",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ]
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="AI 公司",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ],
        [
            RelationRecord(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ],
    )
    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id="doc-d",
                level=1,
                title="d",
                summary="",
                member_entity_names=["OpenAI"],
                metadata={"doc_id": "d"},
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ]
    )


async def _draft(session, user, doc_ids=("d",)):
    c = Contribution(
        source_user_id=user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=uuid.uuid4(),
        title="t",
        doc_ids=list(doc_ids),
        status=ContributionStatus.DRAFT,
    )
    session.add(c)
    await session.flush()
    return c


async def test_collect_by_doc_ids(session):
    user = await _user(session)
    stores = _stores()
    await _seed_source(stores, user.id)
    c = await _draft(session, user)
    collected = await _svc.collect(c, stores=stores, access=_ctx(user.id))
    # 只收 doc_id=d 的 chunk（e#0 不收）
    assert {c.chunk_id for c in collected.chunks} == {"d#0", "d#1"}
    assert {e.name for e in collected.entities} == {"OpenAI"}
    assert len(collected.relations) == 1
    assert {c.community_id for c in collected.communities} == {"doc-d"}


async def test_collect_invisible_source_filtered(session):
    """C1/A：越权源库不收集（visible_to 过滤）。"""
    user = await _user(session)
    other = await _user(session, "other")
    stores = _stores()
    # other 的 personal chunk，user 看不到
    await stores.vector_store.upsert_chunks(
        [
            ChunkRecord(
                chunk_id="d#0",
                doc_id="d",
                content="c",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=other.id,
            ),
        ]
    )
    c = await _draft(session, user)
    collected = await _svc.collect(c, stores=stores, access=_ctx(user.id))
    assert collected.chunks == []
    assert collected.entities == []


async def test_build_manifest_and_diff(session):
    user = await _user(session)
    stores = _stores()
    await _seed_source(stores, user.id)
    c = await _draft(session, user)
    collected = await _svc.collect(c, stores=stores, access=_ctx(user.id))
    manifest = await _svc.build_manifest(
        session,
        c,
        collected=collected,
        target_overlap=1,
        user_id=user.id,
        source="api",
    )
    assert manifest["counts"]["chunks"] == 2
    assert manifest["counts"]["entities"] == 1
    assert manifest["counts"]["relations"] == 1
    assert manifest["counts"]["communities"] == 1
    assert manifest["overlap"] == 1
    assert c.manifest == manifest
    # 审计 push（manifest 写回记 push）
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "push"))).scalars().all()
    )
    assert any(log.resource_id == str(c.id) for log in logs)
    # diff 摘要
    diff = PushService.diff(c)
    assert diff == {
        "new_entities": 1,
        "new_relations": 1,
        "chunks": 2,
        "communities": 1,
        "conflicts": 1,
    }


def test_compute_overlap_name_type():
    """B4：compute_overlap 按 (name,type) 精确匹配，同名不同类型不计。"""
    src = [
        EntityRecord(name="A", type="organization", description=""),
        EntityRecord(name="B", type="person", description=""),
    ]
    tgt = [
        EntityRecord(name="A", type="organization", description=""),
        EntityRecord(name="B", type="organization", description=""),  # B 同名不同类型
    ]
    assert PushService.compute_overlap(src, tgt) == 1
