"""OcrProvider 抽象接口：文档逐字 OCR 转录（PaddleOCR-VL 等专用引擎，可切换）。

与 VisionProvider（识图/语义描述）分离：
- OcrProvider：逐字保真转录，产出喂抽取与嵌入索引的文本（CER/WER 优先）
- VisionProvider：语义理解描述，产出供 LLM 看图问答的语境（interfaces/vision.py）

默认实现保持确定性、零重依赖、离线可测（test/* 走桩）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    text: str  # OCR 逐字转录文本
    model: str
    metadata: dict = field(default_factory=dict)  # 置信度 / 页 / 耗时等


class OcrProvider(ABC):
    @abstractmethod
    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> OcrResult:
        """给定图片字节返回 OCR 转录文本（喂抽取 / 嵌入，逐字保真优先）。"""
