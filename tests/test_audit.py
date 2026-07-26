from sqlalchemy import select

from calliodesmo.audit.models import AuditLog
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.service import create_user


async def test_record_audit(session):
    user = await create_user(session, username="dave", password="pw")
    entry = await record_audit(
        session,
        user_id=user.id,
        action="login",
        resource_type="session",
        detail={"ip": "127.0.0.1"},
        source="test",
    )
    await session.commit()

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "login"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].id == entry.id
    assert rows[0].user_id == user.id
    assert rows[0].detail == {"ip": "127.0.0.1"}
    assert rows[0].created_at is not None


async def test_record_audit_anonymous(session):
    await record_audit(session, user_id=None, action="failed_login", source="api")
    await session.commit()
    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
