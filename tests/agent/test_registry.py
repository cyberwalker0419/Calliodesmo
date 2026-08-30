"""P7 T5：agent 域契约冻结 + 工具注册表 + 三维权限门控。

锁红线：越权与不存在同一错误消息（不可区分、不泄漏存在性）；权限门预过滤；
参数门拒畸形；每次 dispatch 留审计；三角色 × 四密级 × 三 scope 矩阵对齐
DEFAULT_ROLE_PERMISSIONS。
"""

import uuid
from dataclasses import FrozenInstanceError

import pytest

from calliodesmo.agent.errors import tool_unavailable_error
from calliodesmo.agent.registry import DefaultToolRegistry, validate_arguments
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    ClearanceLevel,
    LibraryScope,
    Permission,
)
from calliodesmo.interfaces.agent import (
    AgentEngine,
    AgentMode,
    AgentTool,
    ToolCall,
    ToolResult,
    ToolSpec,
    TurnResult,
)

_SEARCH_SPEC = ToolSpec(
    name="search_knowledge",
    description="检索",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}, "top_k": {"type": "integer"}},
        "required": ["question"],
    },
)
_ANALYZE_SPEC = ToolSpec(
    name="run_analysis",
    description="分析",
    parameters={"type": "object", "properties": {}, "required": []},
)


class _FakeTool:
    def __init__(self, spec: ToolSpec, permission: Permission, *, boom: bool = False):
        self.spec = spec
        self.required_permission = permission
        self.boom = boom
        self.calls: list[tuple[dict, AccessContext]] = []

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        if self.boom:
            raise RuntimeError("数据层内部错误（不得泄漏）")
        self.calls.append((arguments, access))
        return f"output:{arguments.get('question', '')}"


def _ctx(perms: set[Permission], clearance=ClearanceLevel.INTERNAL, scope=LibraryScope.PERSONAL):
    return AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=clearance,
        permissions=frozenset(perms),
        library_scopes=frozenset({scope}),
    )


def _registry(audit: list | None = None, boom: bool = False):
    search = _FakeTool(_SEARCH_SPEC, Permission.QUERY)
    analyze = _FakeTool(_ANALYZE_SPEC, Permission.ANALYZE, boom=boom)

    async def hook(access, action, detail):
        if audit is not None:
            audit.append((access.user_id, action, detail))

    reg = DefaultToolRegistry([search, analyze], audit_hook=hook)
    return reg, search, analyze


# ---- 契约冻结 ----


def test_contract_frozen_and_enum():
    """ToolResult / TurnResult frozen；AgentMode 预留 rewoo；AgentEngine 为 ABC。"""
    tr = ToolResult(tool_call_id="c", name="n", ok=True, output="o", error=None)
    with pytest.raises(FrozenInstanceError):
        tr.ok = False
    turn = TurnResult(answer="a", tool_trace=(), steps=1, usage={}, warnings=[], status="ok")
    with pytest.raises(FrozenInstanceError):
        turn.status = "failed"
    assert AgentMode.REWOO == "rewoo"  # 预留值（⏸ 暂缓，锚点 2026-W49）
    assert AgentMode.REACT == "react"
    with pytest.raises(TypeError):
        AgentEngine()  # ABC 不可实例化


def test_agent_tool_protocol_runtime_checkable():
    search = _FakeTool(_SEARCH_SPEC, Permission.QUERY)
    assert isinstance(search, AgentTool)


# ---- 权限门 ----


def test_list_for_prefilters_by_permission():
    reg, _, _ = _registry()
    assert [s.name for s in reg.list_for(_ctx(set()))] == []
    assert [s.name for s in reg.list_for(_ctx({Permission.QUERY}))] == ["search_knowledge"]
    both = reg.list_for(_ctx({Permission.QUERY, Permission.ANALYZE}))
    assert {s.name for s in both} == {"search_knowledge", "run_analysis"}


# ---- 越权 / 不存在不可区分 ----


async def test_dispatch_denied_and_missing_indistinguishable():
    """红线：越权 dispatch 与不存在工具错误文本逐字相同；两次均留审计。"""
    audit: list = []
    reg, _, _ = _registry(audit)
    no_perm = _ctx(set())

    denied = await reg.dispatch(
        ToolCall(id="c1", name="search_knowledge", arguments={"question": "q"}), access=no_perm
    )
    missing = await reg.dispatch(ToolCall(id="c2", name="ghost_tool", arguments={}), access=no_perm)

    assert denied.ok is False and missing.ok is False
    assert denied.error == missing.error == tool_unavailable_error()
    assert len(audit) == 2  # 越权探测也留审计
    assert audit[0][1] == "agent_tool" and audit[1][1] == "agent_tool"


# ---- 参数门 ----


async def test_dispatch_parameter_gate_rejects_malformed():
    reg, _, _ = _registry()
    access = _ctx({Permission.QUERY})

    call = ToolCall(id="c1", name="search_knowledge", arguments={})
    missing_req = await reg.dispatch(call, access=access)
    assert missing_req.ok is False
    assert "缺少必需参数 question" in missing_req.error
    assert missing_req.error != tool_unavailable_error()  # 参数门文案独立于存在性文案

    bad_type = await reg.dispatch(
        ToolCall(id="c2", name="search_knowledge", arguments={"question": "q", "top_k": "三"}),
        access=access,
    )
    assert bad_type.ok is False and "top_k" in bad_type.error

    bool_not_int = await reg.dispatch(
        ToolCall(id="c3", name="search_knowledge", arguments={"question": "q", "top_k": True}),
        access=access,
    )
    assert bool_not_int.ok is False  # bool 是 int 子类须显式排除


def test_validate_arguments_pure():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert validate_arguments(schema, {"n": 1}) is None
    assert validate_arguments(schema, {}) is not None
    assert validate_arguments(schema, "not-dict") is not None
    assert validate_arguments(schema, {"n": 1.5}) is not None


# ---- 正常派发 / 执行异常 ----


async def test_dispatch_success_passes_access_and_audits():
    audit: list = []
    reg, search, _ = _registry(audit)
    access = _ctx({Permission.QUERY})
    result = await reg.dispatch(
        ToolCall(id="c1", name="search_knowledge", arguments={"question": "q"}), access=access
    )
    assert result.ok is True and result.output == "output:q" and result.error is None
    assert search.calls[0][1] is access  # access 全程传参（审计溯源 + 数据门）
    assert audit[-1][2]["ok"] is True


async def test_dispatch_run_error_unified_message():
    """数据层异常不泄漏内部结构，同收统一消息。"""
    reg, _, _ = _registry(boom=True)
    access = _ctx({Permission.QUERY, Permission.ANALYZE})
    result = await reg.dispatch(ToolCall(id="c1", name="run_analysis", arguments={}), access=access)
    assert result.ok is False and result.error == tool_unavailable_error()


# ---- 三角色 × 四密级 × 三 scope 矩阵 ----


@pytest.mark.parametrize("role", sorted(DEFAULT_ROLE_PERMISSIONS))
@pytest.mark.parametrize("clearance", list(ClearanceLevel))
@pytest.mark.parametrize("scope", list(LibraryScope))
def test_permission_matrix_list_for(role, clearance, scope):
    """可见工具集 = 角色权限派生（与密级 / scope 正交：工具门仅角色权限维度）。"""
    perms = DEFAULT_ROLE_PERMISSIONS[role]
    reg, _, _ = _registry()
    visible = {s.name for s in reg.list_for(_ctx(set(perms), clearance, scope))}
    expected = set()
    if Permission.QUERY in perms:
        expected.add("search_knowledge")
    if Permission.ANALYZE in perms:
        expected.add("run_analysis")
    assert visible == expected


async def test_validate_arguments_enum():
    """参数门 enum 校验（P8 T8 补：task_type 枚举外拒收）。"""
    schema = {"type": "object", "properties": {"t": {"type": "string", "enum": ["a", "b"]}}}
    assert validate_arguments(schema, {"t": "a"}) is None
    assert validate_arguments(schema, {"t": "zz"}) is not None
