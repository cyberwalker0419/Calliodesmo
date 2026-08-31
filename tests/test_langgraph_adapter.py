"""P7 T6：BaseChatModel 适配器——LLMProvider -> LangGraph 桥。

断言：_agenerate 委派 complete(tools=)；bind_tools 只存 schema 透传；
LLMResponse -> AIMessage(tool_calls) id/name/args 无损；懒导入缺 extra 友好报错；
StubLLM + 适配器 + ToolNode 两回合工具循环（InMemorySaver）。
"""

import pytest

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec
from calliodesmo.providers.langgraph_adapter import build_langgraph_chat_model


class _RecordingProvider(LLMProvider):
    """记录调用参数的假 provider（断言委派与透传）。"""

    def __init__(self, tool_calls=None):
        self.model = "test/rec"
        self.calls: list[dict] = []
        self.tool_calls = tool_calls

    async def complete(self, messages, *, temperature=0.2, max_tokens=None, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return LLMResponse(
            content="final" if not self.tool_calls else "",
            model=self.model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            tool_calls=self.tool_calls,
        )


async def test_agenerate_delegates_and_maps_tool_calls():
    """委派 complete；LLMResponse.tool_calls -> AIMessage.tool_calls 无损。"""
    provider = _RecordingProvider(
        tool_calls=(ToolCall(id="c1", name="search_knowledge", arguments={"question": "q"}),)
    )
    model = build_langgraph_chat_model(provider)
    from langchain_core.messages import HumanMessage

    result = await model.agenerate([[HumanMessage(content="hi")]])
    gen = result.generations[0][0]

    sent = provider.calls[0]["messages"]
    assert isinstance(sent[0], LLMMessage) and sent[0].role == "user"
    assert gen.message.tool_calls == [
        {"name": "search_knowledge", "args": {"question": "q"}, "id": "c1", "type": "tool_call"}
    ]
    assert gen.generation_info["usage"]["total_tokens"] == 2


async def test_bind_tools_stores_schema_and_passthrough():
    """bind_tools 只存 OpenAI schema，_agenerate 时转 ToolSpec 透传。"""
    provider = _RecordingProvider()
    model = build_langgraph_chat_model(provider)
    spec = ToolSpec(name="t", description="d", parameters={"type": "object"})
    bound = model.bind_tools([spec])

    from langchain_core.messages import HumanMessage

    await bound.ainvoke([HumanMessage(content="q")])
    tools = provider.calls[0]["tools"]
    assert tools == [ToolSpec(name="t", description="d", parameters={"type": "object"})]

    # 未 bind：tools 为 None（旧调用面零变化）
    await model.ainvoke([HumanMessage(content="q")])
    assert provider.calls[1]["tools"] is None


def test_sync_generate_refused():
    """同步 invoke 显式报错（防异步 provider 配同步 invoke 静默挂死）。"""
    from langchain_core.messages import HumanMessage

    model = build_langgraph_chat_model(_RecordingProvider())
    with pytest.raises(RuntimeError, match="ainvoke"):
        model.invoke([HumanMessage(content="q")])


def test_build_missing_extra_friendly_error(monkeypatch):
    """懒导入守卫：require_langgraph 抛错时装配同抛（API 层转 503 的源头）。"""
    import calliodesmo.providers.langgraph_adapter as adapter_mod

    def boom():
        raise RuntimeError("缺少 agent extra 依赖（langgraph）。安装：uv sync --extra agent")

    monkeypatch.setattr(adapter_mod, "require_langgraph", boom)
    with pytest.raises(RuntimeError, match="uv sync --extra agent"):
        build_langgraph_chat_model(_RecordingProvider())


async def test_stub_adapter_toolnode_two_round_loop():
    """StubLLM + 适配器 + ToolNode 两回合工具循环（InMemorySaver），映射无损。"""
    from typing import Annotated, TypedDict

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode

    from calliodesmo.providers.stub_llm import StubLLMProvider

    seen: dict = {}

    async def search_knowledge(question: str, mode: str = "native_rag") -> str:
        seen["args"] = {"question": question, "mode": mode}
        return "OpenAI 开发了 GPT-4。"

    tool = StructuredTool.from_function(
        coroutine=search_knowledge, name="search_knowledge", description="检索"
    )

    model = build_langgraph_chat_model(StubLLMProvider())
    bound = model.bind_tools([tool_schema_for_stub()])

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    async def model_node(state: State):
        message = await bound.ainvoke(list(state["messages"]))
        return {"messages": [message]}

    def should_continue(state: State):
        return "tools" if state["messages"][-1].tool_calls else END

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    app = graph.compile(checkpointer=InMemorySaver())

    out = await app.ainvoke(
        {
            "messages": [
                SystemMessage(content="你是情报分析助手。[AGENT:two_step_search]"),
                HumanMessage(content="GPT-4 由谁开发？"),
            ]
        },
        config={"configurable": {"thread_id": "t6-loop"}},
    )

    msgs = out["messages"]
    # 轨迹：system -> human -> ai(tool_calls) -> tool -> ai(final)
    assert msgs[2].tool_calls[0]["name"] == "search_knowledge"
    assert msgs[2].tool_calls[0]["id"] == msgs[3].tool_call_id  # id 无损对齐
    assert seen["args"]["question"] == "GPT-4 由谁开发"  # 脚本化参数透传
    assert "OpenAI" in msgs[-1].content


def tool_schema_for_stub() -> ToolSpec:
    return ToolSpec(
        name="search_knowledge",
        description="检索",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}, "mode": {"type": "string"}},
            "required": ["question"],
        },
    )
