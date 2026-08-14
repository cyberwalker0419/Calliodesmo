"""离线桩 VisionProvider：``test/*`` 模型路由到此处，零网络、零依赖。

用途：
- 让提问侧多模态（带图问答）在无真实 VLM 时即可跑通离线验证
- 供问答 API / 前端联调使用，返回固定占位描述文本

实现：返回固定占位文本（含提示词前几个字符），仅用于验证管线联通，
不代表真实识图质量。真实识图请配置 qwen3-vl 等 VLM 后端。
"""

from __future__ import annotations

from calliodesmo.interfaces.vision import VisionProvider, VisionResponse


class StubVisionProvider(VisionProvider):
    """离线桩识图：返回固定占位描述文本。"""

    def __init__(self, model: str = "test/stub-vision") -> None:
        self.model = model

    async def describe(
        self,
        text: str,
        image: bytes,
        *,
        mime: str,
    ) -> VisionResponse:
        prompt_hint = (text or "识图")[:24]
        return VisionResponse(
            content=(
                f"[离线桩 VLM 占位] 提示词={prompt_hint}，图片 "
                f"{len(image)} 字节（仅验证管线联通）"
            ),
            model=self.model,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
