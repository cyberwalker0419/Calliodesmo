"""list_communities：社区摘要枚举（store 侧 visible_to）。"""

from __future__ import annotations

from calliodesmo.agent.tools._common import join_lines, truncate
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.community_store import CommunityStore
from calliodesmo.interfaces.llm import ToolSpec

SPEC = ToolSpec(
    name="list_communities",
    description="枚举当前可见的社区摘要（层级/标题/摘要/成员实体）",
    parameters={"type": "object", "properties": {}, "required": []},
)


class ListCommunitiesTool:
    spec = SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: CommunityStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        communities = await self.store.list_communities(access=access)
        lines = [
            f"- L{c.level} {c.title}（{c.access_level.name}）：{truncate(c.summary)}"
            for c in communities
        ]
        return join_lines(lines) if lines else "（无可见社区）"
