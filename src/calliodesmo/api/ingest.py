"""/ingest 端点：文件上传 -> ECL ingest 到当前用户个人库（owner=用户, scope=personal）。

INGEST 权限守卫；文件存临时路径，ingest 后删；chunk/entity/relation/community
继承 personal access（owner=ctx.user_id, team_id=None, project_id=None）；
记审计。serve 进程内跑 ECL（内存 stores 单例），多账户各 token 调用即各 personal 库。
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import get_app_stores, get_current_context, require_permission
from calliodesmo.api.schemas import IngestStatsOut
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import LibraryScope, Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.ecl.demo_seed import _DemoAccessLoader
from calliodesmo.ecl.engine import build_default_indexing_engine

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestStatsOut, status_code=201)
async def ingest_file(
    file: UploadFile,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> IngestStatsOut:
    """上传文档 -> ECL ingest 到当前用户个人库。

    - ``ingest`` 权限守卫
    - 文件存临时路径（保留后缀供 loader 分发），ingest 后删
    - ``_DemoAccessLoader`` 按 access 设 chunk access 元数据：personal scope +
      owner=用户；access_level 按文件名前缀（public/internal/confidential，缺省 INTERNAL）
    - 记审计（action=ingest）
    """
    require_permission(ctx, Permission.INGEST)
    # personal access：team_ids/project_ids 清空 -> _DemoAccessLoader 落 personal 库
    personal_access = replace(
        ctx,
        team_ids=frozenset(),
        project_ids=frozenset(),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )
    filename = file.filename or "doc.md"
    suffix = Path(filename).suffix or ".md"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        engine = build_default_indexing_engine(
            settings,
            vector_store=stores.vector_store,
            graph_store=stores.graph_store,
            community_store=stores.community_store,
            profile_card_store=stores.profile_card_store,
        )
        engine.loader = _DemoAccessLoader(engine.loader, access=personal_access)
        stats = await engine.ingest(tmp_path, access=personal_access)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)  # noqa: ASYNC240
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="ingest",
        resource_type="document",
        detail=stats.as_dict(),
        source="api",
    )
    await session.commit()
    return IngestStatsOut(
        documents=stats.documents,
        chunks=stats.chunks,
        entities=stats.entities,
        relations=stats.relations,
        communities=stats.communities,
        profile_cards=stats.profile_cards,
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(
    doc_id: str,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    session: AsyncSession = Depends(get_session),
) -> None:
    """删除某文档及其全部派生（chunk / 图谱引用 / 社区成员）。

    P4.5 Task 3 Step 5。``ingest`` 权限守卫 + owner 校验（personal 库仅本人可删自己的文档）；
    越权或不存在 -> 404（不泄漏存在性）。复用三 store ``delete_by_doc``。
    """
    require_permission(ctx, Permission.INGEST)
    # 取该文档的 chunk_ids（供图谱清理）——list_chunks 经 visible_to 过滤，非本人 doc 不可见
    chunks = await stores.vector_store.list_chunks(access=ctx)
    chunk_ids = [c.chunk_id for c in chunks if c.doc_id == doc_id]
    if not chunk_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档不存在或不属于当前用户: {doc_id}",
        )
    await stores.vector_store.delete_by_doc(doc_id)
    await stores.graph_store.delete_by_doc(chunk_ids)
    await stores.community_store.delete_by_doc(doc_id)
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="delete",
        resource_type="document",
        detail={"doc_id": doc_id, "chunk_ids": chunk_ids},
        source="api",
    )
    await session.commit()
    return None
