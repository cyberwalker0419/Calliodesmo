"""graph_neighbors：图谱邻居 / 子图扩展（hops=1 走 neighbors，>1 走 subgraph BFS）。"""

from __future__ import annotations

from calliodesmo.agent.tools._common import join_lines, truncate
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import ToolSpec

SPEC = ToolSpec(
    name="graph_neighbors",
    description="查询实体的图邻居或 BFS 子图（hops 跳数 / limit 节点上限）",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "hops": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["name"],
    },
)

_MAX_HOPS = 3


class GraphNeighborsTool:
    spec = SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        name = arguments["name"]
        hops = max(1, min(int(arguments.get("hops", 1)), _MAX_HOPS))
        limit = max(1, int(arguments.get("limit", 50)))

        lines: list[str] = []
        if hops == 1:
            entities, relations = await self.store.neighbors(name, access=access)
            lines.append(f"邻居（{name}）：")
            lines += [
                f"- {e.name}（{e.type or '未知类型'}）{truncate(e.description)}" for e in entities
            ]
            lines += [
                f"- {r.source} -[{r.type or '相关'}]-> {r.target}：{truncate(r.description)}"
                for r in relations
            ]
        else:
            view = await self.store.subgraph([name], hops=hops, limit=limit, access=access)
            lines.append(f"子图（{name}，hops={hops}，截断={view.truncated}）：")
            lines += [
                f"- {n.name}（{n.type or '未知类型'}）{truncate(n.description)}" for n in view.nodes
            ]
            lines += [f"- {e.source} -[{e.type or '相关'}]-> {e.target}" for e in view.edges]
        return join_lines(lines)
