"""P9 Task 5：就绪探针 /readyz 与请求 ID 中间件。"""

from __future__ import annotations

import httpx

from calliodesmo.api import observability


class TestReadyz:
    async def test_ok_with_real_pg(self, client: httpx.AsyncClient):
        resp = await client.get("/readyz")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        by_name = {check["name"]: check for check in body["checks"]}
        assert by_name["database"]["status"] == "ok"
        assert by_name["config"]["status"] in {"ok", "warn"}
        # 不泄漏连接串与密钥
        assert "postgresql://" not in resp.text
        assert "asyncpg://" not in resp.text

    async def test_degraded_when_db_unreachable(self, client: httpx.AsyncClient, monkeypatch):
        async def _boom(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(observability, "check_database", _boom)
        resp = await client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        database = next(c for c in body["checks"] if c["name"] == "database")
        assert database["status"] == "fail"
        assert "connection refused" in database["detail"]

    async def test_config_errors_surface_as_fail(self, client: httpx.AsyncClient, monkeypatch):
        from calliodesmo.config_validation import ERROR

        monkeypatch.setattr(
            observability,
            "check_config",
            lambda: {
                "status": "fail",
                "detail": "存在 error 级配置问题",
                "issues": [{"level": ERROR, "code": "jwt_default_secret", "message": "默认密钥"}],
            },
        )
        resp = await client.get("/readyz")
        assert resp.status_code == 503
        assert any(c["name"] == "config" and c["status"] == "fail" for c in resp.json()["checks"])

    async def test_api_prefixed_route_available(self, client: httpx.AsyncClient):
        resp = await client.get("/api/readyz")
        assert resp.status_code in (200, 503)


class TestRequestId:
    async def test_generated_when_absent(self, client: httpx.AsyncClient):
        resp = await client.get("/healthz")
        request_id = resp.headers.get("x-request-id")
        assert request_id and len(request_id) >= 8

    async def test_inbound_value_echoed(self, client: httpx.AsyncClient):
        resp = await client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})
        assert resp.headers.get("x-request-id") == "trace-abc-123"

    async def test_overlong_inbound_value_replaced(self, client: httpx.AsyncClient):
        resp = await client.get("/healthz", headers={"X-Request-ID": "x" * 300})
        assert len(resp.headers.get("x-request-id")) <= 128

    async def test_error_response_also_carries_id(self, client: httpx.AsyncClient):
        resp = await client.get("/auth/me")  # 未认证 401
        assert resp.status_code == 401
        assert resp.headers.get("x-request-id")


class TestLivenessUnchanged:
    async def test_healthz_shape(self, client: httpx.AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["version"]
