"""FastAPI 依赖：当前 AccessContext 解析 + SearchEngine 注入。"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.security import decode_access_token
from calliodesmo.auth.service import get_access_context
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="无效或过期的凭证",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_context(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessContext:
    try:
        payload = decode_access_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc
    context = await get_access_context(session, user_id)
    if context is None:
        raise _CREDENTIALS_EXCEPTION
    return context


async def get_search_engine() -> SearchEngine:
    """默认 SearchEngine 依赖。生产环境应注入实际引擎；测试用 dependency_overrides 覆盖。"""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="SearchEngine 未配置（需通过依赖注入或 dependency_overrides 提供）",
    )
