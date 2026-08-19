"""/collab 协作推送端点：建推送/提交/审核/合并 + 差异清单（push/approve 守卫，按 access 过滤）。

路由双挂（根 + /api）由 app.py 统一处理。merge 端点用源用户 access 收集源库数据
（审核人代源用户合并），用审核人 access 查目标库现有 + 状态收尾。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import get_app_stores, get_current_context, require_permission
from calliodesmo.api.schemas import (
    AlignmentReviewOut,
    AlignmentReviewRequest,
    ContributionCreate,
    ContributionOut,
    DiffOut,
    RejectRequest,
    TemplateTypeApproveOut,
    TemplateTypeApproveRequest,
    TemplateTypeOut,
)
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import LibraryScope, Permission
from calliodesmo.auth.service import get_access_context
from calliodesmo.collab.alignment_review import AlignmentReviewService
from calliodesmo.collab.merge import MergeService
from calliodesmo.collab.push import PushService
from calliodesmo.collab.service import (
    ContributionError,
    ContributionNotFoundError,
    ContributionService,
)
from calliodesmo.collab.template_review import TemplateReviewService, collect_discovered_types
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry

router = APIRouter(prefix="/collab", tags=["collab"])

_svc = ContributionService()
_push = PushService()
_merge = MergeService()
_alignment = AlignmentReviewService()


def _to_out(c) -> ContributionOut:
    return ContributionOut(
        id=c.id,
        source_user_id=c.source_user_id,
        source_scope=c.source_scope.value,
        target_scope=c.target_scope.value,
        target_project_id=c.target_project_id,
        target_team_id=c.target_team_id,
        title=c.title,
        description=c.description,
        status=c.status.value,
        doc_ids=list(c.doc_ids),
        assignee_id=c.assignee_id,
        reviewed_by=c.reviewed_by,
        merged_at=c.merged_at,
        created_at=c.created_at,
        version=c.version,
    )


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, ContributionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="贡献不存在或不可见")
    if "自审" in str(exc):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("", response_model=ContributionOut, status_code=201)
async def create_contribution(
    req: ContributionCreate,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    require_permission(ctx, Permission.PUSH)
    try:
        source_scope = LibraryScope(req.source_scope)
        target_scope = LibraryScope(req.target_scope)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知 scope"
        ) from exc
    try:
        c = await _svc.create(
            session,
            source_user_id=ctx.user_id,
            source_scope=source_scope,
            target_scope=target_scope,
            title=req.title,
            doc_ids=req.doc_ids,
            description=req.description,
            target_project_id=req.target_project_id,
            target_team_id=req.target_team_id,
            source="api",
        )
    except ContributionError as exc:
        raise _err(exc) from exc
    await session.commit()
    return _to_out(c)


@router.get("", response_model=list[ContributionOut])
async def list_contributions(
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[ContributionOut]:
    if not (ctx.has_permission(Permission.PUSH) or ctx.has_permission(Permission.APPROVE)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="缺少权限：push 或 approve"
        )
    items = await _svc.list(session, access=ctx)
    return [_to_out(c) for c in items]


@router.get("/template-types", response_model=list[TemplateTypeOut])
async def list_template_types(
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
) -> list[TemplateTypeOut]:
    require_permission(ctx, Permission.APPROVE)
    items = await collect_discovered_types(stores, access=ctx)
    return [TemplateTypeOut(**it) for it in items]


@router.post("/template-types/approve", response_model=TemplateTypeApproveOut)
async def approve_template_type(
    req: TemplateTypeApproveRequest,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    settings: Settings = Depends(get_settings),
) -> TemplateTypeApproveOut:
    require_permission(ctx, Permission.APPROVE)
    registry = ExtractionTemplateRegistry.from_yaml(settings.extraction_template_file)
    svc = TemplateReviewService(registry=registry)
    try:
        result = await svc.approve(
            stores,
            team=req.team,
            approved_type=req.type,
            access=ctx,
            path=settings.extraction_template_file,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemplateTypeApproveOut(**result)


@router.get("/{contribution_id}", response_model=ContributionOut)
async def get_contribution(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    c = await _svc.get(session, contribution_id, access=ctx)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="贡献不存在或不可见")
    return _to_out(c)


@router.get("/{contribution_id}/diff", response_model=DiffOut)
async def get_diff(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DiffOut:
    c = await _svc.get(session, contribution_id, access=ctx)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="贡献不存在或不可见")
    if not c.manifest:
        collected = await _push.collect(c, stores=stores, access=ctx)
        target_entities = await stores.graph_store.list_entities(access=ctx)
        overlap = PushService.compute_overlap(collected.entities, target_entities)
        # P4.5 Task 6：嵌入三段式复核队列（BGE-M3 等真嵌入；缺失时零 overlap 候选）
        alignment_pending = await _compute_alignment_pending(
            collected.entities, target_entities, settings
        )
        await _push.build_manifest(
            session,
            c,
            collected=collected,
            target_overlap=overlap,
            user_id=ctx.user_id,
            source="api",
            alignment_pending=alignment_pending,
        )
        await session.commit()
        c = await _svc.get(session, contribution_id, access=ctx)
    return DiffOut(**_push.diff(c))


async def _compute_alignment_pending(
    source_entities: list, target_entities: list, settings: Settings
) -> list[dict]:
    """按 embedding 三段式算对齐候选；缺嵌入 provider 时返回空（v1 退化，不阻断）。"""
    if not source_entities or not target_entities:
        return []
    from calliodesmo.retrieval.factory import build_embedding_provider

    try:
        embedding = build_embedding_provider(settings)
    except (RuntimeError, ValueError):
        return []
    return await PushService.compute_alignment_pending(
        source_entities, target_entities, embedding=embedding, settings=settings
    )


@router.post("/{contribution_id}/submit", response_model=ContributionOut)
async def submit_contribution(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    require_permission(ctx, Permission.PUSH)
    try:
        c = await _svc.submit(session, contribution_id, user_id=ctx.user_id, source="api")
    except (ContributionError, ContributionNotFoundError) as exc:
        raise _err(exc) from exc
    await session.commit()
    return _to_out(c)


@router.post("/{contribution_id}/approve", response_model=ContributionOut)
async def approve_contribution(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    require_permission(ctx, Permission.APPROVE)
    try:
        c = await _svc.approve(session, contribution_id, user_id=ctx.user_id, source="api")
    except (ContributionError, ContributionNotFoundError) as exc:
        raise _err(exc) from exc
    await session.commit()
    return _to_out(c)


@router.post("/{contribution_id}/reject", response_model=ContributionOut)
async def reject_contribution(
    contribution_id: uuid.UUID,
    req: RejectRequest,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    require_permission(ctx, Permission.APPROVE)
    try:
        c = await _svc.reject(
            session, contribution_id, user_id=ctx.user_id, reason=req.reason, source="api"
        )
    except (ContributionError, ContributionNotFoundError) as exc:
        raise _err(exc) from exc
    await session.commit()
    return _to_out(c)


@router.post("/{contribution_id}/merge", response_model=ContributionOut)
async def merge_contribution(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    require_permission(ctx, Permission.APPROVE)
    c = await _svc.get(session, contribution_id, access=ctx)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="贡献不存在或不可见")
    # 审核人代源用户合并：用源用户 access 收集源库，用审核人 access 查目标库 + 状态收尾
    source_access = await get_access_context(session, c.source_user_id)
    if source_access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="源用户不存在")
    try:
        await _merge.merge(
            session,
            contribution_id,
            stores=stores,
            source_access=source_access,
            target_access=ctx,
            source="api",
        )
    except ContributionError as exc:
        raise _err(exc) from exc
    await session.commit()
    c = await _svc.get(session, contribution_id, access=ctx)
    return _to_out(c)


# ---- 对齐复核（P4.5 Task 6 Step 4）----


@router.get("/{contribution_id}/alignment-review", response_model=list[dict])
async def list_alignment_pending(
    contribution_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """待审对齐对列表（approve 权限 + 贡献可见）。"""
    require_permission(ctx, Permission.APPROVE)
    try:
        return await _alignment.collect_pending(session, contribution_id, access=ctx)
    except ContributionNotFoundError as exc:
        raise _err(exc) from exc


async def _resolve_alignment_pair(
    contribution_id: uuid.UUID,
    req: AlignmentReviewRequest,
    ctx: AccessContext,
    stores,
    session: AsyncSession,
    resolve: str,
) -> AlignmentReviewOut:
    require_permission(ctx, Permission.APPROVE)
    c = await _svc.get(session, contribution_id, access=ctx)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="贡献不存在或不可见")
    source_access = await get_access_context(session, c.source_user_id)
    if source_access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="源用户不存在")
    try:
        if resolve == "approve":
            result = await _alignment.approve(
                session,
                contribution_id,
                pair_id=req.pair_id,
                user_id=ctx.user_id,
                stores=stores,
                source_access=source_access,
                target_access=ctx,
            )
        else:
            result = await _alignment.reject(
                session,
                contribution_id,
                pair_id=req.pair_id,
                user_id=ctx.user_id,
                stores=stores,
                source_access=source_access,
                target_access=ctx,
            )
    except (ContributionError, ContributionNotFoundError) as exc:
        raise _err(exc) from exc
    await session.commit()
    return AlignmentReviewOut(**result)


@router.post("/{contribution_id}/alignment-review/approve", response_model=AlignmentReviewOut)
async def approve_alignment_pair(
    contribution_id: uuid.UUID,
    req: AlignmentReviewRequest,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    session: AsyncSession = Depends(get_session),
) -> AlignmentReviewOut:
    """批准待审对齐对：源实体并入目标库实体（并集 + provenance），幂等。"""
    return await _resolve_alignment_pair(
        contribution_id, req, ctx, stores, session, resolve="approve"
    )


@router.post("/{contribution_id}/alignment-review/reject", response_model=AlignmentReviewOut)
async def reject_alignment_pair(
    contribution_id: uuid.UUID,
    req: AlignmentReviewRequest,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    session: AsyncSession = Depends(get_session),
) -> AlignmentReviewOut:
    """驳回待审对齐对：仅置 rejected + 审计，不动 stores。"""
    return await _resolve_alignment_pair(
        contribution_id, req, ctx, stores, session, resolve="reject"
    )
