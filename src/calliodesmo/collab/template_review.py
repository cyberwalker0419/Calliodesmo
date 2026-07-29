"""抽取模板 review-gated 沉淀：收集发现类型 + 审核批准写回 YAML。

- ``collect_discovered_types``：扫 GraphStore 中 ``template_conforming=False`` 实体的
  ``type``，聚合去重 + 计数（空类型过滤；approved 类型已进模板 -> conforming=True 不再收集）。
- ``TemplateReviewService.approve``：批准类型 -> ``sediment`` 写回 YAML（幂等）。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry


async def collect_discovered_types(stores, *, access: AccessContext) -> list[dict]:
    """扫 GraphStore 中 template_conforming=False 实体的 type，聚合去重 + 计数。

    空类型（None）过滤；已进模板的类型 conforming=True 不收集。全部标记 pending。
    """
    entities = await stores.graph_store.list_entities(access=access)
    counts: dict[str, int] = {}
    for e in entities:
        if not e.template_conforming and e.type:
            counts[e.type] = counts.get(e.type, 0) + 1
    return [
        {"type": etype, "count": count, "status": "pending"}
        for etype, count in sorted(counts.items())
    ]


class TemplateReviewService:
    """抽取模板 review-gated 审核服务：批准发现类型沉淀进团队模板。"""

    def __init__(self, registry: ExtractionTemplateRegistry | None = None) -> None:
        self.registry = registry

    async def approve(
        self,
        stores,
        *,
        team: str,
        approved_type: str,
        access: AccessContext,
        path: str | None = None,
    ) -> dict:
        """批准类型 -> sediment 写回 YAML（幂等）。返回 {team, type, status}。"""
        if self.registry is None:
            raise RuntimeError("未配置 ExtractionTemplateRegistry")
        self.registry.sediment(team, [approved_type], path=path)
        return {"team": team, "type": approved_type, "status": "approved"}
