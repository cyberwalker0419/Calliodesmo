"""Task 6 Step 1：entity_alignment 契约测试（哈希嵌入桩，离线可测）。

验证三段式路由决策与候选对收集：
- 90% 相似（mid_cluster 各自 + name 重叠）-> review_pending（0.85-0.95 复核档）
- 97% 四级同名 -> auto_merge（>=0.95 自动合并档）
- 30% 相似 -> new（<0.85 新节点档）
- type blocking：同名同 type 才路由，type 不同降级 new
- compute_overlap_embedding：返回 source/target 对齐候选（含 score/type/desc）
（v1 直接用嵌入 provider 已有向量，不经 embedding 接口层再算一遍。）
"""

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.collab.entity_alignment import (
    compute_overlap_embedding,
    score_alignment,
)
from calliodesmo.interfaces.graph_store import EntityRecord


def _ent(name, type_, description="", **kw):
    base = dict(
        name=name,
        type=type_,
        description=description,
        source_chunk_ids=[],
        template_conforming=False,
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=None,
        project_id=None,
        team_id=None,
    )
    base.update(kw)
    return EntityRecord(**base)


DUMMY = object()


def _unit(axis: int, dim: int) -> list[float]:
    """第 axis 维单位向量（与其它轴余弦 0）。"""
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def _cos_at(axis: int, cos: float, dim: int) -> list[float]:
    """与第 axis 维单位向量余弦恰为 cos 的向量（二维平面旋转）。"""
    import math

    v = [0.0] * dim
    v[axis] = cos
    v[axis + 1] = math.sqrt(1 - cos * cos)
    return v


async def test_score_routes_review_band():
    """0.85-0.95 复核档：不同名但语义近似（向量余弦 0.90）。"""
    dim = 64
    src = _ent("OpenAI", "organization", description="领先的 AI 研究实验室")
    tgt = _ent("OpenAI Inc", "organization", description="领先的 AI 研究实验室")
    vectors = {src.name: _unit(0, dim), tgt.name: _cos_at(0, 0.90, dim)}
    result = await score_alignment(
        src, tgt, vectors=vectors, auto_merge_threshold=0.95, review_threshold=0.85
    )
    assert result.decision == "review_pending"
    assert 0.85 <= result.score < 0.95
    assert result.type_blocked is False


async def test_score_auto_merge_when_near_identical():
    """>=0.95 自动合并档：向量余弦 0.99。"""
    src = _ent("anthropic", "organization", description="AI 公司")
    tgt = _ent("Anthropic", "organization", description="AI 公司")
    vectors = {src.name: _unit(0, 64), tgt.name: _cos_at(0, 0.99, 64)}
    result = await score_alignment(
        src, tgt, vectors=vectors, auto_merge_threshold=0.95, review_threshold=0.85
    )
    assert result.decision == "auto_merged"
    assert result.score >= 0.95


async def test_score_new_below_threshold():
    """<0.85 新节点档：语义无关（向量余弦 0.3）。"""
    dim = 64
    src = _ent("OpenAI", "organization", description="AI 研究公司")
    tgt = _ent("Banana", "organization", description="热带水果")
    vectors = {src.name: _unit(0, dim), tgt.name: _cos_at(0, 0.3, dim)}
    result = await score_alignment(
        src, tgt, vectors=vectors, auto_merge_threshold=0.95, review_threshold=0.85
    )
    assert result.decision == "new"
    assert result.score < 0.85


async def test_type_blocking_downgrades_to_new():
    """type blocking：type 不同 -> type_blocked=True + decision='new'（v1 不合并）。"""
    v = [0.1, 0.2, 0.3, 0.4, 0.5]
    src = _ent("Apple", "fruit", description="红富士苹果")
    tgt = _ent("Apple", "organization", description="苹果公司")
    result = await score_alignment(
        src,
        tgt,
        vectors={src.name: v, tgt.name: v},
        auto_merge_threshold=0.95,
        review_threshold=0.85,
    )
    assert result.type_blocked is True
    assert result.decision == "new"


async def test_compute_overlap_embedding_collects_pairs():
    """候选对收集：同名同 type -> type_blocked 列表；语义相近 -> 候选对（含 score）。"""
    dim = 64
    source = [
        _ent("OpenAI", "organization", description="领先的 AI 研究实验室"),
        _ent("Apple", "fruit", description="红富士"),
    ]
    target = [
        _ent("OpenAI Inc", "organization", description="领先的 AI 研究实验室"),
        _ent("Apple", "organization", description="苹果公司"),
        _ent("Unrelated", "organization", description="xxx"),
    ]
    vectors = {
        "OpenAI": _unit(0, dim),  # 0.90 -> review_pending 候选
        "OpenAI Inc": _cos_at(0, 0.90, dim),
        "Apple": _unit(1, dim),  # 与任一 target 均 < 0.85
        "Unrelated": _unit(3, dim),
    }
    pairs, type_blocked = await compute_overlap_embedding(
        source, target, vectors=vectors, auto_merge_threshold=0.95, review_threshold=0.85
    )
    # Apple(fruit) vs Apple(organization)：type blocking -> type_blocked 列表
    assert [p.source_name for p in type_blocked] == ["Apple"]
    # OpenAI vs OpenAI Inc：0.85-0.95 复核档候选对
    assert len(pairs) == 1
    p = pairs[0]
    assert p.source_name == "OpenAI"
    assert p.target_name == "OpenAI Inc"
    assert p.type == "organization"
    assert 0.85 <= p.score < 0.95
