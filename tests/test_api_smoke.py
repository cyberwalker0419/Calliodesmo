from sqlalchemy import select

from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_auth_flow(client, session):
    await seed_default_roles(session)
    user = await create_user(
        session, username="erin", password="pw123", clearance=ClearanceLevel.CONFIDENTIAL
    )
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.TEAM)
    await session.commit()

    resp = await client.post("/auth/token", data={"username": "erin", "password": "pw123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert resp.json()["token_type"] == "bearer"

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "erin"
    assert body["clearance"] == "CONFIDENTIAL"
    assert "ingest" in body["permissions"]
    assert "team" in body["library_scopes"]

    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "login"))).scalars().all()
    )
    assert len(logs) == 1
    assert logs[0].user_id == user.id


async def test_auth_wrong_password(client, session):
    await create_user(session, username="frank", password="pw")
    await session.commit()
    resp = await client.post("/auth/token", data={"username": "frank", "password": "nope"})
    assert resp.status_code == 401


async def test_me_requires_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_via_session_cookie(client, session):
    """cookie 会话为主路径（P3 设计：Bearer 仅 CLI/脚本，不作前端主路径）。

    /auth/token 下发 httpOnly cookie 后，无 Authorization 头的同源请求
    （如裸 ``<a href>`` 附件下载导航）经 ``calliodesmo_session`` cookie 鉴权。
    """
    from calliodesmo.api.app import SESSION_COOKIE

    await seed_default_roles(session)
    user = await create_user(
        session, username="gina", password="pw123", clearance=ClearanceLevel.CONFIDENTIAL
    )
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.TEAM)
    await session.commit()

    resp = await client.post("/auth/token", data={"username": "gina", "password": "pw123"})
    assert resp.status_code == 200
    assert SESSION_COOKIE in resp.cookies

    # 无 Authorization 头：cookie jar 自动携带会话 cookie -> 200
    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "gina"


async def test_me_bad_session_cookie(client):
    """伪造 / 篡改的会话 cookie -> 401（与无效 Bearer 同口径）。"""
    from calliodesmo.api.app import SESSION_COOKIE

    client.cookies.set(SESSION_COOKIE, "forged.token.value")
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
