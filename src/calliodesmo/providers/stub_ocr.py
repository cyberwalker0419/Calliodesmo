"""离线桩 OcrProvider：``test/*`` 模型路由到此处，零网络、零依赖。

用途：
- CLI 离线演示 / 冒烟测试 —— ``CALLIODESMO_OCR_PROVIDER=stub calliodesmo ingest ...``
- 让 P1 完整管线（Load->Extract->Cognify->Load）在图片文档场景无需任何真实 OCR 即可跑通

实现：返回固定占位文本（含提示词前几个字符），仅用于验证管线联通，
不代表真实 OCR 质量。真实 OCR 请配置 PaddleOCR-VL 后端。
"""

from __future__ import annotations

from calliodesmo.interfaces.ocr import OcrProvider, OcrResult


class StubOcrProvider(OcrProvider):
    """离线桩 OCR：返回固定占位转录文本。"""

    def __init__(self, model: str = "test/stub-ocr") -> None:
        self.model = model

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> OcrResult:
        prompt_hint = (prompt or "OCR")[:24]
        return OcrResult(
            text=(
                f"[离线桩 OCR 占位] 提示词={prompt_hint}，图片 {len(image)} 字节（仅验证管线联通）"
            ),
            model=self.model,
            metadata={"stub": True, "mime": mime},
        )
