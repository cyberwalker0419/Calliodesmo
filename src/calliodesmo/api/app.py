"""FastAPI 应用工厂：健康检查 + JWT 认证 + Q&A 查询 + 管理/浏览端点。

路由双挂：核心与业务路由同时挂在根路径与 ``/api`` 前缀下——前端 dev/prod 均
以 ``/api`` 为 baseURL（Vite dev proxy 去前缀转发；生产 StaticFiles 同源托管），
根路径保留兼容 CLI/脚本直连。
"""

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo import __version__
from calliodesmo.api.admin import router as admin_router
from calliodesmo.api.collab import router as collab_router
from calliodesmo.api.deps import get_current_context, get_search_engine
from calliodesmo.api.ingest import router as ingest_router
from calliodesmo.api.library import router as library_router
from calliodesmo.api.query_with_image import router as query_image_router
from calliodesmo.api.schemas import (
    ChangePasswordRequest,
    MeResponse,
    QueryRequest,
    QueryResponse,
    RegisterRequest,
    TokenResponse,
)
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, Permission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import authenticate, change_password, create_user
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode

#: JWT httpOnly cookie 名（SameSite=Lax；防 XSS 读 token）
SESSION_COOKIE = "calliodesmo_session"


class SPAStaticFiles(StaticFiles):
    """SPA 静态托管：未知路径回退 index.html（前端路由由客户端接管）。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _issue_token(user_id, settings: Settings) -> str:
    return create_access_token(
        subject=str(user_id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        samesite="lax",
    )


def build_router() -> APIRouter:
    """核心业务路由（根路径与 /api 双挂）。"""
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @router.post("/auth/token", response_model=TokenResponse)
    async def login(
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends(),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> TokenResponse:
        user = await authenticate(session, username=form_data.username, password=form_data.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await record_audit(session, user_id=user.id, action="login", source="api")
        await session.commit()
        token = _issue_token(user.id, settings)
        _set_session_cookie(response, token, settings)
        return TokenResponse(access_token=token)

    @router.post("/auth/logout", status_code=204)
    async def logout(response: Response) -> None:
        """登出：清 httpOnly cookie（Bearer 客户端自行丢弃 token）。"""
        response.delete_cookie(SESSION_COOKIE)

    @router.get("/auth/me", response_model=MeResponse)
    async def me(context: AccessContext = Depends(get_current_context)) -> MeResponse:
        return MeResponse(
            user_id=context.user_id,
            username=context.username,
            clearance=context.clearance.name,
            permissions=sorted(p.value for p in context.permissions),
            library_scopes=sorted(s.value for s in context.library_scopes),
            team_ids=sorted(context.team_ids, key=str),
            project_ids=sorted(context.project_ids, key=str),
        )

    @router.post("/auth/change-password", status_code=204)
    async def change_password_endpoint(
        req: ChangePasswordRequest,
        context: AccessContext = Depends(get_current_context),
        session: AsyncSession = Depends(get_session),
    ) -> None:
        ok = await change_password(
            session,
            user_id=context.user_id,
            old_password=req.old_password,
            new_password=req.new_password,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码不正确或账户已停用"
            )
        await record_audit(session, user_id=context.user_id, action="change_password", source="api")
        await session.commit()

    @router.post("/auth/register", response_model=MeResponse, status_code=201)
    async def register(
        req: RegisterRequest,
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> MeResponse:
        """自注册（默认关；开启时 clearance 上限 INTERNAL，防越权自提）。"""
        if not settings.allow_self_register:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自注册未开启")
        from calliodesmo.auth.service import get_user_by_username

        if await get_user_by_username(session, req.username) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        try:
            clearance = ClearanceLevel[req.clearance.upper()]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知 clearance"
            ) from None
        clearance = min(clearance, ClearanceLevel.INTERNAL)  # 上限 INTERNAL
        user = await create_user(
            session, username=req.username, password=req.password, clearance=clearance
        )
        await record_audit(session, user_id=user.id, action="register", source="api")
        await session.commit()
        return MeResponse(
            user_id=user.id,
            username=user.username,
            clearance=user.clearance.name,
            permissions=[],
            library_scopes=[],
            team_ids=[],
            project_ids=[],
        )

    @router.post("/query", response_model=QueryResponse)
    async def query(
        req: QueryRequest,
        context: AccessContext = Depends(get_current_context),
        engine: SearchEngine = Depends(get_search_engine),
        session: AsyncSession = Depends(get_session),
    ) -> QueryResponse:
        if not context.has_permission(Permission.QUERY):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
        # 验证 mode
        try:
            mode = SearchMode(req.mode)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"未知检索模式：{req.mode}（可选 native_rag / local / global）",
            ) from None
        answer = await engine.query(req.question, mode=mode, top_k=req.top_k, access=context)
        await record_audit(
            session,
            user_id=context.user_id,
            action="query",
            resource_type="answer",
            detail={"mode": req.mode, "sources": len(answer.source_chunk_ids)},
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

    return router


def create_app() -> FastAPI:
    app = FastAPI(title="Calliodesmo", version=__version__)

    core = build_router()
    app.include_router(core)
    app.include_router(admin_router)
    app.include_router(collab_router)
    app.include_router(ingest_router)
    app.include_router(library_router)
    app.include_router(query_image_router)
    # 双挂 /api 前缀：前端 baseURL 固定 /api（dev proxy 去前缀转发 / 生产同源）
    app.include_router(core, prefix="/api", include_in_schema=False)
    app.include_router(admin_router, prefix="/api", include_in_schema=False)
    app.include_router(collab_router, prefix="/api", include_in_schema=False)
    app.include_router(ingest_router, prefix="/api", include_in_schema=False)
    app.include_router(library_router, prefix="/api", include_in_schema=False)
    app.include_router(query_image_router, prefix="/api", include_in_schema=False)

    # 生产同源：前端构建产物静态托管（SPA fallback 到 index.html）；置于最后
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="spa")

    return app


app = create_app()
