"""Task 4：图谱合并纯函数（实体去重/关系并集/来源打标）。"""

import uuid

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.collab.graph_merge import merge_entities, merge_relations
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord

_PROV = {"contribution_id": "c1", "source_user_id": "u1"}


def _ent(name, type_, **kw):
    base = dict(
        name=name,
        type=type_,
        description="",
        source_chunk_ids=[],
        template_conforming=False,
        metadata={},
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=uuid.uuid4(),
    )
    base.update(kw)
    return EntityRecord(**base)


def test_merge_new_entity_marked_new():
    src = [_ent("OpenAI", "organization", source_chunk_ids=["d#0"])]
    merged = merge_entities(
        src,
        target_entities=[],
        target_scope=LibraryScope.PROJECT,
        target_project_id=uuid.uuid4(),
        target_team_id=None,
        provenance=_PROV,
    )
    assert len(merged) == 1
    e = merged[0]
    assert e.metadata["merge_decision"] == "new"
    assert e.metadata["provenance"] == _PROV
    assert e.library_scope == LibraryScope.PROJECT
    assert e.owner_id is None  # project 共享库无个人 owner


def test_merge_existing_entity_merges_chunks_and_access():
    pid = uuid.uuid4()
    target = [
        _ent(
            "OpenAI",
            "organization",
            source_chunk_ids=["t#0"],
            description="原描述",
            access_level=ClearanceLevel.INTERNAL,
            template_conforming=True,
        )
    ]
    src = [
        _ent(
            "OpenAI",
            "organization",
            source_chunk_ids=["d#0", "t#0"],  # 含重复
            description="新描述",
            access_level=ClearanceLevel.CONFIDENTIAL,  # 更严
            template_conforming=False,
        )
    ]
    merged = merge_entities(
        src,
        target_entities=target,
        target_scope=LibraryScope.PROJECT,
        target_project_id=pid,
        target_team_id=None,
        provenance=_PROV,
    )
    assert len(merged) == 1  # 去重
    e = merged[0]
    assert e.metadata["merge_decision"] == "exact_name_type"
    assert e.source_chunk_ids == ["t#0", "d#0"]  # 去重保序
    assert "原描述" in e.description and "新描述" in e.description
    assert e.access_level == ClearanceLevel.CONFIDENTIAL  # 取较严
    assert e.template_conforming is True  # 取或
    assert e.project_id == pid


def test_merge_same_name_diff_type_marked_conflict():
    """B4：同名不同类型标 same_name_diff_type（v1 仍合并，留 v2 embedding 解决）。"""
    target = [_ent("Apple", "organization")]
    src = [_ent("Apple", "fruit")]
    merged = merge_entities(
        src,
        target_entities=target,
        target_scope=LibraryScope.TEAM,
        target_project_id=None,
        target_team_id=uuid.uuid4(),
        provenance=_PROV,
    )
    assert len(merged) == 1
    assert merged[0].metadata["merge_decision"] == "same_name_diff_type"


def test_merge_relations_union_dedup():
    pid = uuid.uuid4()
    target = [
        RelationRecord(
            source="A",
            target="B",
            type="rel",
            description="",
            source_chunk_ids=["t#0"],
            library_scope=LibraryScope.PROJECT,
            project_id=pid,
        )
    ]
    src = [
        RelationRecord(
            source="A",
            target="B",
            type="rel",
            description="",
            source_chunk_ids=["d#0", "t#0"],
            library_scope=LibraryScope.PERSONAL,
        ),
        RelationRecord(
            source="B",
            target="C",
            type="rel",
            description="",
            source_chunk_ids=["d#1"],
            library_scope=LibraryScope.PERSONAL,
        ),
    ]
    merged = merge_relations(
        src,
        target_relations=target,
        target_scope=LibraryScope.PROJECT,
        target_project_id=pid,
        target_team_id=None,
        provenance=_PROV,
    )
    assert len(merged) == 2  # (A,B,rel) 去重 + (B,C,rel) 新增
    ab = next(r for r in merged if (r.source, r.target, r.type) == ("A", "B", "rel"))
    assert ab.source_chunk_ids == ["t#0", "d#0"]  # 去重保序
    assert ab.metadata["merge_decision"] == "exact_name_type"
    bc = next(r for r in merged if (r.source, r.target, r.type) == ("B", "C", "rel"))
    assert bc.metadata["merge_decision"] == "new"
    assert bc.library_scope == LibraryScope.PROJECT
