"""FastAPI 应用工厂：健康检查 + JWT 认证 + Q&A 查询。"""

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo import __version__
from calliodesmo.api.deps import get_current_context, get_search_engine
from calliodesmo.api.schemas import MeResponse, QueryRequest, QueryResponse, TokenResponse
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import authenticate
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode


def create_app() -> FastAPI:
    app = FastAPI(title="Calliodesmo", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/auth/token", response_model=TokenResponse)
    async def login(
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
        return TokenResponse(
            access_token=create_access_token(
                subject=str(user.id),
                secret_key=settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
                expires_minutes=settings.jwt_expire_minutes,
            )
        )

    @app.get("/auth/me", response_model=MeResponse)
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

    @app.post("/query", response_model=QueryResponse)
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

    return app


app = create_app()
