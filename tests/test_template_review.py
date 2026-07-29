"""Task 6：抽取模板 review-gated 沉淀（收集/批准/写回）。"""

import types
import uuid

import pytest

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.collab.template_review import (
    TemplateReviewService,
    collect_discovered_types,
)
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
from calliodesmo.interfaces.graph_store import EntityRecord
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore


def _ctx(user_id=None) -> AccessContext:
    return AccessContext(
        user_id=user_id or uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset({Permission.APPROVE}),
    )


def _stores():
    return types.SimpleNamespace(graph_store=InMemoryGraphStore())


async def test_collect_discovered_types():
    """收集 template_conforming=False 的 type，去重+计数；conforming/空类型过滤。"""
    stores = _stores()
    uid = uuid.uuid4()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="A",
                type="company",
                description="",
                template_conforming=False,
                library_scope=LibraryScope.PERSONAL,
                owner_id=uid,
            ),
            EntityRecord(
                name="B",
                type="company",
                description="",
                template_conforming=False,
                library_scope=LibraryScope.PERSONAL,
                owner_id=uid,
            ),
            EntityRecord(  # conforming=True 不收集
                name="C",
                type="person",
                description="",
                template_conforming=True,
                library_scope=LibraryScope.PERSONAL,
                owner_id=uid,
            ),
            EntityRecord(  # 空类型过滤
                name="D",
                type=None,
                description="",
                template_conforming=False,
                library_scope=LibraryScope.PERSONAL,
                owner_id=uid,
            ),
        ],
        [],
    )
    items = await collect_discovered_types(stores, access=_ctx(uid))
    assert {it["type"] for it in items} == {"company"}
    assert next(it for it in items if it["type"] == "company")["count"] == 2
    assert all(it["status"] == "pending" for it in items)


def test_sediment_appends_and_writes_yaml(tmp_path):
    """sediment 追加 preferred 去重保序 + 写回 YAML + 幂等。"""
    yaml_path = tmp_path / "templates.yaml"
    yaml_path.write_text(
        "templates:\n"
        "  - team: team-a\n"
        "    preferred_entity_types: [person]\n"
        "    type_descriptions: {}\n"
        "    relation_types: []\n"
        "    instructions: ''\n",
        encoding="utf-8",
    )
    registry = ExtractionTemplateRegistry.from_yaml(yaml_path)
    registry.sediment("team-a", ["company", "person"], path=yaml_path)  # person 去重
    assert registry.get("team-a").preferred_entity_types == ["person", "company"]
    # 写回 YAML，重读确认
    registry2 = ExtractionTemplateRegistry.from_yaml(yaml_path)
    assert registry2.get("team-a").preferred_entity_types == ["person", "company"]
    # 幂等：重复批准同类型不重复追加
    registry.sediment("team-a", ["company"], path=yaml_path)
    assert registry.get("team-a").preferred_entity_types == ["person", "company"]


def test_sediment_new_team():
    """团队无模板则新建条目。"""
    registry = ExtractionTemplateRegistry()
    tmpl = registry.sediment("team-new", ["foo"])
    assert tmpl.preferred_entity_types == ["foo"]
    assert "team-new" in registry


def test_sediment_write_failure_friendly(tmp_path):
    """写回失败（目录不存在）抛 RuntimeError 不崩溃。"""
    registry = ExtractionTemplateRegistry.from_yaml(None)
    bad_path = tmp_path / "nonexistent" / "templates.yaml"  # 目录不存在
    with pytest.raises(RuntimeError, match="模板写回失败"):
        registry.sediment("team-a", ["x"], path=str(bad_path))


async def test_approve_writes_back(tmp_path):
    """TemplateReviewService.approve -> sediment 写回。"""
    yaml_path = tmp_path / "templates.yaml"
    yaml_path.write_text(
        "templates:\n  - team: team-a\n    preferred_entity_types: []\n", encoding="utf-8"
    )
    registry = ExtractionTemplateRegistry.from_yaml(yaml_path)
    svc = TemplateReviewService(registry=registry)
    stores = _stores()
    result = await svc.approve(
        stores,
        team="team-a",
        approved_type="company",
        access=_ctx(),
        path=str(yaml_path),
    )
    assert result == {"team": "team-a", "type": "company", "status": "approved"}
    assert "company" in registry.get("team-a").preferred_entity_types
