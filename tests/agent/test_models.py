"""P7 T11：会话 ORM 三表建/读 + migrate 幂等（@pytest.mark.db）。"""

import uuid

from sqlalchemy import select

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.migrate import ensure_missing_columns
from calliodesmo.db.models_agent import AgentMessageORM, AgentRunORM, AgentSessionORM


async def test_agent_session_defaults_and_snapshot(session):
    """五 access 字段默认 personal + 创建时 clearance / scope 快照。"""
    owner = uuid.uuid4()
    sess = AgentSessionORM(
        owner_id=owner,
        mode="react",
        label="会话一",
        clearance_at_create=ClearanceLevel.SECRET,
        scope_at_create=LibraryScope.TEAM,
    )
    session.add(sess)
    await session.commit()

    got = (await session.execute(select(AgentSessionORM))).scalar_one()
    assert got.owner_id == owner
    assert got.mode == "react"
    # 五字段默认 personal 口径
    assert got.access_level == ClearanceLevel.INTERNAL
    assert got.library_scope == LibraryScope.PERSONAL
    assert got.project_id is None and got.team_id is None
    # 快照保留建时密级 / scope（密级不洗白依据，T12 复检）
    assert got.clearance_at_create == ClearanceLevel.SECRET
    assert got.scope_at_create == LibraryScope.TEAM


async def test_agent_message_and_run_roundtrip(session):
    """消息 / 执行建读：轨迹 JSON + usage + 状态枚举口径。"""
    sid = uuid.uuid4()
    run = AgentRunORM(
        id=uuid.uuid4(),
        session_id=sid,
        status="succeeded",
        tool_trace=[{"call": {"id": "c1", "name": "search_knowledge"}, "result": {"ok": True}}],
        usage={"total_tokens": 42},
        steps=2,
    )
    msg_user = AgentMessageORM(session_id=sid, role="user", content="问题")
    msg_ai = AgentMessageORM(session_id=sid, role="assistant", content="回答", run_id=run.id)
    session.add_all([run, msg_user, msg_ai])
    await session.commit()

    msgs = (
        (await session.execute(select(AgentMessageORM).where(AgentMessageORM.session_id == sid)))
        .scalars()
        .all()
    )
    assert {m.role for m in msgs} == {"user", "assistant"}
    got_run = await session.get(AgentRunORM, run.id)
    assert got_run.status == "succeeded"
    assert got_run.tool_trace[0]["call"]["name"] == "search_knowledge"
    assert got_run.usage == {"total_tokens": 42}
    assert got_run.steps == 2
    assert got_run.error is None


async def test_migrate_idempotent_with_agent_tables(session):
    """ensure_missing_columns 双跑幂等（agent 新表经 create_all，补列路径不冲突）。"""
    await ensure_missing_columns(session.bind)
    await ensure_missing_columns(session.bind)  # 二跑不抛 = 幂等
