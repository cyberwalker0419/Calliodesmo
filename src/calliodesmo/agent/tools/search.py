"""search_knowledge：委派 SearchEngine 三模式（native_rag / local / global），access 全程传参。"""

from __future__ import annotations

from calliodesmo.agent.tools._common import clip_output, truncate
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.llm import ToolSpec
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode

SPEC = ToolSpec(
    name="search_knowledge",
    description="在三层知识图谱检索（native_rag / local / global 三模式），回带来源引注",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "mode": {"type": "string", "enum": [m.value for m in SearchMode]},
            "top_k": {"type": "integer"},
        },
        "required": ["question"],
    },
)


class SearchKnowledgeTool:
    spec = SPEC
    required_permission = Permission.QUERY

    def __init__(self, engine: SearchEngine) -> None:
        self.engine = engine

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        try:
            mode = SearchMode(arguments.get("mode", SearchMode.NATIVE_RAG.value))
        except ValueError:
            raise ValueError(f"未知检索模式：{arguments.get('mode')}") from None
        answer = await self.engine.query(
            arguments["question"],
            mode=mode,
            top_k=int(arguments.get("top_k", 6)),
            access=access,
        )
        lines = [clip_output(answer.text), "", "来源："]
        for chunk in answer.context_chunks:
            cid = chunk.get("chunk_id", "?")
            lines.append(f"[{cid}] {truncate(str(chunk.get('content', '')))}")
        return "\n".join(lines)
