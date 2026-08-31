"""工具输出渲染公共件：截断 + 引注口径（防上下文打爆与注入放大）。"""

from __future__ import annotations

#: 单条内容截断上限（字符）——工具结果入 prompt 前的长度纪律
ITEM_LIMIT = 400
#: 单工具输出总上限（字符）
OUTPUT_LIMIT = 4000


def truncate(text: str, limit: int = ITEM_LIMIT) -> str:
    """超长截断并标注（模型可感知截断，不伪装完整）。"""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…[截断]"


def clip_output(text: str) -> str:
    """工具输出总长截断（防多条目叠加打爆上下文）。"""
    return truncate(text, OUTPUT_LIMIT)


def join_lines(lines: list[str]) -> str:
    return clip_output("\n".join(lines))
