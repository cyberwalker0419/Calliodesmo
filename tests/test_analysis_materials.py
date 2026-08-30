"""材料采集器测试（P6 Task 9）：visible_to 红线 + 双闸截断 + 图谱复用 + 密级继承。

走真实 PG+pgvector（``PgVectorStore``）与 Neo4j（``Neo4jGraphStore``），两条安全
红线测试先行：

- **红线一**：``doc_ids`` 仅作成员筛选且逐条复核 ``visible_to``，不可见 ID 静默剔除
  （防枚举探测；禁止凭客户端传入 ID 直取材料）；
- **红线二**：材料获取不依赖内存态 ``sparse_index`` / BM25（跨进程为空，
  ``api/deps.py`` TODO 顺延 P9，2026-W49）——本测试只灌 PG 向量库、不建任何
  BM25 索引，且 monkeypatch BM25 方法触之即红。

密级继承纯函数 ``compute_report_access_level`` 无夹具可离线单测（CI 覆盖）。
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

pytest.importorskip("pgvector")  # CI 未装 persistence extra 时跳过收集
pytest.importorskip("neo4j")

from calliodesmo.analysis.access import compute_report_access_level
from calliodesmo.analysis.materials import (
    GRAPH_CONTEXT_CHUNK_ID,
    AnalysisMaterial,
    GatheredMaterials,
    fold_graph_context,
    format_graph_context,
    gather_materials,
)
from calliodesmo.analysis.schemas import (
    AnalysisEnvelope,
    AnalysisStatus,
    AnalysisType,
)
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.config import get_settings
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore
from calliodesmo.providers.pg_vector_store import PgVectorStore

_DIM = get_settings().embedding_dimension


def _v(*coords: float) -> list[float]:
    """构造 _DIM 维向量（前若干位填 coords，其余 0）。"""
    vec = [0.0] * _DIM
    for i, c in enumerate(coords):
        vec[i] = c
    return vec


def _ctx(user_id, *, clearance=ClearanceLevel.SECRET, project_ids=(), team_ids=()) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        project_ids=frozenset(project_ids),
        team_ids=frozenset(team_ids),
    )


def _chunk(
    chunk_id: str,
    owner,
    *,
    doc_id: str,
    content: str,
    access_level=ClearanceLevel.INTERNAL,
    scope=LibraryScope.PERSONAL,
    metadata=None,
    project_id=None,
    team_id=None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=content,
        vector=_v(1.0),
        metadata=metadata if metadata is not None else {},
        access_level=access_level,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
        project_id=project_id,
        team_id=team_id,
    )


def _ent(name, owner, *, chunks, access=ClearanceLevel.INTERNAL, scope=LibraryScope.PERSONAL):
    return EntityRecord(
        name=name,
        type="org",
        description=f"desc-{name}",
        source_chunk_ids=list(chunks),
        template_conforming=False,
        metadata={},
        access_level=access,
        library_scope=scope,
        owner_id=owner if scope == LibraryScope.PERSONAL else None,
    )


def _rel(src, tgt, owner, *, chunks, type="related"):
    return RelationRecord(
        source=src,
        target=tgt,
        type=type,
        description="",
        source_chunk_ids=list(chunks),
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
    )


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


@pytest.fixture
def vector_store(session, factory):
    """session 夹具先 TRUNCATE 清库，再建 PG 向量库。"""
    return PgVectorStore(factory)


@pytest.fixture
def graph_store(session, neo4j_session, factory):
    """session 夹具 TRUNCATE PG 镜像 + neo4j_session 夹具清图。"""
    return Neo4jGraphStore(neo4j_session, factory)


async def _make_user(factory, username="u") -> uuid.UUID:
    """建真实 User（documents.owner_id FK->users.id 须有真实行）。"""
    from calliodesmo.auth.models import User

    async with factory() as s:
        u = User(username=f"{username}-{uuid.uuid4().hex[:6]}", hashed_password="x")
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
        return uid


async def _seed_basic(vector_store, owner, other):
    """基础语料：alpha（4 块，含 10 以上序号）+ beta（SECRET）+ gamma（他人）+ 项目库块。"""
    project_id = uuid.uuid4()
    await vector_store.upsert_chunks(
        [
            _chunk(
                "alpha.md#0",
                owner,
                doc_id="alpha.md",
                content="阿尔法文档第一块：项目立项背景。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#1",
                owner,
                doc_id="alpha.md",
                content="阿尔法文档第二块：技术方案评审。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#2",
                owner,
                doc_id="alpha.md",
                content="阿尔法文档第三块：风险与应对。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#10",
                owner,
                doc_id="alpha.md",
                content="阿尔法文档第十块：结项总结。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "beta.md#0",
                owner,
                doc_id="beta.md",
                content="贝塔文档：高密级内容。",
                access_level=ClearanceLevel.SECRET,
                metadata={"source_path": "data/demo/beta.md"},
            ),
            _chunk(
                "gamma.md#0",
                other,
                doc_id="gamma.md",
                content="伽马文档：他人个人库内容。",
                metadata={"title": "Gamma 文档"},
            ),
            _chunk(
                "proj.md#0",
                None,
                doc_id="proj.md",
                content="项目库文档块。",
                scope=LibraryScope.PROJECT,
                project_id=project_id,
                metadata={},
            ),
        ]
    )
    return project_id


# ---------------------------------------------------------------------------
# 全量拉取 + visible_to 过滤
# ---------------------------------------------------------------------------


async def test_full_gather_visibility_filter(vector_store):
    """doc_ids=None 全可见范围：他人个人库 / 超密级 / 未授权项目库一律不可见。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    project_id = await _seed_basic(vector_store, owner, other)

    # clearance=INTERNAL：beta（SECRET）不可见；项目库未授权不可见
    got = await gather_materials(
        vector_store=vector_store, access=_ctx(owner, clearance=ClearanceLevel.INTERNAL)
    )
    ids = {m.chunk_id for m in got.materials}
    assert ids == {"alpha.md#0", "alpha.md#1", "alpha.md#2", "alpha.md#10"}
    assert "gamma.md#0" not in ids  # 他人个人库
    assert "beta.md#0" not in ids  # 超密级

    # clearance=SECRET 且授权项目：beta 与项目库块可见
    got2 = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner, clearance=ClearanceLevel.SECRET, project_ids=[project_id]),
    )
    ids2 = {m.chunk_id for m in got2.materials}
    assert "beta.md#0" in ids2
    assert "proj.md#0" in ids2
    assert "gamma.md#0" not in ids2  # 他人个人库仍不可见


# ---------------------------------------------------------------------------
# 红线一：doc_ids 仅作成员筛选 + 逐条复核可见性，不可见 ID 静默剔除
# ---------------------------------------------------------------------------


async def test_redline_one_doc_ids_membership_only_silent_drop(vector_store):
    """提交含不可见 / 不存在 doc_id：静默剔除，不报错、不泄漏存在性。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner),
        doc_ids=["alpha.md", "gamma.md", "ghost.md"],  # gamma 他人、ghost 不存在
    )
    ids = {m.chunk_id for m in got.materials}
    assert ids == {"alpha.md#0", "alpha.md#1", "alpha.md#2", "alpha.md#10"}
    # 静默剔除：结果中无越权痕迹，也不抛错
    assert all(m.doc_id == "alpha.md" for m in got.materials)


async def test_redline_one_low_clearance_doc_ids_silent_empty(vector_store):
    """低密级提交高密文档（枚举探测面）：静默返回空，不暴露存在性。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner, clearance=ClearanceLevel.INTERNAL),
        doc_ids=["beta.md"],  # SECRET，超密级
    )
    assert got.materials == ()

    got2 = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner),
        doc_ids=["gamma.md"],  # 他人个人库
    )
    assert got2.materials == ()


async def test_redline_one_no_direct_chunk_id_fetch(vector_store):
    """禁止凭客户端 ID 直取材料：``get_chunks_by_ids`` 触之即红，采集仍成功。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    def _boom(chunk_ids):
        raise AssertionError("红线一：不得凭客户端传入的 chunk_id / doc_id 直取材料")

    vector_store.get_chunks_by_ids = _boom  # 触之即红
    got = await gather_materials(
        vector_store=vector_store, access=_ctx(owner), doc_ids=["alpha.md"]
    )
    assert len(got.materials) == 4


# ---------------------------------------------------------------------------
# 红线二：不依赖内存态 sparse_index / BM25
# ---------------------------------------------------------------------------


async def test_redline_two_no_bm25_dependency(vector_store, monkeypatch):
    """只灌 PG 向量库、不建任何 BM25 索引，采集仍全量命中；BM25 方法触之即红。"""
    from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

    def _boom(*args, **kwargs):
        raise AssertionError("红线二：材料获取不得依赖内存态 sparse_index / BM25")

    monkeypatch.setattr(InMemoryBM25Index, "index", _boom)
    monkeypatch.setattr(InMemoryBM25Index, "search", _boom)

    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner, clearance=ClearanceLevel.INTERNAL),
    )
    assert len(got.materials) == 4  # 跨进程内存 BM25 为空的场景下仍采集到材料


# ---------------------------------------------------------------------------
# 双闸截断（analysis_max_chunks + analysis_max_input_chars）
# ---------------------------------------------------------------------------


async def test_chunk_gate_truncation(vector_store):
    """块数闸：按排序取前 max_chunks 条，truncated=True。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(
        vector_store=vector_store, access=_ctx(owner), max_chunks=2, max_input_chars=100000
    )
    assert [m.chunk_id for m in got.materials] == ["alpha.md#0", "alpha.md#1"]
    assert got.truncated is True
    assert set(got.source_texts) == {"alpha.md#0", "alpha.md#1"}


async def test_char_gate_truncation(vector_store):
    """字符闸：整块累计不超预算；首块单独超预算时裁剪首块文本。"""
    owner = await _make_user(vector_store._session_factory)
    await vector_store.upsert_chunks(
        [
            _chunk("long.md#0", owner, doc_id="long.md", content="甲" * 100, metadata={}),
            _chunk("long.md#1", owner, doc_id="long.md", content="乙" * 100, metadata={}),
            _chunk("long.md#2", owner, doc_id="long.md", content="丙" * 100, metadata={}),
        ]
    )

    # 预算 250：前两块 200 字纳入，第三块累计 300 超限被丢
    got = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner),
        max_chunks=40,
        max_input_chars=250,
    )
    assert [m.chunk_id for m in got.materials] == ["long.md#0", "long.md#1"]
    assert got.truncated is True

    # 首块单独超预算：裁剪首块文本至预算（不产出空材料）
    got2 = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner),
        max_chunks=40,
        max_input_chars=60,
    )
    assert [m.chunk_id for m in got2.materials] == ["long.md#0"]
    assert got2.materials[0].text == "甲" * 60
    assert got2.source_texts["long.md#0"] == "甲" * 60
    assert got2.truncated is True


async def test_no_truncation_flag_false(vector_store):
    """未触发任一闸：truncated=False。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(vector_store=vector_store, access=_ctx(owner))
    assert got.truncated is False


# ---------------------------------------------------------------------------
# chunk_id → 源文映射（供证据校验）与材料字段
# ---------------------------------------------------------------------------


async def test_source_text_mapping_feeds_evidence_verify(vector_store):
    """映射与材料文本一致，且可被 ``verify_evidence`` 消费（引文子串校验通过）。"""
    owner = await _make_user(vector_store._session_factory)
    await vector_store.upsert_chunks(
        [
            _chunk(
                "doc.md#0",
                owner,
                doc_id="doc.md",
                content="证据校验原文：合同于二月签署。",
                metadata={"title": "合同"},
            )
        ]
    )
    got = await gather_materials(vector_store=vector_store, access=_ctx(owner))
    assert got.source_texts == {"doc.md#0": "证据校验原文：合同于二月签署。"}

    from calliodesmo.analysis.evidence import verify_evidence

    envelope = AnalysisEnvelope(
        task_type=AnalysisType.SUMMARY,
        status=AnalysisStatus.OK,
        generated_at=datetime.now(UTC),
        model="test/stub",
        prompt_version="summary.v1",
        usage={},
        warnings=[],
        source_chunk_ids=["doc.md#0"],
        payload={
            "summary": "合同二月签署。",
            "key_points": [],
            "confidence": 1.0,
            "evidence": [{"chunk_id": "doc.md#0", "quote": "合同于二月签署", "confidence": 1.0}],
        },
    )
    verified = verify_evidence(envelope, got.source_texts)
    assert verified.warnings == []  # 引文为源文子串 -> 无失配告警


async def test_material_fields_and_source_label(vector_store):
    """材料携带 access 三字段；source_label 取 metadata title -> source_path -> doc_id。"""
    owner = await _make_user(vector_store._session_factory)
    await vector_store.upsert_chunks(
        [
            _chunk("t.md#0", owner, doc_id="t.md", content="a", metadata={"title": "标题甲"}),
            _chunk(
                "s.md#0",
                owner,
                doc_id="s.md",
                content="b",
                metadata={"source_path": "data/demo/s.md"},
            ),
            _chunk("n.md#0", owner, doc_id="n.md", content="c", metadata={}),
            _chunk(
                "hi.md#0",
                owner,
                doc_id="hi.md",
                content="d",
                access_level=ClearanceLevel.SECRET,
                metadata={},
            ),
        ]
    )
    got = await gather_materials(vector_store=vector_store, access=_ctx(owner))
    by_id = {m.chunk_id: m for m in got.materials}
    assert by_id["t.md#0"].source_label == "标题甲"
    assert by_id["s.md#0"].source_label == "data/demo/s.md"
    assert by_id["n.md#0"].source_label == "n.md"
    # access 字段随材料携带（密级继承计算的输入）
    assert by_id["hi.md#0"].access_level == ClearanceLevel.SECRET
    assert by_id["t.md#0"].access_level == ClearanceLevel.INTERNAL
    assert by_id["t.md#0"].library_scope == LibraryScope.PERSONAL
    assert by_id["t.md#0"].owner_id == owner


# ---------------------------------------------------------------------------
# 排序：按文档序（提交序）/ 块序（序号数值序）
# ---------------------------------------------------------------------------


async def test_sort_doc_order_and_numeric_ordinal(vector_store):
    """doc_ids 提交序定文档先后；块序按 # 后序号数值排（#2 先于 #10）。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got = await gather_materials(
        vector_store=vector_store,
        access=_ctx(owner),
        doc_ids=["beta.md", "alpha.md"],
    )
    assert [m.chunk_id for m in got.materials] == [
        "beta.md#0",
        "alpha.md#0",
        "alpha.md#1",
        "alpha.md#2",
        "alpha.md#10",  # 数值序：2 之后是 10，而非字典序的 #10 先于 #2
    ]

    # 未指定 doc_ids：按 doc_id 字典序定文档先后
    got2 = await gather_materials(vector_store=vector_store, access=_ctx(owner))
    assert [m.chunk_id for m in got2.materials][:4] == [
        "alpha.md#0",
        "alpha.md#1",
        "alpha.md#2",
        "alpha.md#10",
    ]


async def test_empty_doc_ids_means_full_visible_scope(vector_store):
    """doc_ids 空列表与 None 同义（全可见范围；API 默认空列表不变成零材料）。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)

    got_none = await gather_materials(vector_store=vector_store, access=_ctx(owner))
    got_empty = await gather_materials(vector_store=vector_store, access=_ctx(owner), doc_ids=[])
    assert [m.chunk_id for m in got_empty.materials] == [m.chunk_id for m in got_none.materials]
    assert len(got_empty.materials) == 5  # SECRET 可见：alpha 4 块 + beta 1 块


# ---------------------------------------------------------------------------
# 图谱复用：实体 / 关系类附带图谱上下文（经 visible_to，不重新抽取）
# ---------------------------------------------------------------------------


async def test_graph_context_for_entity_types(vector_store, graph_store):
    """实体识别 / 关系映射附带相关实体与关系；其余类型不读图。"""
    owner = await _make_user(vector_store._session_factory)
    other = await _make_user(vector_store._session_factory, "other")
    await _seed_basic(vector_store, owner, other)
    await graph_store.upsert_graph(
        [
            _ent("立项委员会", owner, chunks=["alpha.md#0"]),  # 相关且可见
            _ent("外部机构", other, chunks=["alpha.md#0"]),  # 他人个人库 -> 不可见
            _ent(
                "密级实体",
                owner,
                chunks=["alpha.md#1"],
                access=ClearanceLevel.SECRET,
            ),  # 超密级（ctx INTERNAL）-> 不可见
            _ent("无关实体", owner, chunks=["omega.md#0"]),  # 可见但与材料无关 -> 剔除
        ],
        [
            _rel("立项委员会", "无关实体", owner, chunks=["alpha.md#0"]),  # 源块命中 -> 纳入
            _rel("外部机构", "立项委员会", other, chunks=["alpha.md#0"]),  # 他人 -> 不可见
        ],
    )

    got = await gather_materials(
        vector_store=vector_store,
        graph_store=graph_store,
        access=_ctx(owner, clearance=ClearanceLevel.INTERNAL),
        task_type=AnalysisType.ENTITY_RECOGNITION,
        doc_ids=["alpha.md"],
    )
    assert [e.name for e in got.entities] == ["立项委员会"]  # 仅相关且可见
    assert [(r.source, r.target) for r in got.relations] == [("立项委员会", "无关实体")]
    # 图谱数据原样复用（不重新抽取）：字段内容与入库一致
    assert got.entities[0].description == "desc-立项委员会"

    # 关系映射同样读图
    got2 = await gather_materials(
        vector_store=vector_store,
        graph_store=graph_store,
        access=_ctx(owner, clearance=ClearanceLevel.INTERNAL),
        task_type=AnalysisType.RELATION_MAPPING,
        doc_ids=["alpha.md"],
    )
    assert [e.name for e in got2.entities] == ["立项委员会"]

    # 其余类型（摘要）不读图
    got3 = await gather_materials(
        vector_store=vector_store,
        graph_store=graph_store,
        access=_ctx(owner),
        task_type=AnalysisType.SUMMARY,
        doc_ids=["alpha.md"],
    )
    assert got3.entities == ()
    assert got3.relations == ()


async def test_graph_context_requires_material_overlap(vector_store, graph_store):
    """图谱上下文与最终材料块相交才纳入（截断后被裁掉的块不带出图谱数据）。"""
    owner = await _make_user(vector_store._session_factory)
    await vector_store.upsert_chunks(
        [
            _chunk("g.md#0", owner, doc_id="g.md", content="第一块", metadata={}),
            _chunk("g.md#1", owner, doc_id="g.md", content="第二块", metadata={}),
        ]
    )
    await graph_store.upsert_graph(
        [
            _ent("首块实体", owner, chunks=["g.md#0"]),
            _ent("次块实体", owner, chunks=["g.md#1"]),
        ],
        [],
    )

    got = await gather_materials(
        vector_store=vector_store,
        graph_store=graph_store,
        access=_ctx(owner),
        task_type=AnalysisType.ENTITY_RECOGNITION,
        max_chunks=1,  # 只留第一块
    )
    assert [m.chunk_id for m in got.materials] == ["g.md#0"]
    assert [e.name for e in got.entities] == ["首块实体"]


# ---------------------------------------------------------------------------
# compute_report_access_level：max(材料各级, INTERNAL) 纯函数（无夹具，CI 覆盖）
# ---------------------------------------------------------------------------


def _mat(access_level: ClearanceLevel) -> AnalysisMaterial:
    return AnalysisMaterial(
        chunk_id="c#0",
        doc_id="c",
        source_label="c",
        text="t",
        access_level=access_level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=None,
    )


def test_compute_report_access_level_boundaries():
    """全 public 材料 -> INTERNAL（下限）；含 secret -> SECRET；空材料 -> INTERNAL。"""
    assert (
        compute_report_access_level([_mat(ClearanceLevel.PUBLIC), _mat(ClearanceLevel.PUBLIC)])
        == ClearanceLevel.INTERNAL
    )
    assert (
        compute_report_access_level([_mat(ClearanceLevel.PUBLIC), _mat(ClearanceLevel.SECRET)])
        == ClearanceLevel.SECRET
    )
    assert (
        compute_report_access_level(
            [_mat(ClearanceLevel.INTERNAL), _mat(ClearanceLevel.CONFIDENTIAL)]
        )
        == ClearanceLevel.CONFIDENTIAL
    )
    assert compute_report_access_level([]) == ClearanceLevel.INTERNAL


def test_compute_report_access_level_accepts_raw_levels():
    """鸭子类型：直接接收 ClearanceLevel 序列亦可。"""
    assert (
        compute_report_access_level([ClearanceLevel.PUBLIC, ClearanceLevel.CONFIDENTIAL])
        == ClearanceLevel.CONFIDENTIAL
    )


# ---------------------------------------------------------------------------
# fold_graph_context：图谱上下文折入材料（纯函数，worker / 评估侧折后进引擎）
# ---------------------------------------------------------------------------


def _gathered(entities=(), relations=(), materials=None) -> GatheredMaterials:
    """构造 GatheredMaterials（折入纯函数用例用；材料默认一条）。"""
    mats = materials if materials is not None else (_mat(ClearanceLevel.INTERNAL),)
    return GatheredMaterials(
        materials=tuple(mats),
        source_texts={m.chunk_id: m.text for m in mats},
        entities=tuple(entities),
        relations=tuple(relations),
        truncated=False,
    )


def _fold_ent(name="立项委员会", access=ClearanceLevel.INTERNAL) -> EntityRecord:
    return EntityRecord(
        name=name,
        type="org",
        description=f"desc-{name}",
        source_chunk_ids=["c#0"],
        access_level=access,
    )


def _fold_rel(src="立项委员会", tgt="合作机构", access=ClearanceLevel.INTERNAL) -> RelationRecord:
    return RelationRecord(
        source=src,
        target=tgt,
        type="related",
        description=f"{src} 与 {tgt} 合作",
        source_chunk_ids=["c#0"],
        access_level=access,
    )


def test_fold_graph_context_noop_without_graph_data():
    """无实体 / 关系：原样返回材料（非图谱类与图空场景不加伪块）。"""
    gathered = _gathered()
    assert fold_graph_context(gathered) == gathered.materials


def test_fold_graph_context_appends_pseudo_material():
    """有图谱上下文：末尾追加伪材料块，实体 / 关系数据序列化入文。"""
    gathered = _gathered(entities=[_fold_ent()], relations=[_fold_rel()])
    folded = fold_graph_context(gathered)
    assert [m.chunk_id for m in folded] == ["c#0", GRAPH_CONTEXT_CHUNK_ID]
    pseudo = folded[-1]
    assert "立项委员会" in pseudo.text  # 实体名入文
    assert "合作机构" in pseudo.text  # 关系尾实体入文
    assert "related" in pseudo.text  # 关系类型入文
    # 真实材料块不变（伪块仅追加）
    assert folded[0] == gathered.materials[0]


def test_fold_graph_context_access_level_is_max_of_graph_data():
    """伪块 access_level 取实体 / 关系各级最大值（保守方向）。"""
    gathered = _gathered(
        entities=[_fold_ent(access=ClearanceLevel.INTERNAL)],
        relations=[_fold_rel(access=ClearanceLevel.SECRET)],
    )
    folded = fold_graph_context(gathered)
    assert folded[-1].access_level == ClearanceLevel.SECRET


def test_fold_graph_context_entities_only_and_relations_only():
    """仅实体或仅关系亦可折入（对应段缺省时不渲染空段）。"""
    ent_only = fold_graph_context(_gathered(entities=[_fold_ent()]))
    assert ent_only[-1].chunk_id == GRAPH_CONTEXT_CHUNK_ID
    assert "立项委员会" in ent_only[-1].text
    rel_only = fold_graph_context(_gathered(relations=[_fold_rel()]))
    assert rel_only[-1].chunk_id == GRAPH_CONTEXT_CHUNK_ID
    assert "合作机构" in rel_only[-1].text


def test_format_graph_context_deterministic_and_skips_blank_fields():
    """序列化确定性：段落标记固定；空类型 / 空描述不渲染多余分隔符。"""
    ent = EntityRecord(name="甲", type=None, description="", source_chunk_ids=["c#0"])
    rel = RelationRecord(
        source="甲", target="乙", type="", description="", source_chunk_ids=["c#0"]
    )
    text = format_graph_context([ent], [rel])
    assert text == ("【图谱上下文 · 实体】\n- 实体：甲\n【图谱上下文 · 关系】\n- 关系：甲 -> 乙")


def test_format_graph_context_renders_type_and_description():
    """非空类型 / 描述以「 | 」分隔渲染（字段内容原样复用，不重新抽取）。"""
    text = format_graph_context([_fold_ent()], [_fold_rel()])
    assert "- 实体：立项委员会 | 类型：org | 描述：desc-立项委员会" in text
    assert (
        "- 关系：立项委员会 -> 合作机构 | 类型：related | 描述：立项委员会 与 合作机构 合作" in text
    )
