"""评估指标：context_recall / faithfulness / answer_relevance。"""

from __future__ import annotations

import re

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider


def context_recall(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """相关 chunk 的召回比例（确定性，0-1）。"""
    if not relevant_ids:
        return 0.0
    hit = len(set(retrieved_ids) & relevant_ids)
    return hit / len(relevant_ids)


async def faithfulness(answer: str, context: list[str], *, judge: LLMProvider) -> float:
    """忠实度：答案断言能否由 context 支撑（LLM-as-judge，0-1）。"""
    if not answer or not context:
        return 0.0
    context_text = "\n".join(context)
    prompt = (
        "你是忠实度评估器。判断以下答案的断言是否能由给定上下文支撑。\n"
        "仅返回一个 0 到 1 的浮点数（1=完全支撑，0=完全无法支撑）。\n"
        f"上下文：\n{context_text}\n\n答案：\n{answer}"
    )
    resp = await judge.complete(
        [
            LLMMessage(role="system", content="你是忠实度评估器。"),
            LLMMessage(role="user", content=prompt),
        ],
        temperature=0.0,
        max_tokens=16,
    )
    return _parse_score(resp.content)


async def answer_relevance(answer: str, question: str, *, judge: LLMProvider) -> float:
    """答案相关性：答案是否切题（LLM-as-judge，0-1）。"""
    if not answer or not question:
        return 0.0
    prompt = (
        "你是答案相关性评估器。判断以下答案是否切题回答了问题。\n"
        "仅返回一个 0 到 1 的浮点数（1=完全切题，0=完全不切题）。\n"
        f"问题：\n{question}\n\n答案：\n{answer}"
    )
    resp = await judge.complete(
        [
            LLMMessage(role="system", content="你是答案相关性评估器。"),
            LLMMessage(role="user", content=prompt),
        ],
        temperature=0.0,
        max_tokens=16,
    )
    return _parse_score(resp.content)


def _parse_score(text: str) -> float:
    """从 LLM 响应解析 0-1 分数（非法返回 0.0，不抛异常）。"""
    m = re.search(r"([0-9]*\.?[0-9]+)", text.strip())
    if not m:
        return 0.0
    try:
        val = float(m.group(1))
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return 0.0
