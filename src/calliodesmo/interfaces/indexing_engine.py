"""IndexingEngine 抽象接口：六个可插拔接口之一，ECL 主链路编排入口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from calliodesmo.auth.context import AccessContext


@dataclass
class IngestStats:
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0
    communities: int = 0

    def as_dict(self) -> dict:
        return {
            "documents": self.documents,
            "chunks": self.chunks,
            "entities": self.entities,
            "relations": self.relations,
            "communities": self.communities,
        }


class IndexingEngine(ABC):
    @abstractmethod
    async def ingest(self, source: str | Path, *, access: AccessContext) -> IngestStats:
        """端到端建图落库：Load->Extract->Cognify->Load->社区派生。"""
