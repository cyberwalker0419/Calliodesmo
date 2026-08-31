"""list_entities / entity_profile：实体枚举与档案卡（store 侧 visible_to）。"""

from __future__ import annotations

from calliodesmo.agent.tools._common import join_lines, truncate
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import ToolSpec
from calliodesmo.stores.profile_card_store import InMemoryProfileCardStore

LIST_SPEC = ToolSpec(
    name="list_entities",
    description="枚举当前可见的全部实体（名称/类型/简述）",
    parameters={"type": "object", "properties": {}, "required": []},
)

PROFILE_SPEC = ToolSpec(
    name="entity_profile",
    description="取实体档案卡（角色/组织/关联/时间跨度/叙述）",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)


class ListEntitiesTool:
    spec = LIST_SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        entities = await self.store.list_entities(access=access)
        lines = [f"- {e.name}（{e.type or '未知类型'}）{truncate(e.description)}" for e in entities]
        return join_lines(lines) if lines else "（无可见实体）"


class EntityProfileTool:
    spec = PROFILE_SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: InMemoryProfileCardStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        card = await self.store.get(arguments["name"], access=access)
        if card is None:
            # 不可见 / 不存在同一语义：抛 LookupError 由注册表收统一消息
            raise LookupError(arguments["name"])
        return truncate(card.to_context_text(), 2000)
