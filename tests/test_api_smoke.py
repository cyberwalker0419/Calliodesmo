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
