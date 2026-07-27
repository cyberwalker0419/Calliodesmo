"""FastAPI 依赖：当前 AccessContext 解析 + 内存 stores 单例工厂 + SearchEngine 注入。"""

import uuid
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.auth.security import decode_access_token
from calliodesmo.auth.service import get_access_context
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="无效或过期的凭证",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_permission(ctx: AccessContext, permission: Permission) -> None:
    """权限守卫 helper：有权放行，无权 403。后端为权限唯一真相。"""
    if not ctx.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限：{permission.value}"
        )


@dataclass
class AppStores:
    """API 进程内存 stores 单例容器：ingest/query/browse 同进程共享。

    prod 持久化（Postgres/pgvector/Neo4j）随真后端落地（P9）；内存模式为默认。
    """

    vector_store: object = field(default=None)
    graph_store: object = field(default=None)
    community_store: object = field(default=None)
    profile_card_store: object = field(default=None)
    sparse_index: object = field(default=None)
    search_engine: object = field(default=None)

    def __post_init__(self) -> None:
        from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
        from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
        from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
        from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index
        from calliodesmo.stores.profile_card_store import InMemoryProfileCardStore

        if self.vector_store is None:
            self.vector_store = InMemoryVectorStore()
        if self.graph_store is None:
            self.graph_store = InMemoryGraphStore()
        if self.community_store is None:
            self.community_store = InMemoryCommunityStore()
        if self.profile_card_store is None:
            self.profile_card_store = InMemoryProfileCardStore()
        if self.sparse_index is None:
            self.sparse_index = InMemoryBM25Index()


_app_stores: AppStores | None = None


def get_app_stores() -> AppStores:
    """内存 stores 单例工厂（serve --seed-demo 与 query/browse 共享同一实例）。"""
    global _app_stores
    if _app_stores is None:
        _app_stores = AppStores()
    return _app_stores


def reset_app_stores() -> None:
    """测试隔离：清空单例（每个用例独立 stores）。"""
    global _app_stores
    _app_stores = None


async def get_current_context(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessContext:
    if not token:
        raise _CREDENTIALS_EXCEPTION
    try:
        payload = decode_access_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc
    context = await get_access_context(session, user_id)
    if context is None:
        raise _CREDENTIALS_EXCEPTION
    return context


async def get_profile_card_store():
    return get_app_stores().profile_card_store


async def get_graph_store():
    return get_app_stores().graph_store


async def get_community_store():
    return get_app_stores().community_store


async def get_vector_store():
    return get_app_stores().vector_store


async def get_search_engine() -> SearchEngine:
    """默认 SearchEngine：在共享内存 stores 单例上装配（缓存复用）。

    LLM/嵌入按配置路由；非豁免后端缺 key -> 503 并给出配置指引。
    """
    stores = get_app_stores()
    if stores.search_engine is not None:
        return stores.search_engine
    from calliodesmo.retrieval.factory import build_default_search_engine

    try:
        engine = build_default_search_engine(
            get_settings(),
            vector_store=stores.vector_store,
            graph_store=stores.graph_store,
            community_store=stores.community_store,
            sparse_index=stores.sparse_index,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    stores.search_engine = engine
    return engine
