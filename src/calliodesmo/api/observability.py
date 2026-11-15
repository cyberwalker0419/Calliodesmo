"""可观测性最小集：就绪探针 ``/readyz`` + 请求 ID 中间件（P9 Task 5）。

分工：

- ``/healthz`` 是**存活**探针（进程在跑就 200，零依赖，给 compose/k8s liveness 用）；
- ``/readyz`` 是**就绪**探针：逐组件自检并给出明细（数据库连通、图库连通、配置校验、
  可选 extra），任一 ``fail`` 即 503，供 load-balancer / 引导脚本判断「能不能接流量」；
  出参只含状态与可读说明，**不回显连接串与密钥**；
- 请求 ID 中间件：入站带 ``X-Request-ID`` 就沿用（便于全链路串联），否则生成；写回
  响应头并挂到 ``request.state``，访问日志同行输出，便于把用户报障与审计/日志对齐。

探活一律带超时（``CHECK_TIMEOUT_SECONDS``），避免依赖不可达时把探针拖成慢请求。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from calliodesmo import __version__
from calliodesmo.config import Settings, get_settings
from calliodesmo.config_validation import summarize, validate_settings
from calliodesmo.db.session import get_session

#: 请求 ID 头名（入站沿用 / 出站回显）
REQUEST_ID_HEADER = "X-Request-ID"
#: 入站 ID 合法形态与长度上限（防日志注入 / 超长头）
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
#: 单项探活超时（秒）
CHECK_TIMEOUT_SECONDS = 3.0

logger = logging.getLogger("calliodesmo.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """请求 ID 贯穿 + 单行访问日志（method / path / status / 耗时 / rid）。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming or "") else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("请求异常 %s %s rid=%s", request.method, request.url.path, request_id)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "http %s %s -> %s %.1fms rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response


async def check_database(session: AsyncSession) -> dict[str, Any]:
    """数据库探活：``SELECT 1``（带超时），失败即 fail。"""
    await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=CHECK_TIMEOUT_SECONDS)
    return {"name": "database", "status": "ok", "detail": "PostgreSQL 可达"}


def check_config(settings: Settings) -> dict[str, Any]:
    """配置体检：error 级问题判 fail，warn 级判 warn，否则 ok（只报 code，不回显值）。"""
    issues = validate_settings(settings)
    summary = summarize(issues)
    status = "fail" if summary["errors"] else ("warn" if issues else "ok")
    return {
        "name": "config",
        "status": status,
        "detail": f"error={summary['errors']} warn={summary['warnings']} info={summary['infos']}",
        "codes": sorted({issue.code for issue in issues}),
    }


async def check_graph(settings: Settings) -> dict[str, Any]:
    """图库探活：backend=neo4j 时 verify_connectivity；memory 后端判 skipped。"""
    if settings.graph_store_backend != "neo4j":
        return {"name": "graph", "status": "skipped", "detail": "graph_store_backend=memory"}
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
        try:
            await asyncio.wait_for(driver.verify_connectivity(), timeout=CHECK_TIMEOUT_SECONDS)  # type: ignore[misc]
        finally:
            await driver.close()
        return {"name": "graph", "status": "ok", "detail": "Neo4j 可达"}
    except Exception as exc:  # 连接 / 认证 / 依赖缺失都归 fail（detail 不含凭据）
        return {"name": "graph", "status": "fail", "detail": f"{type(exc).__name__}: {exc}"[:200]}


def check_optional_extras() -> dict[str, Any]:
    """可选 extra 探测：agent 家族缺失时 agent 面 503（其余面照常），如实报 skipped。"""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return {
            "name": "agent_extra",
            "status": "skipped",
            "detail": "未装 agent extra（Agent 面不可用）：`uv sync --extra agent`",
        }
    return {"name": "agent_extra", "status": "ok", "detail": "LangGraph 可用"}


async def run_check(
    name: str, run: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]]
) -> dict:
    """执行单项检查并把异常转成 fail 明细（探针本身不能 500）。"""
    try:
        result = run()
        if asyncio.iscoroutine(result):
            result = await result  # type: ignore[misc]
        return result
    except Exception as exc:  # asyncio.TimeoutError 等同样归入 fail
        return {"name": name, "status": "fail", "detail": f"{type(exc).__name__}: {exc}"[:200]}


def build_observability_router() -> APIRouter:
    """就绪探针路由（根路径与 ``/api`` 双挂，与业务路由同规则）。"""
    router = APIRouter()

    @router.get("/readyz")
    async def readyz(
        request: Request,
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> JSONResponse:
        checks = [
            await run_check("database", lambda: check_database(session)),
            await run_check("graph", lambda: check_graph(settings)),
            await run_check("config", lambda: check_config(settings)),
            await run_check("agent_extra", check_optional_extras),
        ]
        degraded = any(check["status"] == "fail" for check in checks)
        return JSONResponse(
            status_code=503 if degraded else 200,
            content={
                "status": "degraded" if degraded else "ok",
                "version": __version__,
                "request_id": getattr(request.state, "request_id", None),
                "checks": checks,
            },
        )

    return router


__all__ = [
    "CHECK_TIMEOUT_SECONDS",
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "build_observability_router",
    "check_config",
    "check_database",
    "check_graph",
    "check_optional_extras",
    "run_check",
]
