"""Task 6 Step 2：PushService 对齐候选（alignment_pending）接入 manifest/diff。

- ``compute_alignment_pending``：源/目标实体向量余弦三段式 -> 复核档候选（JSON-safe）
- ``build_manifest`` 可选存 ``manifest["alignment_pending"]``（不入则不带键，旧调用不变）
- ``diff`` 返回 ``alignment_pending`` 列表
"""

import types
import uuid

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.collab.models import Contribution
from calliodesmo.collab.push import PushService
from calliodesmo.interfaces.embedding import EmbeddingResult
from calliodesmo.interfaces.graph_store import EntityRecord

_settings = types.SimpleNamespace(
    alignment_auto_merge_threshold=0.95, alignment_review_threshold=0.85
)


def _unit(axis: int, dim: int) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def _cos_at(axis: int, cos: float, dim: int) -> list[float]:
    import math

    v = [0.0] * dim
    v[axis] = cos
    v[axis + 1] = math.sqrt(1 - cos * cos)
    return v


class _VecEmbed:
    """同名向量桩：按实体名返回预设向量（哈希嵌入同构，离线可测）。

    实现侧按 ``name: desc`` 文本批量嵌入，桩按 name 前缀解析回查。
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @property
    def dimension(self) -> int:
        return 64

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        out = []
        for t in texts:
            key = t.split(": ", 1)[0] if ": " in t else t
            out.append(self._vectors[key])
        return EmbeddingResult(vectors=out, model="test", dimension=64)


def _ent(name, type_, description=""):
    return EntityRecord(
        name=name,
        type=type_,
        description=description,
        source_chunk_ids=[],
        template_conforming=False,
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=uuid.uuid4(),
    )


async def test_compute_alignment_pending_review_band():
    """源/目标重叠 -> 仅复核档（< auto_merge）进待审；type_blocked 不进。"""
    src = [
        _ent("OpenAI", "organization", "AI 研究"),
        _ent("Apple", "fruit", "红富士"),
    ]
    tgt = [
        _ent("OpenAI Inc", "organization", "AI 研究"),
        _ent("Apple", "organization", "苹果公司"),
    ]
    emb = _VecEmbed(
        {
            "OpenAI": _unit(0, 64),  # 0.90 -> review_pending
            "OpenAI Inc": _cos_at(0, 0.90, 64),
            "Apple": _unit(1, 64),
        }
    )
    pending = await PushService.compute_alignment_pending(
        src, tgt, embedding=emb, settings=_settings
    )
    assert len(pending) == 1
    p = pending[0]
    assert p["source_name"] == "OpenAI"
    assert p["target_name"] == "OpenAI Inc"
    assert p["score"] < 0.95
    assert "pair_id" in p
    assert p["source_description"] == "AI 研究"


async def test_build_manifest_stores_alignment_pending(session):
    """build_manifest 传入 alignment_pending -> manifest 落键；diff 返回。"""
    real_user = await _User(session)
    real_team = await _Team(session)
    real_project = await _Project(session, real_team.id)
    c = Contribution(
        source_user_id=real_user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=real_project.id,
        title="t",
        doc_ids=["d"],
    )
    session.add(c)
    await session.flush()
    pending = [
        {
            "pair_id": "abc",
            "source_name": "OpenAI",
            "target_name": "OpenAI Inc",
            "score": 0.9,
            "type": "organization",
            "source_type": "organization",
            "target_type": "organization",
            "source_description": "AI 研究",
            "target_description": "AI 研究",
        }
    ]
    _push = PushService()
    manifest = await _push.build_manifest(
        session,
        c,
        collected=_Collected(),
        target_overlap=1,
        user_id=real_user.id,
        source="api",
        alignment_pending=pending,
    )
    assert manifest["alignment_pending"] == pending
    diff = PushService.diff(c)
    assert diff["alignment_pending"] == pending


async def test_build_manifest_without_alignment(session):
    """不传 alignment_pending -> manifest 不带键，diff 返回空列表（旧调用不变）。"""
    real_user = await _User(session)
    real_team = await _Team(session)
    real_project = await _Project(session, real_team.id)
    c = Contribution(
        source_user_id=real_user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=real_project.id,
        title="t",
        doc_ids=["d"],
    )
    session.add(c)
    await session.flush()
    _push = PushService()
    manifest = await _push.build_manifest(
        session,
        c,
        collected=_Collected(),
        target_overlap=0,
        user_id=real_user.id,
        source="api",
    )
    assert "alignment_pending" not in manifest
    assert PushService.diff(c)["alignment_pending"] == []


# ---- 可复用夹具（本文件内建）----


async def _User(session):
    from calliodesmo.auth.models import User

    u = User(username=f"u-{uuid.uuid4().hex[:8]}", hashed_password="x")
    session.add(u)
    await session.flush()
    return u


async def _Team(session):
    from calliodesmo.auth.models import Team

    t = Team(name=f"team-{uuid.uuid4().hex[:8]}")
    session.add(t)
    await session.flush()
    return t


async def _Project(session, team_id):
    from calliodesmo.auth.models import Project

    p = Project(name=f"proj-{uuid.uuid4().hex[:8]}", team_id=team_id)
    session.add(p)
    await session.flush()
    return p


class _Collected:
    """空收集占位（本组用例不关心计数）。"""

    chunks: list = []  # noqa: RUF012
    entities: list = []  # noqa: RUF012
    relations: list = []  # noqa: RUF012
    communities: list = []  # noqa: RUF012
