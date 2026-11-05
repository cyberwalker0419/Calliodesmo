"""接地度侧车流水线：材料 → claim 抽取 → 核验 → 汇总（三输出面共用）。

调用方（分析 worker / QA 端点 / Agent worker）只负责提供**已按三维权限过滤**的
``sources``（``chunk_id → 源文``），本模块产出可 JSON 化的 ``verification`` 侧车：

```json
{
  "version": 1,
  "source": "analysis | qa | agent",
  "claims": [{text, kind, cited, chunk_id, verdict, confidence, reason, evidence}],
  "totals": {claims, checkable, supported, unsupported, uncertain, contradicted,
             uncited, citations, citations_supported},
  "metrics": {citation_precision, claim_grounding, unsupported_rate,
              contradiction_rate, uncited_claim_rate, calibrated_confidence},
  "needs_review": false
}
```

口径（P8 关键决策 3）：
- **只核验带引注或可定位 quote 的声明**；无引注声明 ``verdict="uncited"``，
  只计入 ``uncited_claim_rate``，不臆造证据（``uncited`` 为侧车状态，不在引擎
  四类判定枚举内）。
- 分析报告：结构化 payload 的 Evidence 节点做引注定位（kind=citation），
  其余文本字段按句子做跨文档核验（kind=claim，cited=false）。
- QA / Agent：答案按句子切分 + ``[chunk_id]`` 解析；句子引注的块不在可见集合时
  与「无证据」同语义（不泄漏存在性）。
- 验证只标记、不改内容：``needs_review`` 供复核队列消费，不自动删改报告。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from calliodesmo.eval.metrics_grounding import (
    citation_precision,
    claim_grounding,
    contradiction_rate,
    uncited_claim_rate,
    unsupported_rate,
)
from calliodesmo.verification.engine import normalize_text, verify_claim
from calliodesmo.verification.models import Claim, EvidenceSpan, Verdict, VerificationResult

#: 侧车版本（字段演进时递增，消费端按版本兼容）
VERIFICATION_VERSION = 1

#: 单次输出最多核验的声明数（防超长 payload 拖慢请求；超出部分截断并留痕）
MAX_CLAIMS = 200

#: 侧车证据引文最大展示长度（原文定位仍保留 start/end）
MAX_EVIDENCE_QUOTE_CHARS = 500

_SENTENCE_RE = re.compile(r"[^。！？；\n]+[。！？；\n]?")
_CITATION_RE = re.compile(r"\[([a-zA-Z0-9_\-:.#]+)\]")
#: 分析 payload 中不作为 claim 文本的结构键
_SKIP_TEXT_KEYS = frozenset(
    {
        "chunk_id",
        "quote",
        "source_chunk_ids",
        "model",
        "prompt_version",
        "generated_at",
        "task_type",
        "status",
        "usage",
        "warnings",
        "access_level",
        "library_scope",
    }
)


def build_verification(
    *,
    source: str,
    sources: Mapping[str, str],
    answer: str | None = None,
    payload: dict | None = None,
) -> dict:
    """构建 ``verification`` 侧车。

    参数:
        source: 输出面标识（``analysis`` / ``qa`` / ``agent``）。
        sources: 调用方已按 ``visible_to`` 过滤的 ``chunk_id → 源文``。
        answer: QA / Agent 答案文本（与 ``payload`` 二选一）。
        payload: 分析报告结构化 payload（与 ``answer`` 二选一）。

    返回:
        可 JSON 序列化的侧车 dict（结构见模块 docstring）。
    """
    claims: list[dict] = []
    citations_total = 0
    citations_supported = 0

    if payload is not None:
        citation_entries, text_claims = _analysis_entries(payload, sources)
        claims.extend(citation_entries)
        citations_total += len(citation_entries)
        citations_supported += sum(1 for c in citation_entries if c["verdict"] == "supported")
        claims.extend(_verify_uncited_text_claims(text_claims, sources))
    elif answer is not None:
        answer_claims, cited, supported = _answer_entries(answer, sources)
        claims.extend(answer_claims)
        citations_total += cited
        citations_supported += supported
    else:
        raise ValueError("build_verification 需要 answer 或 payload 之一")

    truncated = len(claims) > MAX_CLAIMS
    if truncated:
        claims = claims[:MAX_CLAIMS]

    totals = _totals(claims, citations_total, citations_supported)
    metrics = _metrics(totals, claims)
    return {
        "version": VERIFICATION_VERSION,
        "source": source,
        "claims": claims,
        "totals": totals,
        "metrics": metrics,
        "needs_review": _needs_review(totals, metrics),
        "truncated": truncated,
    }


def build_answer_verification(*, source: str, answer: str, context_chunks: list[dict]) -> dict:
    """QA / Agent 端点便捷入口：从 ``context_chunks`` 取可见源文生成侧车。"""
    sources = {
        str(chunk.get("chunk_id")): str(chunk.get("content", ""))
        for chunk in context_chunks
        if chunk.get("chunk_id")
    }
    return build_verification(source=source, sources=sources, answer=answer)


def _answer_entries(answer: str, sources: Mapping[str, str]) -> tuple[list[dict], int, int]:
    """QA / Agent 答案：按句子切分 + 引注解析（返回 entries / 引注数 / 支撑数）。"""
    entries: list[dict] = []
    cited_total = 0
    cited_supported = 0
    for sentence in _split_sentences(answer):
        cited_ids = [cid for cid in _CITATION_RE.findall(sentence)]
        text = _CITATION_RE.sub("", sentence).strip()
        if not text:
            continue
        if cited_ids:
            visible = {cid: sources[cid] for cid in cited_ids if cid in sources}
            result = verify_claim(Claim(text=text, quote=None), visible)
            entries.append(_entry(text=text, kind="claim", cited=True, result=result))
            cited_total += 1
            cited_supported += 1 if result.verdict is Verdict.SUPPORTED else 0
        else:
            entries.append(_uncited_entry(text))
    return entries, cited_total, cited_supported


def _analysis_entries(payload: dict, sources: Mapping[str, str]) -> tuple[list[dict], list[str]]:
    """分析 payload：Evidence 节点引注核验 + 其余文本字段句子 claim 收集。"""
    citation_entries: list[dict] = []
    for chunk_id, quote in _iter_evidence_nodes(payload):
        source_text = sources.get(chunk_id)
        if source_text is None:
            result = verify_claim(Claim(text=quote or "证据引文", chunk_id=chunk_id), {})
        elif not quote:
            result = VerificationResult(
                claim=Claim(text="证据引文", chunk_id=chunk_id),
                verdict=Verdict.UNSUPPORTED,
                confidence=0.2,
                reason="证据引文为空",
            )
        else:
            result = verify_claim(
                Claim(text=quote, chunk_id=chunk_id, quote=quote),
                {chunk_id: source_text},
            )
        citation_entries.append(
            _entry(text=quote or "", kind="citation", cited=True, result=result)
        )
    text_claims = list(_iter_text_fields(payload))
    return citation_entries, text_claims


def _verify_uncited_text_claims(text_claims: list[str], sources: Mapping[str, str]) -> list[dict]:
    """自由文本 claim：按句子做跨文档核验（无引注，cited=false）。"""
    entries: list[dict] = []
    for text in text_claims:
        for sentence in _split_sentences(text):
            if len(normalize_text(sentence)) < 4:
                continue
            result = verify_claim(Claim(text=sentence, quote=None), sources)
            entries.append(_entry(text=sentence, kind="claim", cited=False, result=result))
    return entries


def _entry(*, text: str, kind: str, cited: bool, result: VerificationResult) -> dict:
    """单条声明 -> 侧车条目（证据引文截断展示，偏移保留）。"""
    return {
        "text": text[:MAX_EVIDENCE_QUOTE_CHARS],
        "kind": kind,
        "cited": cited,
        "chunk_id": result.claim.chunk_id,
        "verdict": result.verdict.value,
        "confidence": result.confidence,
        "calibrated_confidence": result.confidence,  # T4 温度缩放覆盖
        "reason": result.reason,
        "evidence": [_span_dict(span) for span in result.evidence],
    }


def _uncited_entry(text: str) -> dict:
    """无引注声明：不核验、不臆造证据，只计入 uncited_claim_rate。"""
    return {
        "text": text[:MAX_EVIDENCE_QUOTE_CHARS],
        "kind": "claim",
        "cited": False,
        "chunk_id": None,
        "verdict": "uncited",
        "confidence": 0.0,
        "calibrated_confidence": 0.0,
        "reason": "无引注：未做支持性判定",
        "evidence": [],
    }


def _span_dict(span: EvidenceSpan) -> dict:
    return {
        "chunk_id": span.chunk_id,
        "quote": span.quote[:MAX_EVIDENCE_QUOTE_CHARS],
        "start": span.start,
        "end": span.end,
        "match_type": span.match_type,
    }


def _totals(claims: list[dict], citations_total: int, citations_supported: int) -> dict:
    """汇总计数（checkable = 四类已判定声明；uncited 单列）。"""
    verdicts = [claim["verdict"] for claim in claims]
    # uncited 按引注纪律计数（含已跨文档核验但无引注的自由文本声明）
    uncited = sum(1 for claim in claims if not claim["cited"])
    checkable = sum(1 for verdict in verdicts if verdict != "uncited")
    return {
        "claims": len(claims),
        "checkable": checkable,
        "supported": verdicts.count(Verdict.SUPPORTED.value),
        "unsupported": verdicts.count(Verdict.UNSUPPORTED.value),
        "uncertain": verdicts.count(Verdict.UNCERTAIN.value),
        "contradicted": verdicts.count(Verdict.CONTRADICTED.value),
        "uncited": uncited,
        "citations": citations_total,
        "citations_supported": citations_supported,
    }


def _metrics(totals: dict, claims: list[dict]) -> dict:
    """由计数派生指标（单一事实源：eval/metrics_grounding）。"""
    checkable = totals["checkable"]
    confidences = [
        claim["calibrated_confidence"] for claim in claims if claim["verdict"] != "uncited"
    ]
    return {
        "citation_precision": round(
            citation_precision(totals["citations_supported"], totals["citations"]), 4
        ),
        "claim_grounding": round(claim_grounding(totals["supported"], checkable), 4),
        "unsupported_rate": round(unsupported_rate(totals["unsupported"], checkable), 4),
        "contradiction_rate": round(contradiction_rate(totals["contradicted"], checkable), 4),
        "uncited_claim_rate": round(uncited_claim_rate(totals["uncited"], totals["claims"]), 4),
        "calibrated_confidence": round(sum(confidences) / len(confidences), 4)
        if confidences
        else 0.0,
    }


def _needs_review(totals: dict, metrics: dict) -> bool:
    """复核标记：矛盾存在，或接地度低于质量门槛（P8 门槛 0.80 / 0.10）。"""
    if totals["checkable"] == 0:
        return False
    return (
        totals["contradicted"] > 0
        or metrics["claim_grounding"] < 0.8
        or metrics["unsupported_rate"] > 0.1
    )


def _split_sentences(text: str) -> list[str]:
    """按句末标点 / 换行切句（保留句内引注，交给调用方解析）。"""
    return [
        match.group(0).strip() for match in _SENTENCE_RE.finditer(text) if match.group(0).strip()
    ]


def _iter_evidence_nodes(node: Any) -> Iterator[tuple[str, str]]:
    """递归产出 Evidence 节点 ``(chunk_id, quote)``（同 P6 证据节点判定）。"""
    if isinstance(node, dict):
        chunk_id = node.get("chunk_id")
        quote = node.get("quote")
        if isinstance(chunk_id, str) and isinstance(quote, str):
            yield chunk_id, quote
            return
        for value in node.values():
            yield from _iter_evidence_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_evidence_nodes(value)


def _iter_text_fields(node: Any, *, key: str | None = None) -> Iterator[str]:
    """递归产出非结构键的字符串字段（跳过 chunk_id / quote 等）。"""
    if isinstance(node, dict):
        if isinstance(node.get("chunk_id"), str) and isinstance(node.get("quote"), str):
            return
        for child_key, value in node.items():
            if child_key in _SKIP_TEXT_KEYS:
                continue
            yield from _iter_text_fields(value, key=child_key)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_text_fields(value, key=key)
    elif isinstance(node, str) and key not in _SKIP_TEXT_KEYS:
        yield node
