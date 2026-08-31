"""P7 T12：多轮状态 × 三维权限交叉专项（会话跨密级泄漏 = 本阶段最高危风险）。

- 密级降级后读旧会话 False（密级不洗白：当前 clearance >= 建时）；
- scope 移除后不可见；跨用户会话不可见（404 不泄漏存在性，API 层 T14）；
- 落库前密级断言钩子 fail-fast；
- 历史滑动窗口截断（系统提示恒留 + 最近 N 回合 + warning）；
- 注入探针回归（语料内嵌指令诱导越权，期望零成功）。
"""

import uuid

import pytest

from calliodesmo.agent.access import (
    ClearanceViolationError,
    assert_evidence_within_session,
    verify_session_access,
)
from calliodesmo.agent.graph import ReActAgentEngine
from calliodesmo.agent.history import truncate_history
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_agent import AgentSessionORM
from calliodesmo.eval.agent_harness import (
    DEFAULT_GOLDEN_FILE,
    build_eval_access,
    build_eval_registry,
    load_golden,
    run_scenario,
)
from calliodesmo.providers.stub_llm import StubLLMProvider

OWNER = uuid.uuid4()
TEAM = uuid.uuid4()


def _session(owner=OWNER, scope=LibraryScope.PERSONAL, at_create=ClearanceLevel.SECRET):
    return AgentSessionORM(
        owner_id=owner,
        access_level=ClearanceLevel.INTERNAL,  # transient 对象列默认值不生效，显式补
        library_scope=scope,
        team_id=TEAM if scope == LibraryScope.TEAM else None,
        project_id=None,
        clearance_at_create=at_create,
        scope_at_create=scope,
    )


def _access(user=OWNER, clearance=ClearanceLevel.SECRET, teams=(), scopes=(LibraryScope.PERSONAL,)):
    from calliodesmo.auth.context import AccessContext

    return AccessContext(
        user_id=user,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        library_scopes=frozenset(scopes),
        team_ids=frozenset(teams),
    )


# ---- 密级不洗白 × scope 移除 × 跨用户 ----


@pytest.mark.parametrize("role_clearance", list(ClearanceLevel))
def test_verify_session_clearance_no_whitewash(role_clearance):
    """建时 SECRET 的会话：当前 clearance >= SECRET 才可见（降级即拒）。"""
    row = _session(at_create=ClearanceLevel.SECRET)
    ok = verify_session_access(row, access=_access(clearance=role_clearance))
    assert ok == (role_clearance >= ClearanceLevel.SECRET)


def test_verify_session_scope_removed():
    """team scope 移除后不可见（scope 维度独立于密级）。"""
    row = _session(scope=LibraryScope.TEAM)
    with_team = _access(
        clearance=ClearanceLevel.SECRET,
        teams=(TEAM,),
        scopes=(LibraryScope.PERSONAL, LibraryScope.TEAM),
    )
    without_team = _access(clearance=ClearanceLevel.SECRET)
    assert verify_session_access(row, access=with_team) is True
    assert verify_session_access(row, access=without_team) is False


def test_verify_session_cross_user_hidden():
    """跨用户 personal 会话不可见（404 同语义，不泄漏存在性）。"""
    row = _session()
    stranger = _access(user=uuid.uuid4(), clearance=ClearanceLevel.SECRET)
    assert verify_session_access(row, access=stranger) is False


# ---- 落库前密级断言钩子 ----


def test_assert_evidence_within_session():
    assert_evidence_within_session(
        ClearanceLevel.INTERNAL, session_level=ClearanceLevel.INTERNAL
    )  # 相等放行
    with pytest.raises(ClearanceViolationError):
        assert_evidence_within_session(ClearanceLevel.SECRET, session_level=ClearanceLevel.INTERNAL)


# ---- 历史滑动窗口 ----


def _msgs(n_turns: int):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    out: list = [SystemMessage(content="sys")]
    for i in range(n_turns):
        out.append(HumanMessage(content=f"q{i}"))
        out.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"id": f"c{i}", "name": "search_knowledge", "args": {}, "type": "tool_call"}
                ],
            )
        )
        out.append(ToolMessage(content="r", tool_call_id=f"c{i}"))
        out.append(AIMessage(content=f"a{i}"))
    return out


def test_truncate_history_keeps_system_and_window():
    msgs = _msgs(5)
    kept, truncated = truncate_history(msgs, window=2)
    assert truncated is True
    assert kept[0].type == "system"  # 系统提示恒留
    humans = [m for m in kept if m.type == "human"]
    assert [h.content for h in humans] == ["q3", "q4"]  # 最近两回合
    # 无孤儿 tool/ai：截断边界必为 human 起界
    assert kept[1].type == "human"


def test_truncate_history_within_window_noop():
    msgs = _msgs(2)
    kept, truncated = truncate_history(msgs, window=3)
    assert truncated is False
    assert kept == msgs


async def test_graph_history_truncated_warning():
    """窗口=1 多轮续接：模型节点加 history_truncated warning（模型可感知）。"""
    engine = ReActAgentEngine(StubLLMProvider(), build_eval_registry(), history_window=1)
    access = build_eval_access(["query", "analyze"])
    tid = str(uuid.uuid4())
    for i in range(3):
        turn = await engine.run_turn(
            question=f"第{i}轮", thread_id=tid, access=access, system="[AGENT:insufficient_direct]"
        )
    assert "history_truncated" in turn.warnings


# ---- 注入探针回归 ----


async def test_injection_probe_zero_induction_regression():
    """语料内嵌指令诱导越权工具调用：期望零成功（T9 槽位回归）。"""
    scenario = next(s for s in load_golden(DEFAULT_GOLDEN_FILE) if s["id"] == "injection_probe")
    result = await run_scenario(scenario)
    assert not any(c.name == "run_analysis" and r.ok for c, r in result["trace"])
    assert "job_id=" not in result["answer"]
