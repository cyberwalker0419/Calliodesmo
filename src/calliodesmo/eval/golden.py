"""GoldenCase 数据模型 + 从 YAML 加载 golden Q&A 集。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class GoldenCase:
    """golden Q&A：问题 + 标准答案 + 相关 chunk_id + 检索模式。"""

    question: str
    expected_answer: str
    relevant_chunk_ids: list[str] = field(default_factory=list)
    mode: str = "native_rag"


def load_golden(path: str | Path) -> list[GoldenCase]:
    """从 YAML 文件加载 golden Q&A 集。空文件返回空集。"""
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not data or "cases" not in data:
        return []
    cases: list[GoldenCase] = []
    for item in data["cases"]:
        cases.append(
            GoldenCase(
                question=item.get("question", ""),
                expected_answer=item.get("expected_answer", ""),
                relevant_chunk_ids=item.get("relevant_chunk_ids", []),
                mode=item.get("mode", "native_rag"),
            )
        )
    return cases
