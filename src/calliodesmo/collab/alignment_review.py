"""AlignmentReviewService：推送待审对齐对的收集与批准/驳回（P4.5 Task 6 Step 3）。

仿 ``template_review`` 的收集-批准-幂等落地 + P4 状态机守卫：
- ``collect_pending``：读 ``contribution.manifest["alignment_pending"]``（已落库）-> 待审对
- ``approve``：把源实体并入目标库实体（source_chunk_ids 去重并集 + 描述拼接 +
  ``merge_decision=auto_merged`` + provenance + 审计）；resolve 后幂等
- ``reject``：仅置 review_status=rejected + 审计，不动 stores；resolve 后幂等
- 自审阻断（源用户不能复核自己的推送对齐）+ 已合并贡献不可再复核

对齐对状态走 ``manifest[alignment_pending][i][review_status]``（pending/approved/rejected）
就地落库（Manifest 是本 MR 语境的一部分，与 P4 manifest 同生命周期）；
独立 ``alignment_reviews`` 表留存证查询（roadmap P9 审计硬化）。
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import (
    ContributionError,
    ContributionNotFoundError,
    ContributionService,
)


class AlignmentReviewService:
    def __init__(self, contribution_service: ContributionService | None = None) -> None:
        self.cs = contribution_service or ContributionService()

    async def collect_pending(
        self, session: AsyncSession, contribution_id: uuid.UUID, *, access: AccessContext
    ) -> list[dict]:
        """收集待审对齐对（manifest 已落库，仅未 resolve 的）。"""
        contribution = await self.cs.get(session, contribution_id, access=access)
        if contribution is None:
            raise ContributionNotFoundError(f"贡献 {contribution_id} 不存在")
        pairs = list(contribution.manifest.get("alignment_pending", []))
        return [
            {**p, "status": p.get("review_status", "pending")}
            for p in pairs
            if p.get("review_status", "pending") == "pending"
        ]

    async def _resolve_pair(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        pair_id: str,
        user_id: uuid.UUID,
        stores,
        source_access: AccessContext,
        target_access: AccessContext,
        resolve: str,  # approved | rejected
    ) -> dict:
        contribution = await session.get(Contribution, contribution_id)
        if contribution is None:
            raise ContributionNotFoundError(f"贡献 {contribution_id} 不存在")
        if contribution.source_user_id == user_id:
            raise ContributionError("不能复核自己的推送对齐（自审阻断）")
        if contribution.status == ContributionStatus.MERGED:
            raise ContributionError("贡献已合并，不可再复核对齐")
        pair = next(
            (
                p
                for p in contribution.manifest.get("alignment_pending", [])
                if p.get("pair_id") == pair_id
            ),
            None,
        )
        if pair is None:
            raise ContributionNotFoundError(f"对齐对 {pair_id} 不存在")
        # 幂等：已 resolve 的对直接返回当前状态（不重复写 stores）
        current = pair.get("review_status")
        if current in ("approved", "rejected"):
            return {"pair_id": pair_id, "status": current}

        if resolve == "approved":
            await self._merge_pair_into_target(
                contribution, pair, stores, source_access=source_access, target_access=target_access
            )
        pair["review_status"] = resolve
        pair["reviewed_by"] = str(user_id)
        # TODO(P6 Task 1 审查留痕, 2026-W49)：JSON manifest 内时间串为 naive UTC（无时区后缀）。
        # ORM 时间列已统一 tz-aware（P6 Task 1），此处字符串是否补 +00:00 后缀需与前端
        # 消费格式（ContributionDetail 时间显示）对齐后动，随 P9 收尾批评估；全库仅此 1 处。
        pair["reviewed_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
        # JSON 列不做嵌套可变跟踪，且 setter 按值比较（deepcopy 结构相等不触发 dirty）
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(contribution, "manifest")
        await session.flush()
        await record_audit(
            session,
            user_id=user_id,
            action=f"alignment_{resolve}",
            resource_type="contribution",
            resource_id=str(contribution.id),
            detail={
                "pair_id": pair_id,
                "source": pair.get("source_name"),
                "target": pair.get("target_name"),
            },
            source="api",
        )
        await session.flush()
        return {
            "pair_id": pair_id,
            "status": resolve,
            "source_name": pair.get("source_name"),
            "target_name": pair.get("target_name"),
        }

    async def _merge_pair_into_target(
        self,
        contribution: Contribution,
        pair: dict,
        stores,
        *,
        source_access: AccessContext,
        target_access: AccessContext,
    ) -> None:
        """把源侧实体并入目标侧实体（并集语义与 merge_entities 一致），落目标 store。"""
        source_name = pair["source_name"]
        target_name = pair["target_name"]
        tgt = await stores.graph_store.get_entity(target_name, access=target_access)
        src = await stores.graph_store.get_entity(source_name, access=source_access)
        if tgt is None or src is None:
            raise ContributionError(
                f"对齐对实体缺失（source={source_name!r}, target={target_name!r}），无法批准"
            )
        chunk_ids = list(dict.fromkeys([*tgt.source_chunk_ids, *src.source_chunk_ids]))
        descs = [d for d in (tgt.description, src.description) if d]
        desc = "\n".join(dict.fromkeys(descs))
        meta = dict(tgt.metadata or {})
        meta["provenance"] = {
            "contribution_id": str(contribution.id),
            "source_user_id": str(contribution.source_user_id),
        }
        meta["merge_decision"] = "auto_merged"
        merged = replace(
            tgt,
            description=desc,
            source_chunk_ids=chunk_ids,
            access_level=max(tgt.access_level, src.access_level),
            metadata=meta,
        )
        await stores.graph_store.upsert_graph([merged], [])

    async def approve(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        pair_id: str,
        user_id: uuid.UUID,
        stores,
        source_access: AccessContext,
        target_access: AccessContext,
    ) -> dict:
        return await self._resolve_pair(
            session,
            contribution_id,
            pair_id=pair_id,
            user_id=user_id,
            stores=stores,
            source_access=source_access,
            target_access=target_access,
            resolve="approved",
        )

    async def reject(
        self,
        session: AsyncSession,
        contribution_id: uuid.UUID,
        *,
        pair_id: str,
        user_id: uuid.UUID,
        stores,
        source_access: AccessContext,
        target_access: AccessContext,
    ) -> dict:
        return await self._resolve_pair(
            session,
            contribution_id,
            pair_id=pair_id,
            user_id=user_id,
            stores=stores,
            source_access=source_access,
            target_access=target_access,
            resolve="rejected",
        )
