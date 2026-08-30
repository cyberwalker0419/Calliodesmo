"""工具注册表：三道闸之权限门（``list_for`` 预过滤）+ 参数门（JSON Schema 校验）+ 审计钩子。

- 权限门：无权限工具对模型不可见（``list_for(access)`` 只回授权集）。
- 参数门：按 ``ToolSpec.parameters`` 最小 JSON Schema 校验拒畸形入参（纯函数零依赖；
  完整 jsonschema 校验留 T17/T18 评估口径）。
- 数据门在工具实现侧（store ``visible_to``，T7；``get_chunk`` 工具层自补）。
越权 / 不存在 dispatch 同一错误消息（不泄漏存在性）；每次 dispatch 经审计钩子
（worker 装配 ``record_audit``，离线测试注入记录器）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from calliodesmo.agent.errors import parameter_validation_error, tool_unavailable_error
from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.agent import ToolCall, ToolResult, ToolSpec

#: 审计钩子：(access, action, detail)；worker 装配 audit.service.record_audit
AuditHook = Callable[[AccessContext, str, dict[str, Any]], Awaitable[None]]

#: 最小 JSON Schema 类型映射（bool 是 int 子类，integer 须显式排除）
_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_arguments(schema: dict, arguments: Any) -> str | None:
    """最小 JSON Schema 校验（纯函数）：通过回 None，否则回失败原因。"""
    if schema.get("type", "object") == "object" and not isinstance(arguments, dict):
        return "arguments 须为 object"
    if not isinstance(arguments, dict):
        return None
    for req in schema.get("required", []) or []:
        if req not in arguments:
            return f"缺少必需参数 {req}"
    for name, prop in (schema.get("properties") or {}).items():
        if name not in arguments:
            continue
        expected = prop.get("type") if isinstance(prop, dict) else None
        py = _JSON_TYPES.get(expected or "")
        if py is None:
            continue
        value = arguments[name]
        if isinstance(value, bool) and expected in ("integer", "number"):
            return f"参数 {name} 类型须为 {expected}"
        if not isinstance(value, py):
            return f"参数 {name} 类型须为 {expected}"
    return None


class DefaultToolRegistry:
    """agent 工具注册表：权限预过滤 + 参数校验 + 统一错误 + 审计钩子。"""

    def __init__(self, tools: list, *, audit_hook: AuditHook | None = None) -> None:
        self._tools = {t.spec.name: t for t in tools}
        self._audit_hook = audit_hook

    def list_for(self, access: AccessContext) -> list[ToolSpec]:
        """权限门预过滤：模型可见集 = 当前 access 授权集（无权限工具不可见）。"""
        return [
            t.spec for t in self._tools.values() if access.has_permission(t.required_permission)
        ]

    def get(self, name: str):
        return self._tools.get(name)

    async def dispatch(self, call: ToolCall, *, access: AccessContext) -> ToolResult:
        """派发工具调用：越权 / 不存在同一消息；参数门拒畸形；执行异常同收统一消息。"""
        tool = self._tools.get(call.name)
        permitted = tool is not None and access.has_permission(tool.required_permission)
        if not permitted:
            # 红线：越权与不存在不区分、不泄漏存在性
            await self._audit(access, {"tool": call.name, "ok": False, "reason": "unavailable"})
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                ok=False,
                output="",
                error=tool_unavailable_error(),
            )

        err = validate_arguments(tool.spec.parameters, call.arguments)
        if err is not None:
            await self._audit(
                access, {"tool": call.name, "ok": False, "reason": "bad_arguments", "detail": err}
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                ok=False,
                output="",
                error=parameter_validation_error(err),
            )

        try:
            output = await tool.run(call.arguments, access=access)
        except Exception:
            # 数据层异常不泄漏内部结构，同收统一消息
            await self._audit(access, {"tool": call.name, "ok": False, "reason": "run_error"})
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                ok=False,
                output="",
                error=tool_unavailable_error(),
            )

        await self._audit(access, {"tool": call.name, "ok": True})
        return ToolResult(tool_call_id=call.id, name=call.name, ok=True, output=output, error=None)

    async def _audit(self, access: AccessContext, detail: dict[str, Any]) -> None:
        if self._audit_hook is not None:
            await self._audit_hook(access, "agent_tool", detail)
