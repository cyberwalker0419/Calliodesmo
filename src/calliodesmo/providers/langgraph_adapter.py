"""BaseChatModel 适配器：LLMProvider -> LangGraph 桥（LLM 所有权不旁落）。

仅依赖 langchain-core（langgraph 硬依赖带入），**不引 langchain 主体 /
langchain-litellm**（与 P6 拒 LangChain 主体一致）。``_agenerate`` 委派
``LLMProvider.complete(tools=...)``；``bind_tools`` 只存 OpenAI schema 并在
调用时透传；``LLMResponse`` -> ``AIMessage(tool_calls)`` 映射。

图调用一律 ``ainvoke``：同步 ``_generate`` 显式报错（异步 provider 配同步 invoke
静默挂死，P7 决策 2 检查单）。
"""

from __future__ import annotations

from typing import Any

from calliodesmo.agent.extras import require_langgraph
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, ToolCall, ToolSpec


def _to_openai_schema(t: Any) -> dict:
    """ToolSpec / OpenAI function dict -> 统一 OpenAI schema dict。"""
    if isinstance(t, ToolSpec):
        return {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
    if isinstance(t, dict):
        return t if "function" in t else {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            },
        }
    raise TypeError(f"bind_tools 不支持的工具形态: {type(t)!r}")


def _to_llm_message(m) -> LLMMessage:
    """langchain BaseMessage -> 自有 LLMMessage（四种角色 + tool_calls 形态）。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    if isinstance(m, ToolMessage):
        return LLMMessage(role="tool", content=m.content or "", tool_call_id=m.tool_call_id)
    if isinstance(m, AIMessage):
        calls = tuple(
            ToolCall(
                id=tc.get("id", ""), name=tc.get("name", ""), arguments=dict(tc.get("args") or {})
            )
            for tc in (m.tool_calls or [])
        )
        return LLMMessage(role="assistant", content=m.content or "", tool_calls=calls or None)
    if isinstance(m, SystemMessage):
        return LLMMessage(role="system", content=m.content or "")
    if isinstance(m, HumanMessage):
        return LLMMessage(role="user", content=m.content or "")
    return LLMMessage(role="user", content=str(m.content))


def _build_model_class():
    """类体延迟构建：langchain-core 缺依赖时经 require_langgraph 友好报错。"""
    require_langgraph()
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class LLMProviderChatModel(BaseChatModel):
        """委派自有 LLMProvider 的 BaseChatModel（适配器，不旁落 LLM 所有权）。"""

        provider: Any

        @property
        def _llm_type(self) -> str:
            return "calliodesmo-llm-provider"

        def bind_tools(self, tools: list, **kwargs: Any):
            """只存 OpenAI schema，调用时经 kwargs 透传 provider.complete(tools=)。"""
            schemas = [_to_openai_schema(t) for t in tools]
            return super().bind(tools=schemas, **kwargs)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError(
                "LLMProviderChatModel 仅支持异步调用（ainvoke）；"
                "异步 provider 配同步 invoke 会静默挂死"
            )

        async def _agenerate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> ChatResult:
            tools = [
                ToolSpec(
                    name=s["function"]["name"],
                    description=s["function"].get("description", ""),
                    parameters=s["function"].get("parameters", {}),
                )
                for s in kwargs.get("tools") or []
            ]
            resp = await self.provider.complete(
                [_to_llm_message(m) for m in messages], tools=tools or None
            )
            ai = AIMessage(
                content=resp.content or "",
                tool_calls=[
                    {"name": tc.name, "args": tc.arguments, "id": tc.id, "type": "tool_call"}
                    for tc in resp.tool_calls or []
                ],
            )
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=ai,
                        generation_info={"model": resp.model, "usage": resp.usage},
                    )
                ],
                llm_output={"model": resp.model, "usage": resp.usage},
            )

    return LLMProviderChatModel


def build_langgraph_chat_model(provider: LLMProvider):
    """装配适配器：懒导入守卫（缺 agent extra 友好报错，API 层转 503）。"""
    cls = _build_model_class()
    return cls(provider=provider)
