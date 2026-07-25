"""DocumentLoader 抽象接口：把文档源加载为统一文档对象（P1 ECL 的入口）。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoadedDocument:
    doc_id: str  # 稳定标识（相对路径）
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentLoader(ABC):
    @abstractmethod
    async def load(self, source: str | Path) -> list[LoadedDocument]:
        """从文件/目录/URI 加载文档列表。"""
