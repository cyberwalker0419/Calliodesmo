"""默认 LLMProvider：LiteLLM 统一后端（模型经 CALLIODESMO_LLM_MODEL 配置切换）。"""

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse


class LiteLLMProvider(LLMProvider):
    def __init__(self, model: str, api_key: str | None = None, api_base: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base

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
            model=response.model,
            usage=usage,
            raw=response,
        )
