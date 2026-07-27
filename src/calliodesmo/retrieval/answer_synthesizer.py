"""AnswerSynthesizer：LLM 答案合成 + 来源标注。

prompt 含来源标注要求：答案须标注引用的 chunk_id；忠实度约束（不编造）。
候选为空时返回"无可引用证据"而非编造。
"""

from __future__ import annotations

import re

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.retriever import Answer, Candidate, SearchMode

_SYSTEM_PROMPT = (
    "你是答案合成引擎。基于给定的上下文文本块回答用户问题。"
    "要求：1) 答案须由上下文支撑，不可编造；"
    "2) 引用证据时标注 [chunk_id]，如 [c1]；"
    "3) 若上下文不足以回答，直接说明。"
)

_NO_EVIDENCE = "无可引用证据，无法基于现有上下文回答该问题。"

_CITATION_RE = re.compile(r"\[([a-zA-Z0-9_\-:]+)\]")


class AnswerSynthesizer:
    """LLM 答案合成器：召回候选 -> prompt -> LLM -> 解析来源标注 -> Answer。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def synthesize(
        self,
        question: str,
        candidates: list[Candidate],
        *,
        mode: SearchMode,
        access: AccessContext,
    ) -> Answer:
        if not candidates:
            return Answer(
                text=_NO_EVIDENCE,
                source_chunk_ids=[],
                mode=mode,
                context_chunks=[],
                model="",
                usage={},
            )

        # 构建上下文：每条候选标注 [chunk_id]
        context_lines: list[str] = []
        valid_ids = {c.chunk_id for c in candidates}
        for c in candidates:
            context_lines.append(f"[{c.chunk_id}] {c.content}")
        context_text = "\n\n".join(context_lines)

        user_prompt = f"问题：{question}\n\n上下文：\n{context_text}"

        resp = await self._llm.complete(
            [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        # 解析答案中的 [chunk_id] 标注
        cited_ids = [cid for cid in _CITATION_RE.findall(resp.content) if cid in valid_ids]
        # 去重保序
        seen: set[str] = set()
        source_ids: list[str] = []
        for cid in cited_ids:
            if cid not in seen:
                seen.add(cid)
                source_ids.append(cid)
        # 若 LLM 未标注来源，回退为全部候选
        if not source_ids:
            source_ids = [c.chunk_id for c in candidates]

        context_chunks = [
            {"chunk_id": c.chunk_id, "content": c.content, "score": c.score} for c in candidates
        ]

        return Answer(
            text=resp.content,
            source_chunk_ids=source_ids,
            mode=mode,
            context_chunks=context_chunks,
            model=resp.model,
            usage=resp.usage,
        )
