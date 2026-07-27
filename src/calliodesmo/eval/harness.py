"""EvalHarness：对 golden Q&A 集跑回归，汇总均值与每条详情。"""

from __future__ import annotations

from dataclasses import dataclass, field

from calliodesmo.auth.context import AccessContext
from calliodesmo.eval.golden import GoldenCase
from calliodesmo.eval.metrics import answer_relevance, context_recall, faithfulness
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode


@dataclass
class CaseResult:
    question: str
    context_recall: float
    faithfulness: float
    answer_relevance: float
    answer_text: str
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    total: int = 0
    mean_context_recall: float = 0.0
    mean_faithfulness: float = 0.0
    mean_answer_relevance: float = 0.0
    cases: list[CaseResult] = field(default_factory=list)


class EvalHarness:
    """评估 harness：对每 golden case 跑 engine.query -> 算指标 -> 汇总。"""

    def __init__(self, engine: SearchEngine, judge: LLMProvider) -> None:
        self._engine = engine
        self._judge = judge

    async def run(self, cases: list[GoldenCase], *, access: AccessContext) -> EvalReport:
        if not cases:
            return EvalReport()
        results: list[CaseResult] = []
        for case in cases:
            mode = SearchMode(case.mode)
            answer = await self._engine.query(case.question, mode=mode, top_k=10, access=access)
            cr = context_recall(answer.source_chunk_ids, set(case.relevant_chunk_ids))
            context_texts = [c.get("content", "") for c in answer.context_chunks]
            fa = await faithfulness(answer.text, context_texts, judge=self._judge)
            ar = await answer_relevance(answer.text, case.question, judge=self._judge)
            results.append(
                CaseResult(
                    question=case.question,
                    context_recall=cr,
                    faithfulness=fa,
                    answer_relevance=ar,
                    answer_text=answer.text,
                    source_chunk_ids=answer.source_chunk_ids,
                )
            )
        n = len(results)
        report = EvalReport(
            total=n,
            mean_context_recall=round(sum(r.context_recall for r in results) / n, 4),
            mean_faithfulness=round(sum(r.faithfulness for r in results) / n, 4),
            mean_answer_relevance=round(sum(r.answer_relevance for r in results) / n, 4),
            cases=results,
        )
        return report
