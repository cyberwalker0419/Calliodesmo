"""DocumentCommunityDeriver：选项 A 自动派生文档级社区（level=1）。

在 Task 3 实体社区之上，按文档来源聚合一层"文档级"社区，便于按文档检索与导航。
- 按 doc_id 聚合其 chunk 关联实体（经实体消解后的图节点）
- LLM 生成文档级 title+summary
- 写入 CommunityStore（level=1），access 字段从该文档 chunk 继承
- 增量安全：仅为本批文档派生，不动已有文档社区（community_id 按 doc 唯一）
- 手动编辑保护：跳过 metadata["manual"]=True 的社区（不覆盖手改，P3）
"""

from __future__ import annotations

import json
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.cognify import _data_access_fields
from calliodesmo.interfaces.cognify import Community
from calliodesmo.interfaces.community_store import CommunityRecord, CommunityStore
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider


def _doc_id_of(chunk_id: str) -> str:
    return chunk_id.split("#", 1)[0] if "#" in chunk_id else chunk_id


def _access_from_chunk(chunk) -> dict[str, Any]:
    return {
        "access_level": chunk.access_level,
        "library_scope": chunk.library_scope,
        "owner_id": chunk.owner_id,
        "project_id": chunk.project_id,
        "team_id": chunk.team_id,
    }


class DocumentCommunityDeriver:
    def __init__(
        self,
        llm: LLMProvider,
        community_store: CommunityStore | None = None,
        *,
        temperature: float = 0.2,
    ) -> None:
        self.llm = llm
        self.community_store = community_store
        self.temperature = temperature

    async def derive(self, chunks: list, graph: dict, *, access: AccessContext) -> list[Community]:
        # doc_id -> 访问字段（从该文档首个 chunk 继承）
        doc_access: dict[str, dict[str, Any]] = {}
        for c in chunks:
            doc_access.setdefault(c.doc_id, _access_from_chunk(c))

        # doc_id -> 关联实体节点
        doc_entities: dict[str, list] = {}
        nodes = graph.get("nodes", {})
        for node in nodes.values():
            docs = {_doc_id_of(cid) for cid in node.source_chunk_ids}
            for doc_id in docs:
                doc_entities.setdefault(doc_id, []).append(node)

        communities: list[Community] = []
        for doc_id in sorted(doc_entities):
            members = doc_entities[doc_id]
            title, summary = await self._summarize(doc_id, members)
            fields = doc_access.get(doc_id) or _data_access_fields(access)
            communities.append(
                Community(
                    community_id=f"doc-{doc_id}",
                    level=1,
                    title=title or f"文档社区: {doc_id}",
                    summary=summary,
                    member_entity_names=sorted(m.name for m in members),
                    metadata={"doc_id": doc_id, "size": len(members)},
                    **fields,
                )
            )

        # 手动编辑保护：跳过 metadata["manual"]=True 的社区（不覆盖手改）
        if self.community_store is not None:
            communities = [
                c
                for c in communities
                if c.community_id not in self.community_store._records
                or not self.community_store._records[c.community_id].metadata.get("manual")
            ]
            records = [
                CommunityRecord(
                    community_id=c.community_id,
                    level=c.level,
                    title=c.title,
                    summary=c.summary,
                    member_entity_names=list(c.member_entity_names),
                    metadata=dict(c.metadata),
                    access_level=c.access_level,
                    library_scope=c.library_scope,
                    owner_id=c.owner_id,
                    project_id=c.project_id,
                    team_id=c.team_id,
                )
                for c in communities
            ]
            await self.community_store.upsert_communities(records)
        return communities

    async def _summarize(self, doc_id: str, members: list) -> tuple[str, str]:
        if not members:
            return f"文档社区: {doc_id}", "（无关联实体）"
        listing = "\n".join(f"- {m.name}（{m.type or '未知'}）: {m.description}" for m in members)
        messages = [
            LLMMessage(
                "system",
                "你是文档摘要引擎。为给定文档的实体集合生成简短 title 与 summary。"
                '严格只输出 JSON：{"title":"...","summary":"..."}',
            ),
            LLMMessage("user", f"文档 {doc_id} 的实体：\n{listing}"),
        ]
        resp = await self.llm.complete(messages, temperature=self.temperature)
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> tuple[str, str]:
        try:
            data = json.loads(content.strip().strip("`"))
            if isinstance(data, dict):
                return str(data.get("title", "")), str(data.get("summary", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
        return "", ""
