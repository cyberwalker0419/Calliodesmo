"""默认 LLMProvider：LiteLLM 统一后端（模型经 CALLIODESMO_LLM_MODEL 配置切换）。

支持经 ``extra_body`` 透传后端特有参数（如 llama.cpp 的
``chat_template_kwargs.enable_thinking`` 用于禁用 reasoning 模型的思考链，
让 content 直接承载回答，避免 token 被思考链耗尽）。
"""

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse


def _short_model(model: str | None) -> str:
    """模型标识短化：llama.cpp 等本地服务回显的常是文件路径，取 basename 避免泄露服务器路径。"""
    if not model:
        return ""
    return model.replace("\\", "/").rsplit("/", 1)[-1]


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
    ) -> LLMResponse:
        import litellm  # 延迟导入：调用点才承担其导入开销

        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
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
        )
