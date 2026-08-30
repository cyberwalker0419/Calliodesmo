"""统一工具错误文案：越权与不存在同一消息（不泄漏存在性，roadmap 红线）。

注入防御不寄托提示词——派发层与数据层双保险：无权限工具经 ``list_for`` 对模型
不可见；直击越权 / 探测不存在均回同一文案，探测者无法推断工具是否存在。
"""

from __future__ import annotations

#: 越权 / 不存在共用文案（契约测试锁定二者不可区分）
TOOL_UNAVAILABLE_MESSAGE = "工具不可用或不存在。"


def tool_unavailable_error() -> str:
    """越权与不存在的统一错误消息——两路径必须经此构造，禁手写文案。"""
    return TOOL_UNAVAILABLE_MESSAGE


def parameter_validation_error(detail: str) -> str:
    """参数门（JSON Schema 校验）拒畸形入参文案——与存在性无关，可独立。"""
    return f"工具参数校验失败：{detail}"
