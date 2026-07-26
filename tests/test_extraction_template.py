"""Task 2 Step 3：ExtractionTemplateRegistry 测试。"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry


def _write_yaml(tmp_path, text):
    f = tmp_path / "templates.yaml"
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_load_single_team(tmp_path):
    path = _write_yaml(
        tmp_path,
        "templates:\n"
        "  - team: team-a\n"
        "    preferred_entity_types: [person, org]\n"
        "    type_descriptions: {person: someone}\n"
        "    relation_types: [works_for]\n"
        "    instructions: focus on people\n",
    )
    reg = ExtractionTemplateRegistry.from_yaml(path)
    t = reg.get("team-a")
    assert t is not None
    assert t.team == "team-a"
    assert t.preferred_entity_types == ["person", "org"]
    assert t.type_descriptions == {"person": "someone"}
    assert t.relation_types == ["works_for"]
    assert t.instructions == "focus on people"


def test_duplicate_team_raises(tmp_path):
    path = _write_yaml(
        tmp_path,
        "templates:\n"
        "  - team: team-a\n"
        "    preferred_entity_types: [person]\n"
        "  - team: team-a\n"
        "    preferred_entity_types: [org]\n",
    )
    import pytest

    with pytest.raises(ValueError, match="团队模板重复"):
        ExtractionTemplateRegistry.from_yaml(path)


def test_missing_file_empty_registry():
    reg = ExtractionTemplateRegistry.from_yaml("nope/missing.yaml")
    assert len(reg) == 0


def test_empty_file_empty_registry(tmp_path):
    path = _write_yaml(tmp_path, "")
    reg = ExtractionTemplateRegistry.from_yaml(path)
    assert len(reg) == 0


def test_get_for_access_by_team_id(tmp_path):
    team = uuid.uuid4()
    path = _write_yaml(
        tmp_path,
        f"templates:\n  - team: {team}\n    preferred_entity_types: [person]\n",
    )
    reg = ExtractionTemplateRegistry.from_yaml(path)
    access = AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        team_ids=frozenset({team}),
    )
    t = reg.get_for_access(access)
    assert t is not None
    assert t.team == str(team)


def test_get_for_access_no_team_returns_none():
    reg = ExtractionTemplateRegistry()
    access = AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.INTERNAL,
    )
    assert reg.get_for_access(access) is None
