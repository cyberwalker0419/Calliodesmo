"""/query/with-image 多模态问答端点：multipart 上传图片 + 识图描述注入回答上下文。

与 ``POST /query``（JSON，纯文本）互补：
- 保留 ``POST /query`` 原样（旧客户端 / curl / 既有测试兼容）
- 新增本端点：multipart/form-data，Form 字段 question / mode / top_k + file 图片
- 流程：读图片字节 -> ``VisionProvider.describe``（识图语义描述）-> 注入 user prompt
  （问题之后、上下文之前）-> LLM 合成（AnswerSynthesizer 内部逻辑不变）
- 守卫：``Permission.QUERY``（同 /query）；审计 detail 加 has_image
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import get_current_context, get_search_engine, get_vision_provider
from calliodesmo.api.schemas import QueryResponse
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode
from calliodesmo.interfaces.vision import VisionProvider

router = APIRouter(prefix="/query", tags=["query"])

_IMAGE_BY_MIME = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}


def _mime_from_name(filename: str) -> str:
    """按文件名后缀推断 mime（客户端常不带 content_type 或填 application/octet-stream）。"""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }.get(suffix, "")


@router.post("/with-image", response_model=QueryResponse)
async def query_with_image(
    question: str = Form(...),
    mode: str = Form("native_rag"),
    top_k: int = Form(10),
    file: UploadFile = File(...),
    context: AccessContext = Depends(get_current_context),
    engine: SearchEngine = Depends(get_search_engine),
    vision: VisionProvider = Depends(get_vision_provider),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    """带图提问：识图描述并入回答上下文（multipart）。"""
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    try:
        search_mode = SearchMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知检索模式：{mode}（可选 native_rag / local / global）",
        ) from None

    # 图片校验：大小上限 + mime
    image_bytes = await file.read()
    if len(image_bytes) > settings.vision_image_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"图片超过大小上限：{settings.vision_image_max_bytes} 字节",
        )
    mime = (file.content_type or "").lower()
    if mime not in _IMAGE_BY_MIME:
        mime = _mime_from_name(file.filename or "")
    if mime not in _IMAGE_BY_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"不支持的图片类型：{file.content_type or file.filename}"
                "（支持 PNG/JPEG/GIF/WebP/BMP/TIFF）"
            ),
        )

    # 识图描述注入回答上下文（VLM 语义理解）
    resp = await vision.describe(settings.vision_prompt, image_bytes, mime=mime)
    # 描述并入问题：AnswerSynthesizer 的 user prompt 为 "问题：{question}\n\n上下文：..."
    # 这里把描述作为看图上下文前置（不侵入合成器内部）
    question_with_image = f"{question}\n\n[图片内容描述] {resp.content}"

    answer = await engine.query(
        question_with_image,
        mode=search_mode,
        top_k=top_k,
        access=context,
    )
    await record_audit(
        session,
        user_id=context.user_id,
        action="query",
        resource_type="answer",
        detail={
            "mode": mode,
            "has_image": True,
            "vision_model": resp.model,
            "sources": len(answer.source_chunk_ids),
        },
        source="api",
    )
    await session.commit()
    return QueryResponse(
        answer=answer.text,
        mode=answer.mode.value,
        source_chunk_ids=answer.source_chunk_ids,
        context_chunks=answer.context_chunks,
        model=answer.model,
    )
