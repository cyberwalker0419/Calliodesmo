"""list_documents / get_chunk：文档聚合枚举 + 块取回。

**红线**：``VectorStore.get_chunks_by_ids`` 接口无 access 过滤——``get_chunk`` 工具层
必须自补 ``visible_to`` 逐条复核（跨密级泄漏通道）；越权 / 不存在同一语义（LookupError
由注册表收统一消息，不泄漏存在性）。
"""

from __future__ import annotations

from calliodesmo.agent.tools._common import join_lines, truncate
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.llm import ToolSpec
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.stores.visibility import visible_to

LIST_SPEC = ToolSpec(
    name="list_documents",
    description="按 doc 聚合枚举当前可见文档（块数/密级/范围）",
    parameters={"type": "object", "properties": {}, "required": []},
)

GET_SPEC = ToolSpec(
    name="get_chunk",
    description="按 chunk_id 取原始文本块（逐条权限复核，带引注）",
    parameters={
        "type": "object",
        "properties": {"chunk_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["chunk_ids"],
    },
)


class ListDocumentsTool:
    spec = LIST_SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: VectorStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        chunks = await self.store.list_chunks(access=access)
        docs: dict[str, dict] = {}
        for c in chunks:
            agg = docs.setdefault(
                c.doc_id, {"chunks": 0, "level": c.access_level, "scope": c.library_scope}
            )
            agg["chunks"] += 1
        lines = [
            f"- {doc_id}：{agg['chunks']} 块（{agg['level'].name}/{agg['scope'].value}）"
            for doc_id, agg in sorted(docs.items())
        ]
        return join_lines(lines) if lines else "（无可见文档）"


class GetChunkTool:
    spec = GET_SPEC
    required_permission = Permission.QUERY

    def __init__(self, store: VectorStore) -> None:
        self.store = store

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        chunks = await self.store.get_chunks_by_ids(list(arguments["chunk_ids"]))
        # 红线：接口无 access 过滤——工具层逐条 visible_to 复核
        visible = [c for c in chunks if visible_to(c, access)]
        if not visible:
            # 越权与不存在同一语义（不泄漏存在性）
            raise LookupError(",".join(arguments["chunk_ids"]))
        return join_lines(
            [f"[{c.chunk_id}]（{c.access_level.name}）{truncate(c.content)}" for c in visible]
        )
