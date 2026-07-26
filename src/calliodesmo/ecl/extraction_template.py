"""ExtractionTemplateRegistry：从 YAML 加载团队级抽取模板（软引导），按 team 唯一。

模板为**引导非白名单**：注入 prompt 优先抽取模板类型，但模板外实体仍保留并打标
（``template_conforming``/``discovered_types``），不 reject。新类型沉淀进模板为
review-gated（P4），P1 只捕获+打标+收集。

YAML 结构（``config/extraction_templates.yaml``）::

    templates:
      - team: "team-alpha"
        preferred_entity_types: ["person", "organization"]
        type_descriptions: {person: "an individual"}
        relation_types: ["works_for"]
        instructions: "优先抽取人物与组织及其关系。"

- 同 team 重复键 -> 加载报错
- 缺文件/空文件 -> 空 registry（全 free）
- 路径经 ``CALLIODESMO_EXTRACTION_TEMPLATE_FILE`` 可覆盖
"""

from __future__ import annotations

import uuid
from pathlib import Path

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.extractor import ExtractionTemplate


class ExtractionTemplateRegistry:
    def __init__(self, templates: dict[str, ExtractionTemplate] | None = None) -> None:
        self._templates: dict[str, ExtractionTemplate] = dict(templates or {})

    @classmethod
    def from_yaml(cls, path: str | Path | None) -> ExtractionTemplateRegistry:
        if not path:
            return cls()
        p = Path(path)
        if not p.exists():
            return cls()
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
        if not data:
            return cls()
        entries = data.get("templates", []) if isinstance(data, dict) else []
        templates: dict[str, ExtractionTemplate] = {}
        for entry in entries:
            if not isinstance(entry, dict) or "team" not in entry:
                raise ValueError(f"非法模板条目（缺 team 字段）: {entry!r}")
            team = str(entry["team"])
            if team in templates:
                raise ValueError(f"团队模板重复: {team}（每团队仅允许一套模板）")
            templates[team] = ExtractionTemplate(
                team=team,
                preferred_entity_types=list(entry.get("preferred_entity_types", [])),
                type_descriptions=dict(entry.get("type_descriptions", {})),
                relation_types=list(entry.get("relation_types", [])),
                instructions=str(entry.get("instructions", "")),
            )
        return cls(templates)

    def get(self, team: str | uuid.UUID | None) -> ExtractionTemplate | None:
        if team is None:
            return None
        return self._templates.get(str(team))

    def get_for_access(self, access: AccessContext) -> ExtractionTemplate | None:
        """按 access.team_ids 解析所属团队模板（首个命中即返回）。"""
        for tid in access.team_ids:
            tmpl = self._templates.get(str(tid))
            if tmpl is not None:
                return tmpl
        return None

    def __len__(self) -> int:
        return len(self._templates)

    def __contains__(self, team: object) -> bool:
        return self.get(team) is not None  # type: ignore[arg-type]
