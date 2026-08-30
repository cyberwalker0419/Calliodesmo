"""FastAPI 依赖：当前 AccessContext 解析 + 内存 stores 单例工厂 + SearchEngine 注入。"""

import uuid
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.auth.security import decode_access_token
from calliodesmo.auth.service import get_access_context
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine

#: JWT httpOnly 会话 cookie 名（SameSite=Lax；防 XSS 读 token）。P3 设计：
#: cookie 为前端会话主路径，Bearer 仅 CLI/脚本（见 phases/P3-web-ui.md Task 5）。
#: 登录写入（app.py ``_set_session_cookie``）；``get_current_context`` 消费。
SESSION_COOKIE = "calliodesmo_session"

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

        settings = get_settings()
        # P4.5 Task 2：真后端路由（config 驱动）；默认 memory 兼容旧测试
        if self.vector_store is None:
            if settings.vector_store_backend == "postgres":
                from calliodesmo.db.session import SessionLocal
                from calliodesmo.providers.pg_vector_store import PgVectorStore

                self.vector_store = PgVectorStore(SessionLocal)
            else:
                self.vector_store = InMemoryVectorStore()
        if self.graph_store is None:
            if settings.graph_store_backend == "neo4j":
                from neo4j import AsyncGraphDatabase

                from calliodesmo.db.session import SessionLocal
                from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore

                driver = AsyncGraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                self.graph_store = Neo4jGraphStore(driver, SessionLocal)
            else:
                self.graph_store = InMemoryGraphStore()
        if self.community_store is None:
            if settings.community_store_backend == "postgres":
                from calliodesmo.db.session import SessionLocal
                from calliodesmo.providers.pg_community_store import PgCommunityStore

                self.community_store = PgCommunityStore(SessionLocal)
            else:
                self.community_store = InMemoryCommunityStore()
        # TODO(P9, 2026-W49)：ProfileCard 与 BM25 改 PG 数据源——与三 store list 谓词下推同批。
        # （原锚点 2026-W33 逾期，P6 Task 1 显式顺延：P6 材料路径不依赖 BM25。）
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
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessContext:
    if not token:
        # 无 Bearer 头时回退同源会话 cookie（P3 设计 cookie 为前端主路径）：
        # 裸 ``<a href>`` 附件下载等浏览器导航不带 Authorization 头，仅携
        # httpOnly cookie（SameSite=Lax 防跨站子资源 CSRF）。Bearer 优先，
        # 二者皆无 / 无效 -> 401。
        token = request.cookies.get(SESSION_COOKIE)
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
    from calliodesmo.retrieval.factory import build_default_search_engine, build_reranker

    settings = get_settings()
    try:
        engine = build_default_search_engine(
            settings,
            vector_store=stores.vector_store,
            graph_store=stores.graph_store,
            community_store=stores.community_store,
            sparse_index=stores.sparse_index,
            reranker=build_reranker(settings),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    stores.search_engine = engine
    return engine


async def get_vision_provider():
    """识图 VLM provider（/query/with-image 用）；按配置路由，测试可经依赖覆盖为桩。"""
    from calliodesmo.retrieval.factory import build_vision_provider

    return build_vision_provider(get_settings())


def get_job_session_factory():
    """后台 job worker 的 session 工厂（默认生产 SessionLocal；测试可覆盖为测试 schema）。

    P4.5 Task 5：worker 无请求上下文，须自建 session 落 job 状态/审计；经依赖注入
    暴露，测试（conftest 专用 schema 隔离）可 override 指向测试 engine。
    """
    from calliodesmo.db.session import SessionLocal

    return SessionLocal
