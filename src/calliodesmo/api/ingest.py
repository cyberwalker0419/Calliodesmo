"""/ingest 端点：文件上传 -> 异步 ECL job -> 轮询 /jobs/{id} 取进度与结果。

P4.5 Task 5：POST 改 ``202 + job_id``（BackgroundTasks 进程内 worker），请求即时
返回；ECL 引擎在请求边界按 settings 构建（settings 覆盖生效 + LLM 缺 key 等
``RuntimeError`` -> 503），worker 只执行与状态机（ecl/job_worker.py）。
INGEST 权限守卫；文件存临时路径（worker 完成后删）；chunk/entity/relation/
community 继承 personal access（owner=用户, team_id=None, project_id=None）。
``DELETE /ingest/{doc_id}`` 复用 Task 3 三 store ``delete_by_doc``。
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import (
    get_app_stores,
    get_current_context,
    get_job_session_factory,
    require_permission,
)
from calliodesmo.api.schemas import IngestAcceptedOut
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import LibraryScope, Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.db.session import get_session
from calliodesmo.ecl.demo_seed import _DemoAccessLoader
from calliodesmo.ecl.engine import build_default_indexing_engine
from calliodesmo.ecl.job_worker import run_ingest_job

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    session_factory=Depends(get_job_session_factory),
) -> IngestAcceptedOut:
    """上传文档 -> 建异步 job -> BackgroundTasks 跑 ECL ingest 到个人库。

    - ``ingest`` 权限守卫；文件存临时路径（保留后缀供 loader 分发），worker 完成后删
    - 引擎在请求边界构建：``RuntimeError``（LLM 缺 key 等）-> 503；未注册文件
      后缀在建 job 前经 loader.resolve 显式校验 -> 400
    - ``_DemoAccessLoader`` 按 access 设 chunk access 元数据：personal scope +
      owner=用户；access_level 按文件名前缀（public/internal/confidential，缺省 INTERNAL）
    - 请求记审计（action=ingest_submit）；job 终态审计由 worker 落（action=ingest）
    """
    require_permission(ctx, Permission.INGEST)
    filename = file.filename or "doc.md"
    suffix = Path(filename).suffix or ".md"
    try:
        # 引擎请求边界构建：settings 注入 + RuntimeError -> 503 判定留在请求侧
        engine = build_default_indexing_engine(
            settings,
            vector_store=stores.vector_store,
            graph_store=stores.graph_store,
            community_store=stores.community_store,
            profile_card_store=stores.profile_card_store,
        )
        # personal access：team_ids/project_ids 清空 -> _DemoAccessLoader 落 personal 库
        personal_access = replace(
            ctx,
            team_ids=frozenset(),
            project_ids=frozenset(),
            library_scopes=frozenset({LibraryScope.PERSONAL}),
        )
        engine.loader = _DemoAccessLoader(engine.loader, access=personal_access)
        # 未注册后缀在 ingest 内部才抛 ValueError -> 建 job 前显式 resolve 校验（400）。
        # loader 可能为 None（测试桩引擎），跳过校验不影响生产路径。
        inner = getattr(engine.loader, "inner", None)
        if inner is not None and hasattr(inner, "resolve"):
            inner.resolve(Path(filename))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    # 建 job 行（pending）+ 审计受理，再排后台任务（顺序：先落库后调度）
    job = Job(user_id=ctx.user_id, filename=filename)
    session.add(job)
    await session.flush()
    from calliodesmo.audit.service import record_audit

    await record_audit(
        session,
        user_id=ctx.user_id,
        action="ingest_submit",
        resource_type="job",
        resource_id=str(job.id),
        detail={"filename": filename},
        source="api",
    )
    await session.commit()
    job_id: uuid.UUID = job.id

    async def _cleanup() -> None:
        tmp_path.unlink(missing_ok=True)  # noqa: ASYNC240

    background_tasks.add_task(
        run_ingest_job,
        job_id,
        tmp_path,
        engine=engine,
        access=personal_access,
        session_factory=session_factory,
        request_id=filename,
    )
    background_tasks.add_task(_cleanup)
    return IngestAcceptedOut(job_id=job_id, status=JobStatus.PENDING.value, filename=filename)


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
    from calliodesmo.audit.service import record_audit

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
