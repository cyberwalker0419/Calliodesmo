"""LLMProvider 抽象接口：LiteLLM 统一接入 OpenAI/Qwen/DeepSeek/Ollama，可切换。

P7 T3：原生工具调用契约（function calling）——``ToolSpec`` / ``ToolCall`` frozen
dataclass；``LLMMessage`` 可选 ``tool_calls``（assistant 携带）/ ``tool_call_id``
（tool 角色回写）；``LLMResponse`` 可选 ``tool_calls``；``complete(..., tools=None)``
默认 ``None`` 保旧调用面零变化。LiteLLM 走 OpenAI 格式 ``tools`` / ``tool_calls`` 透传。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """工具定义：JSON Schema 参数（注册表入参校验与 provider ``tools=`` 共用同一份）。"""

    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    """模型下发的一次工具调用（OpenAI 格式 id / name / arguments）。"""

    id: str
    name: str
    arguments: dict


@dataclass
class LLMMessage:
    role: str  # system / user / assistant / tool
    content: str
    tool_calls: tuple[ToolCall, ...] | None = None  # assistant：本轮原生工具调用
    tool_call_id: str | None = None  # tool：回写结果对应的 tool_call_id


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None
    tool_calls: tuple[ToolCall, ...] | None = None  # 原生工具调用（后端不支持时为 None）


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        """对话补全。``tools`` 默认 None 保旧调用面零变化；传入时走原生 function calling。"""
