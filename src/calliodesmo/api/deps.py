"""FastAPI 依赖：当前 AccessContext 解析（JWT -> AccessContext）。"""

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
