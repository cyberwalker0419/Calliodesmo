"""PushService：推送收集与差异清单(manifest)。

从源 scope 枚举 chunk/entity/relation/community（按 ``contribution.doc_ids`` 聚合），
生成内容清单 manifest（各类型 id+计数 + 与目标库的重叠判定），供审核人审阅。
越权源库不收集（``visible_to`` 过滤）。

重叠判定 ``compute_overlap`` 按 ``(name,type)`` 精确匹配（B4：同名不同义冲突解决留 v2，
合并时记 ``merge_decision:"exact_name_type"`` 为 v2 embedding 三段式阈值留接口位）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.collab.models import Contribution


@dataclass
class CollectedContent:
    """推送收集结果：源库命中的 chunk/entity/relation/community。"""

    chunks: list
    entities: list
    relations: list
    communities: list


class PushService:
    async def collect(
        self, contribution: Contribution, *, stores, access: AccessContext
    ) -> CollectedContent:
        """按 ``doc_ids`` 从源库枚举 chunk/entity/relation/community（visible_to 过滤）。

        - chunk：按 ``doc_id`` 过滤
        - entity/relation：``source_chunk_ids`` 命中这些 chunk
        - community：member 命中 entity 或 ``metadata["doc_id"]`` 命中
        """
        doc_ids = set(contribution.doc_ids)
        chunks = [
            c for c in await stores.vector_store.list_chunks(access=access) if c.doc_id in doc_ids
        ]
        chunk_ids = {c.chunk_id for c in chunks}
        entities = [
            e
            for e in await stores.graph_store.list_entities(access=access)
            if any(cid in chunk_ids for cid in e.source_chunk_ids)
        ]
        entity_names = {e.name for e in entities}
        relations = [
            r
            for r in await stores.graph_store.list_relations(access=access)
            if any(cid in chunk_ids for cid in r.source_chunk_ids)
        ]
        communities = [
            c
            for c in await stores.community_store.list_communities(access=access)
            if (entity_names & set(c.member_entity_names)) or c.metadata.get("doc_id") in doc_ids
        ]
        return CollectedContent(chunks, entities, relations, communities)

    @staticmethod
    def compute_overlap(source_entities: list, target_entities: list) -> int:
        """目标库已存同名同类型实体数（B4：v1 仅 (name,type) 精确匹配）。"""
        target_keys = {(e.name, e.type) for e in target_entities}
        return sum(1 for e in source_entities if (e.name, e.type) in target_keys)

    async def build_manifest(
        self,
        session: AsyncSession,
        contribution: Contribution,
        *,
        collected: CollectedContent,
        target_overlap: int = 0,
        user_id: uuid.UUID,
        source: str | None = None,
    ) -> dict:
        """聚合清单 + 重叠判定，写回 ``contribution.manifest``，记审计 push。"""
        manifest = {
            "chunks": [c.chunk_id for c in collected.chunks],
            "entities": [e.name for e in collected.entities],
            "relations": [[r.source, r.target, r.type] for r in collected.relations],
            "communities": [c.community_id for c in collected.communities],
            "counts": {
                "chunks": len(collected.chunks),
                "entities": len(collected.entities),
                "relations": len(collected.relations),
                "communities": len(collected.communities),
            },
            "overlap": target_overlap,
        }
        contribution.manifest = manifest
        await session.flush()
        await record_audit(
            session,
            user_id=user_id,
            action="push",
            resource_type="contribution",
            resource_id=str(contribution.id),
            detail={"manifest": manifest},
            source=source,
        )
        await session.flush()
        return manifest

    @staticmethod
    def diff(contribution: Contribution) -> dict:
        """返回清单摘要供审核展示（新增实体/关系/chunk/社区计数 + 冲突数）。"""
        manifest = contribution.manifest or {}
        counts = manifest.get("counts", {})
        return {
            "new_entities": counts.get("entities", 0),
            "new_relations": counts.get("relations", 0),
            "chunks": counts.get("chunks", 0),
            "communities": counts.get("communities", 0),
            "conflicts": manifest.get("overlap", 0),
        }
