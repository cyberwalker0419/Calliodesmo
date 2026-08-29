"""查询改写抽象：query -> 多变体子查询（P5 Task 1）。"""

from abc import ABC, abstractmethod


class QueryRewriter(ABC):
    @abstractmethod
    async def generate(self, query: str) -> list[str]:
        """把单个查询改写为多个视角的子查询。"""
