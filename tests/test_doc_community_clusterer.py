"""Task 7：独立文档嵌入聚类引擎。"""

import uuid

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.doc_community_clusterer import DocCommunityClusterer
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore


class _Chunk:
    def __init__(self, chunk_id, doc_id, content, owner_id):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.content = content
        self.access_level = ClearanceLevel.INTERNAL
        self.library_scope = LibraryScope.PERSONAL
        self.owner_id = owner_id
        self.project_id = None
        self.team_id = None


def _ctx(user_id):
    return AccessContext(user_id=user_id, username="u", clearance=ClearanceLevel.INTERNAL)


def _emb():
    return HashEmbeddingProvider(dimension=64)


async def test_cluster_all_connected_low_threshold():
    """阈值极低 -> 全连 -> 单社区含全部文档。"""
    uid = uuid.uuid4()
    clusterer = DocCommunityClusterer(_emb(), threshold=-2.0)
    chunks = [
        _Chunk("a#0", "a", "x", uid),
        _Chunk("b#0", "b", "y", uid),
        _Chunk("c#0", "c", "z", uid),
    ]
    records = await clusterer.derive(chunks, access=_ctx(uid))
    assert len(records) == 1
    assert set(records[0].member_entity_names) == {"a", "b", "c"}


async def test_cluster_all_separate_high_threshold():
    """阈值高于 1（cosine 上界）-> 全不连 -> 每文档一类。"""
    uid = uuid.uuid4()
    clusterer = DocCommunityClusterer(_emb(), threshold=2.0)
    chunks = [
        _Chunk("a#0", "a", "x", uid),
        _Chunk("b#0", "b", "y", uid),
        _Chunk("c#0", "c", "z", uid),
    ]
    records = await clusterer.derive(chunks, access=_ctx(uid))
    assert len(records) == 3
    assert all(len(r.member_entity_names) == 1 for r in records)


async def test_cluster_prefix_level_metadata():
    """docc- 前缀（不撞选项 A doc-）+ level=2 + metadata source/质量信号。"""
    uid = uuid.uuid4()
    store = InMemoryCommunityStore()
    clusterer = DocCommunityClusterer(_emb(), store, threshold=-2.0)
    chunks = [_Chunk("a#0", "a", "x", uid), _Chunk("b#0", "b", "y", uid)]
    records = await clusterer.derive(chunks, access=_ctx(uid))
    assert all(r.community_id.startswith("docc-") for r in records)
    assert not any(r.community_id.startswith("doc-") for r in records)  # 不撞选项 A
    assert all(r.level == 2 for r in records)
    assert all(r.metadata.get("source") == "doc_clustering" for r in records)
    # 写入 store
    stored = await store.list_communities(access=_ctx(uid))
    assert len(stored) == len(records)
    # 簇内最低相似度质量信号（B5）
    multi = [r for r in records if len(r.member_entity_names) > 1]
    assert all(r.metadata.get("min_intra_similarity") is not None for r in multi)


async def test_cluster_single_doc_returns_empty():
    uid = uuid.uuid4()
    clusterer = DocCommunityClusterer(_emb(), threshold=0.7)
    records = await clusterer.derive([_Chunk("a#0", "a", "x", uid)], access=_ctx(uid))
    assert records == []


async def test_cluster_no_chunks_returns_empty():
    clusterer = DocCommunityClusterer(_emb(), threshold=0.7)
    records = await clusterer.derive([], access=_ctx(uuid.uuid4()))
    assert records == []


async def test_cluster_aggregates_chunks_by_doc():
    """同 doc 的多 chunk 只取首 chunk 代表（不重复聚类）。"""
    uid = uuid.uuid4()
    clusterer = DocCommunityClusterer(_emb(), threshold=-2.0)
    chunks = [
        _Chunk("a#0", "a", "first", uid),
        _Chunk("a#1", "a", "second", uid),  # 同 doc
        _Chunk("b#0", "b", "y", uid),
    ]
    records = await clusterer.derive(chunks, access=_ctx(uid))
    assert len(records) == 1  # a, b 一类
    assert set(records[0].member_entity_names) == {"a", "b"}
