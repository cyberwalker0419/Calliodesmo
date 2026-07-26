"""FastAPI 应用工厂：P0 暴露健康检查与 JWT 认证链路（Q&A 端点属 P2）。"""

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo import __version__
from calliodesmo.api.deps import get_current_context
from calliodesmo.api.schemas import MeResponse, TokenResponse
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import authenticate
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session


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
            group_ids=sorted(context.group_ids, key=str),
        )

    return app


app = create_app()
