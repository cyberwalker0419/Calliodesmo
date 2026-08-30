"""历史滑动窗口截断：系统提示恒留 + 最近 N 回合（P7 T12，防上下文溢出）。

纯函数；回合以 human 消息起界（tool / ai 跟随其后），截断不产生孤儿
tool / ai 消息。截断时回 ``truncated=True``（图节点加 warning
``history_truncated``，模型可感知窗口）。
"""

from __future__ import annotations

from typing import Any


def _split_turns(rest: list[Any]) -> list[list[Any]]:
    turns: list[list[Any]] = []
    current: list[Any] = []
    for m in rest:
        if getattr(m, "type", "") == "human" and current:
            turns.append(current)
            current = []
        current.append(m)
    if current:
        turns.append(current)
    return turns


def truncate_history(messages: list[Any], *, window: int) -> tuple[list[Any], bool]:
    """保留系统提示 + 最近 ``window`` 回合；未超窗原样返回（truncated=False）。"""
    systems = [m for m in messages if getattr(m, "type", "") == "system"]
    rest = [m for m in messages if getattr(m, "type", "") != "system"]
    turns = _split_turns(rest)
    if len(turns) <= window:
        return messages, False
    kept = [m for turn in turns[-window:] for m in turn]
    return systems + kept, True
