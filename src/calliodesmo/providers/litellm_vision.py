"""默认 VisionProvider：LiteLLM 统一 backend（模型经 CALLIODESMO_VISION_MODEL 配置切换）。

与 LLM 走同一套 LiteLLM 接入（Ollama / LM Studio / llama.cpp / 云端均可），
把图片字节 base64 为 data URI 的 image_url part，与文本提示组成 OpenAI 多模态
content part 列表；``extra_body`` 透传后端特有参数（同 litellm_provider）。
"""

from __future__ import annotations

import base64

from calliodesmo.interfaces.vision import VisionProvider, VisionResponse
from calliodesmo.providers.litellm_provider import _short_model


def _data_uri(image: bytes, mime: str) -> str:
    """图片字节 -> data URI（LiteLLM/Ollama 视觉走 image_url 协议）。"""
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


class LiteLLMVisionProvider(VisionProvider):
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

    async def describe(
        self,
        text: str,
        image: bytes,
        *,
        mime: str,
    ) -> VisionResponse:
        import litellm  # 延迟导入：调用点才承担其导入开销

        content: list[dict] = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": _data_uri(image, mime)}},
        ]
        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
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
        return VisionResponse(
            content=choice.message.content or "",
            model=_short_model(response.model),
            usage=usage,
        )
