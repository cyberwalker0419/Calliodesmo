"""LoadService：把 ECL 中间产物（Chunk/ExtractionResult/Community）落三层个人库。

- Chunk 经 EmbeddingProvider 嵌入 -> ChunkRecord -> VectorStore
- ExtractionResult -> EntityRecord/RelationRecord -> GraphStore
- Community -> CommunityRecord -> CommunityStore
- access 字段从 chunk（doc）继承，贯通三 store 供 AccessContext 过滤
- L0 chunk 摘要按需补生（summary_enabled 时填 metadata["summary"]，content 保持原文）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.cognify import Community
from calliodesmo.interfaces.community_store import CommunityRecord, CommunityStore
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.extractor import ExtractionResult
from calliodesmo.interfaces.graph_store import EntityRecord, GraphStore, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord, VectorStore

if TYPE_CHECKING:
    from calliodesmo.ecl.chunk_summarizer import LLMChunkSummarizer


def _access_from_chunk(chunk) -> dict[str, Any]:
    return {
        "access_level": chunk.access_level,
        "library_scope": chunk.library_scope,
        "owner_id": chunk.owner_id,
        "project_id": chunk.project_id,
        "team_id": chunk.team_id,
    }


def _access_from_context(access: AccessContext) -> dict[str, Any]:
    from calliodesmo.ecl.cognify import _data_access_fields

    return _data_access_fields(access)


class LoadService:
    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore,
        community_store: CommunityStore,
        embedding_provider: EmbeddingProvider,
        chunk_summarizer: LLMChunkSummarizer | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.community_store = community_store
        self.embedding_provider = embedding_provider
        self.chunk_summarizer = chunk_summarizer

    async def load(
        self,
        chunks: list,
        result: ExtractionResult,
        communities: list[Community],
        *,
        access: AccessContext,
    ) -> None:
        # 默认 access 字段：优先从首个 chunk（doc）继承，否则从 ingest 上下文派生
        base = _access_from_chunk(chunks[0]) if chunks else _access_from_context(access)

        await self._load_chunks(chunks)
        await self._load_graph(result, base)
        await self._load_communities(communities)

    async def _load_chunks(self, chunks: list) -> None:
        if not chunks:
            return
        embed = await self.embedding_provider.embed([c.content for c in chunks])
        records = []
        for c, vec in zip(chunks, embed.vectors, strict=True):
            metadata = dict(c.metadata)
            # L0 chunk 摘要按需补生：summary_enabled 时填 metadata["summary"]，content 保持原文
            if self.chunk_summarizer is not None:
                summary = await self.chunk_summarizer.summarize(c.content)
                if summary:
                    metadata["summary"] = summary
            records.append(
                ChunkRecord(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    content=c.content,
                    vector=vec,
                    metadata=metadata,
                    access_level=c.access_level,
                    library_scope=c.library_scope,
                    owner_id=c.owner_id,
                    project_id=c.project_id,
                    team_id=c.team_id,
                )
            )
        await self.vector_store.upsert_chunks(records)

    async def _load_graph(self, result: ExtractionResult, base: dict[str, Any]) -> None:
        entities = [
            EntityRecord(
                name=e.name,
                type=e.type,
                description=e.description,
                source_chunk_ids=list(e.source_chunk_ids),
                template_conforming=e.template_conforming,
                **base,
            )
            for e in result.entities
        ]
        relations = [
            RelationRecord(
                source=r.source,
                target=r.target,
                type=r.type,
                description=r.description,
                source_chunk_ids=list(r.source_chunk_ids),
                **base,
            )
            for r in result.relations
        ]
        await self.graph_store.upsert_graph(entities, relations)

    async def _load_communities(self, communities: list[Community]) -> None:
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
