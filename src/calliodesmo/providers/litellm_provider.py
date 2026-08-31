"""默认 LLMProvider：LiteLLM 统一后端（模型经 CALLIODESMO_LLM_MODEL 配置切换）。

支持经 ``extra_body`` 透传后端特有参数（如 llama.cpp 的
``chat_template_kwargs.enable_thinking`` 用于禁用 reasoning 模型的思考链，
让 content 直接承载回答，避免 token 被思考链耗尽）。

P7 T3：原生工具调用——``tools`` 转 OpenAI 格式透传 ``acompletion(tools=...)``，
响应 ``tool_calls`` 解析回 ``ToolCall``（arguments JSON 解析失败兜底空 dict）；
后端不支持时响应无 tool_calls，``LLMResponse.tool_calls=None`` 走纯文本路径
（友好降级；``--real`` 预检后端能力，不做文本协议降级，见 P7 T19）。
"""

import json

from calliodesmo.interfaces.llm import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)


def _short_model(model: str | None) -> str:
    """模型标识短化：llama.cpp 等本地服务回显的常是文件路径（含盘符/反斜杠/.gguf），取 basename
    避免泄露服务器路径；LiteLLM 的 provider/model 形式（如 openai/gpt-4o-mini）原样保留。"""
    if not model:
        return ""
    if "\\" in model or ":" in model or model.lower().endswith((".gguf", ".bin", ".safetensors")):
        return model.replace("\\", "/").rsplit("/", 1)[-1]
    return model


class LiteLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        extra_body: dict | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.extra_body = extra_body

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        import litellm  # 延迟导入：调用点才承担其导入开销

        kwargs: dict = {
            "model": self.model,
            "messages": [_to_openai_message(m) for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        # 透传后端特有参数（OpenAI 兼容 server 经 extra_body 接收，如 llama.cpp 的
        # chat_template_kwargs；LiteLLM 会原样转给底层 httpx 请求体）
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        if tools:
            # OpenAI 格式工具定义（与注册表入参校验共用同一份 JSON Schema）
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return LLMResponse(
            content=choice.message.content or "",
            model=_short_model(response.model),
            usage=usage,
            raw=response,
            tool_calls=_parse_tool_calls(choice),
        )


def _to_openai_message(m: LLMMessage) -> dict:
    """LLMMessage -> OpenAI chat 格式（assistant tool_calls / tool 回写两种形态）。"""
    out: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id is not None:
        out["tool_call_id"] = m.tool_call_id
    return out


def _parse_tool_calls(choice) -> tuple[ToolCall, ...] | None:
    """响应 message.tool_calls（OpenAI 格式）-> ToolCall 元组；无则 None。"""
    raw_calls = getattr(choice.message, "tool_calls", None)
    if not raw_calls:
        return None
    parsed: list[ToolCall] = []
    for rc in raw_calls:
        args_raw = rc.function.arguments or "{}"
        try:
            arguments = json.loads(args_raw)
            if not isinstance(arguments, dict):
                arguments = {}
        except (ValueError, TypeError):
            arguments = {}  # 参数幻觉兜底：注册表 schema 校验会拒畸形入参
        parsed.append(ToolCall(id=rc.id, name=rc.function.name, arguments=arguments))
    return tuple(parsed)
