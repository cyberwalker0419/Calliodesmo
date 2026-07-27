"""/library 只读浏览端点：ProfileCard / 社区 / 实体 / 子图（query 守卫 + visible_to 过滤）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import (
    get_community_store,
    get_current_context,
    get_graph_store,
    get_profile_card_store,
    require_permission,
)
from calliodesmo.api.schemas import (
    CommunityOut,
    EntityBrief,
    EntityOut,
    ProfileCardOut,
    RelationOut,
    SubgraphEdge,
    SubgraphNode,
    SubgraphResponse,
)
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.profile_card import ProfileCard

router = APIRouter(prefix="/library", tags=["library"])

_GUARD = Permission.QUERY


def _card_out(card: ProfileCard) -> ProfileCardOut:
    return ProfileCardOut(
        entity_name=card.entity_name,
        entity_type=card.entity_type,
        aliases=[a.value for a in card.aliases],
        role=card.role.value if card.role else None,
        organization=card.organization.value if card.organization else None,
        associates=[a.value for a in card.associates],
        timespan=card.timespan.value if card.timespan else None,
        description=card.description,
        narrative=card.narrative,
        evidence_chunk_ids=list(card.evidence_chunk_ids),
        access_level=card.access_level.name,
        library_scope=card.library_scope.value,
    )


@router.get("/profile-cards", response_model=list[ProfileCardOut])
async def list_profile_cards(
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_profile_card_store),
) -> list[ProfileCardOut]:
    require_permission(ctx, _GUARD)
    return [_card_out(c) for c in await store.list(access=ctx)]  # store 内已 visible_to 过滤


@router.get("/profile-cards/{entity_name}", response_model=ProfileCardOut)
async def get_profile_card(
    entity_name: str,
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_profile_card_store),
) -> ProfileCardOut:
    require_permission(ctx, _GUARD)
    card = await store.get(entity_name, access=ctx)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="档案卡不存在或不可见")
    return _card_out(card)


@router.get("/communities", response_model=list[CommunityOut])
async def list_communities(
    level: int | None = Query(default=None, ge=0),
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_community_store),
) -> list[CommunityOut]:
    require_permission(ctx, _GUARD)
    records = await store.list_communities(access=ctx)
    if level is not None:
        records = [r for r in records if r.level == level]
    return [
        CommunityOut(
            community_id=r.community_id,
            level=r.level,
            title=r.title,
            summary=r.summary,
            member_entity_names=list(r.member_entity_names),
            metadata=dict(r.metadata),
            access_level=r.access_level.name,
            library_scope=r.library_scope.value,
        )
        for r in records
    ]


@router.get("/entities/{name}", response_model=EntityOut)
async def get_entity(
    name: str,
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_graph_store),
    session: AsyncSession = Depends(get_session),
) -> EntityOut:
    require_permission(ctx, _GUARD)
    ent = await store.get_entity(name, access=ctx)
    if ent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="实体不存在或不可见")
    neighbors, relations = await store.neighbors(name, access=ctx)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="query",
        resource_type="entity",
        resource_id=name,
        detail={"endpoint": "entity_detail"},
        source="api",
    )
    await session.commit()
    return EntityOut(
        name=ent.name,
        type=ent.type,
        description=ent.description,
        source_chunk_ids=list(ent.source_chunk_ids),
        template_conforming=ent.template_conforming,
        access_level=ent.access_level.name,
        library_scope=ent.library_scope.value,
        neighbors=[
            EntityBrief(name=n.name, type=n.type, description=n.description) for n in neighbors
        ],
        relations=[
            RelationOut(source=r.source, target=r.target, type=r.type, description=r.description)
            for r in relations
        ],
    )


@router.get("/subgraph", response_model=SubgraphResponse)
async def get_subgraph(
    seeds: str = Query(..., description="种子实体名，逗号分隔（多种子）"),
    hops: int = Query(default=1, ge=0, le=5),
    limit: int = Query(default=50, ge=1, le=500),
    ctx: AccessContext = Depends(get_current_context),
    store=Depends(get_graph_store),
) -> SubgraphResponse:
    """增量子图扩展：BFS 从 seeds 按 hops 扩、limit 截断，全程 visible_to 过滤。"""
    require_permission(ctx, _GUARD)
    seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
    if not seed_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="seeds 不能为空"
        )
    view = await store.subgraph(seed_list, hops=hops, limit=limit, access=ctx)
    return SubgraphResponse(
        nodes=[
            SubgraphNode(
                name=n.name,
                type=n.type,
                description=n.description,
                access_level=n.access_level.name,
            )
            for n in view.nodes
        ],
        edges=[
            SubgraphEdge(source=e.source, target=e.target, type=e.type, description=e.description)
            for e in view.edges
        ],
        expanded_seeds=list(view.expanded_seeds),
        truncated=view.truncated,
    )
