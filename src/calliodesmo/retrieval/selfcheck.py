"""SelfCheck：答案-上下文一致性自检，低分 1 轮重答（P5 Task 5）。

答案合成后由 LLM judge 判别答案与问题的一致性；低于 threshold 时以
「基于上下文可靠回答」提示触发 1 轮重答（限定上下文，防止反复追问）。
judge 走 StubLLM 时返回固定分数，可离线确定性测试。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode


class SelfCheckEngine(SearchEngine):
    """包装 SearchEngine：答案产出后 LLM judge 判别一致性，低于 threshold 重答 1 轮。"""

    def __init__(self, *, inner: SearchEngine, judge: LLMProvider, threshold: float = 0.5) -> None:
        self._inner = inner
        self._judge = judge
        self._threshold = threshold

    async def query(self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext):
        answer = await self._inner.query(question, mode=mode, top_k=top_k, access=access)
        score = await self._score(question, answer)
        if score >= self._threshold:
            return answer
        # 低一致性：限定上下文重答 1 轮
        answer2 = await self._inner.query(
            f"{question}（请基于上述上下文做出可靠回答）",
            mode=mode,
            top_k=top_k,
            access=access,
        )
        answer2.mode = mode
        return answer2

    async def _score(self, question: str, answer) -> float:
        """LLM judge 对答案与问题的相关性/一致性打分（0-1，非法解析 0）。"""
        if not answer.text:
            return 0.0
        user_msg = "问题：" + question + " || 答案：" + answer.text
        resp = await self._judge.complete(
            [
                LLMMessage(role="system", content="你是答案一致性评估器。仅返回 0-1 浮点数。"),
                LLMMessage(role="user", content=user_msg),
            ],
            temperature=0.0,
            max_tokens=16,
        )
        try:
            return max(0.0, min(1.0, float(resp.content.strip())))
        except ValueError:
            return 0.0
