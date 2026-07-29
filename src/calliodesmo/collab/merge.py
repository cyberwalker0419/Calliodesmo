"""MergeService：approved 贡献合并进目标 scope（图谱合并 + scope 改写 + 状态收尾）。

- 仅 approved 可合并；已 MERGED 不可再合并（幂等）。
- 自审阻断（合并人 != 源用户）。
- 图谱合并（实体按 name 去重 + 关系并集 + provenance）后 upsert 目标 store。
- access_level 保留源值（不降密）；scope 字段改写为目标 scope。
- 状态收尾复用 ContributionService.merge（version 乐观锁 + 审计）。

崩溃一致性【修订】：合并跨两轨写（内存 stores + ORM）非原子，v1 接受（演示/单机），
可选两阶段（ORM MERGING -> 合并 stores -> MERGED）便于崩溃检测；持久化 stores 留 P9。
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.auth.context import AccessContext
from calliodesmo.collab.graph_merge import merge_entities, merge_relations
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.push import PushService
from calliodesmo.collab.service import ContributionError, ContributionService


class MergeService:
    def __init__(
        self,
        contribution_service: ContributionService | None = None,
        push_service: PushService | None = None,
    ) -> None:
        self.cs = contribution_service or ContributionService()
        self.push = push_service or PushService()

    async def merge(
        self,
        session: AsyncSession,
        contribution_id,
        *,
        stores,
        source_access: AccessContext,
        target_access: AccessContext,
        source: str | None = None,
    ) -> Contribution:
        contribution = await session.get(Contribution, contribution_id)
        if contribution is None:
            raise ContributionError("贡献不存在")
        if contribution.status == ContributionStatus.MERGED:
            raise ContributionError("已合并，不可重复合并（幂等）")
        if contribution.status != ContributionStatus.APPROVED:
            raise ContributionError("仅 approved 可合并")
        if contribution.source_user_id == target_access.user_id:
            raise ContributionError("不能合并自己的推送（自审阻断）")
        # 收集源数据（源用户 access，看源 personal 库）
        collected = await self.push.collect(contribution, stores=stores, access=source_access)
        provenance = {
            "contribution_id": str(contribution.id),
            "source_user_id": str(contribution.source_user_id),
        }
        # 目标库现有数据（审核人 access，看目标 scope）
        target_entities = await stores.graph_store.list_entities(access=target_access)
        target_relations = await stores.graph_store.list_relations(access=target_access)
        # 图谱合并（纯函数）+ scope 改写
        merged_entities = merge_entities(
            collected.entities,
            target_entities=target_entities,
            target_scope=contribution.target_scope,
            target_project_id=contribution.target_project_id,
            target_team_id=contribution.target_team_id,
            provenance=provenance,
        )
        merged_relations = merge_relations(
            collected.relations,
            target_relations=target_relations,
            target_scope=contribution.target_scope,
            target_project_id=contribution.target_project_id,
            target_team_id=contribution.target_team_id,
            provenance=provenance,
        )
        rewritten_chunks = [_rewrite_chunk(c, contribution, provenance) for c in collected.chunks]
        rewritten_communities = [
            _rewrite_community(c, contribution, provenance) for c in collected.communities
        ]
        # upsert 目标 store（scope 已改写）
        await stores.vector_store.upsert_chunks(rewritten_chunks)
        await stores.graph_store.upsert_graph(merged_entities, merged_relations)
        await stores.community_store.upsert_communities(rewritten_communities)
        # 状态收尾（复用状态机 + version 乐观锁 + 审计 merge）
        await self.cs.merge(session, contribution_id, user_id=target_access.user_id, source=source)
        return contribution


def _rewrite_chunk(chunk, contribution: Contribution, provenance: dict):
    meta = dict(chunk.metadata)
    meta["provenance"] = provenance
    return replace(
        chunk,
        library_scope=contribution.target_scope,
        owner_id=None,
        project_id=contribution.target_project_id,
        team_id=contribution.target_team_id,
        metadata=meta,
    )


def _rewrite_community(community, contribution: Contribution, provenance: dict):
    meta = dict(community.metadata)
    meta["provenance"] = provenance
    return replace(
        community,
        library_scope=contribution.target_scope,
        owner_id=None,
        project_id=contribution.target_project_id,
        team_id=contribution.target_team_id,
        metadata=meta,
    )
