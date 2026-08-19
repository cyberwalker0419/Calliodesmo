"""VisionProvider 抽象接口：图像语义理解 / 识图描述（qwen3-vl 等 VLM，可切换）。

与 OcrProvider（逐字 OCR，interfaces/ocr.py）分离：
- VisionProvider：语义理解描述，产出供 LLM 看图问答的语境（识图 / 图表 / 图片内容）
- OcrProvider：逐字保真转录，产出喂抽取与嵌入索引的文本

默认实现保持确定性、零重依赖、离线可测（test/* 走桩）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VisionResponse:
    content: str  # 视觉理解描述文本
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class VisionProvider(ABC):
    @abstractmethod
    async def describe(
        self,
        text: str,
        image: bytes,
        *,
        mime: str,
    ) -> VisionResponse:
        """给定图片字节与提示词，返回视觉理解描述（识图 / 图表 / 看图问答）。"""
