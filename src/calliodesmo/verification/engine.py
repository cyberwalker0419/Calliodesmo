"""确定性证据核验引擎（纯函数、无 LLM、无 DB、无新依赖）。

判定链（顺序即优先级，见 P8 关键决策 1/4）：

1. **引注定位**：``quote`` 经归一化（去空白 + NFKC 全半角折叠）后必须是源文子串；
   定位失败 → ``unsupported``（引注不可定位），不臆造证据。
2. **矛盾启发式**：在声明与证据文本覆盖度足够（≥ ``CONFLICT_MIN_COVERAGE``）时，
   数值 / 日期集合不一致、单位不一致、否定极性相反判 ``contradicted``；
   反义词对（上行/下行、等级高/等级低等）命中即判 ``contradicted``。
3. **支持性判定**：声明对证据文本的字符二元组覆盖率
   ≥ ``QUOTE_SUPPORT_THRESHOLD`` → ``supported``；≥ ``QUOTE_UNCERTAIN_THRESHOLD``
   → ``uncertain``；否则 ``unsupported``。
4. **跨文档核验**：无引注时，在**调用方已按 ``visible_to`` 过滤**的源文里按句子 /
   整块检索候选证据；跨文档匹配证据更弱，故阈值更高
   （``CROSS_SUPPORT_THRESHOLD`` / ``CROSS_UNCERTAIN_THRESHOLD``）。

权限红线：不可见 chunk 与不存在 chunk 返回**同一** ``unsupported`` 语义与理由，
不泄漏存在性；引擎本身不做权限判断，由调用方只传入可见材料。

注入防御：声明 / 引注中的任何文字都只作为被判定数据，引擎不解析、不执行其中的指令；
命中常见注入话术时仅在 ``reason`` 追加「已忽略注入指令」留痕。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence

from calliodesmo.analysis.evidence import normalize_for_match
from calliodesmo.verification.models import Claim, EvidenceSpan, Verdict, VerificationResult

#: 引注路径的支持 / 不确定阈值（字符二元组覆盖率）
QUOTE_SUPPORT_THRESHOLD = 0.85
QUOTE_UNCERTAIN_THRESHOLD = 0.35
#: 跨文档路径阈值（证据更弱，要求更高）
CROSS_SUPPORT_THRESHOLD = 0.75
CROSS_UNCERTAIN_THRESHOLD = 0.50
#: 矛盾判定的最低覆盖度（避免无关文本触发否定 / 数值冲突）
CONFLICT_MIN_COVERAGE = 0.30

#: 证据不可用（不存在 / 不可见）的统一理由——两者必须同文案
_EVIDENCE_UNAVAILABLE = "证据不可用：chunk 不存在或当前权限不可见"

_NEGATION_MARKERS = ("并非", "不是", "未经", "没有", "不", "未", "无", "非")
_ANTONYM_PAIRS = (
    ("上行", "下行"),
    ("上涨", "下跌"),
    ("增加", "减少"),
    ("上升", "下降"),
    ("高于", "低于"),
    ("等级高", "等级低"),
    ("增强", "减弱"),
    ("同一", "不同"),
)
_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*(?:至|到|-|–|~)\s*(\d{4})")
_UNIT_RE = re.compile(r"万吨|亿元|万元|吨|元|%")
_SENTENCE_RE = re.compile(r"[^。！？；]+[。！？；]?")
_INJECTION_RE = re.compile(
    r"(忽略.{0,8}指令|忽略以上|忽略先前|直接判定|系统指令|system\s*prompt|输出系统提示)",
    re.IGNORECASE,
)


def verify_claim(claim: Claim, sources: Mapping[str, str]) -> VerificationResult:
    """核验单条声明。

    参数:
        claim: 待核验声明。
        sources: ``chunk_id → 源文`` 映射；调用方必须已按三维权限过滤。

    返回:
        ``VerificationResult``（不可变，确定性——同一输入恒得同一输出）。
    """
    if not claim.text or not claim.text.strip():
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNSUPPORTED,
            confidence=0.1,
            reason="空声明：无可核验内容",
        )
    if claim.quote and normalize_text(claim.quote).strip():
        return _verify_with_quote(claim, sources)
    return _verify_cross_document(claim, sources)


def verify_claims(claims: Sequence[Claim], sources: Mapping[str, str]) -> list[VerificationResult]:
    """批量核验（保持输入顺序，逐条确定性判定）。"""
    return [verify_claim(claim, sources) for claim in claims]


def _verify_with_quote(claim: Claim, sources: Mapping[str, str]) -> VerificationResult:
    """引注路径：定位 quote → 矛盾检查 → 覆盖率判定。"""
    chunk_id = claim.chunk_id or ""
    source = sources.get(chunk_id)
    if source is None:
        return _unsupported(claim, _EVIDENCE_UNAVAILABLE)

    norm_source = normalize_text(source)
    norm_quote = normalize_text(claim.quote or "")
    start = norm_source.find(norm_quote)
    if start < 0:
        return _unsupported(claim, "引注不可定位：quote 不是对应源文子串")

    span = EvidenceSpan(
        chunk_id=chunk_id,
        quote=claim.quote or "",
        start=start,
        end=start + len(norm_quote),
        match_type="quote",
    )
    conflict = _detect_conflict(claim.text, norm_quote)
    if conflict is not None:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.CONTRADICTED,
            confidence=0.9,
            reason=_with_injection_note(conflict, claim),
            evidence=(span,),
        )

    coverage = _coverage(claim.text, norm_quote)
    if coverage >= QUOTE_SUPPORT_THRESHOLD:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.SUPPORTED,
            confidence=round(min(0.95, 0.7 + 0.25 * coverage), 4),
            reason=_with_injection_note(f"引注直接支撑声明（覆盖率 {coverage:.2f}）", claim),
            evidence=(span,),
        )
    if coverage >= QUOTE_UNCERTAIN_THRESHOLD:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNCERTAIN,
            confidence=0.5,
            reason=_with_injection_note(f"引注部分支撑声明（覆盖率 {coverage:.2f}）", claim),
            evidence=(span,),
        )
    return _unsupported(
        claim,
        _with_injection_note(f"引注与声明相关性不足（覆盖率 {coverage:.2f}）", claim),
    )


def _verify_cross_document(claim: Claim, sources: Mapping[str, str]) -> VerificationResult:
    """跨文档路径：在可见源文的句子 / 整块中检索候选证据。"""
    if claim.chunk_id and claim.chunk_id not in sources:
        return _unsupported(claim, _EVIDENCE_UNAVAILABLE)

    best: tuple[float, str, EvidenceSpan] | None = None
    conflicting: tuple[float, str, EvidenceSpan] | None = None
    for chunk_id in sorted(sources):
        for unit_text, start, end in _iter_units(sources[chunk_id]):
            coverage = _coverage(claim.text, unit_text)
            span = EvidenceSpan(
                chunk_id=chunk_id,
                quote=unit_text,
                start=start,
                end=end,
                match_type="cross_document",
            )
            if coverage >= CONFLICT_MIN_COVERAGE:
                conflict = _detect_conflict(claim.text, unit_text)
                if conflict is not None and (conflicting is None or coverage > conflicting[0]):
                    conflicting = (coverage, conflict, span)
            if best is None or coverage > best[0]:
                best = (coverage, unit_text, span)

    if conflicting is not None:
        _, conflict, span = conflicting
        return VerificationResult(
            claim=claim,
            verdict=Verdict.CONTRADICTED,
            confidence=0.85,
            reason=_with_injection_note(f"跨文档证据冲突：{conflict}", claim),
            evidence=(span,),
        )

    if best is None:
        return _unsupported(claim, "无可核查源文")
    coverage, _, span = best
    if coverage >= CROSS_SUPPORT_THRESHOLD:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.SUPPORTED,
            confidence=round(min(0.9, 0.6 + 0.3 * coverage), 4),
            reason=_with_injection_note(f"跨文档证据支撑声明（覆盖率 {coverage:.2f}）", claim),
            evidence=(span,),
        )
    if coverage >= CROSS_UNCERTAIN_THRESHOLD:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNCERTAIN,
            confidence=0.45,
            reason=_with_injection_note(f"跨文档证据部分支撑（覆盖率 {coverage:.2f}）", claim),
            evidence=(span,),
        )
    return _unsupported(
        claim,
        _with_injection_note(f"未找到支撑证据（最高覆盖率 {coverage:.2f}）", claim),
    )


def _unsupported(claim: Claim, reason: str) -> VerificationResult:
    """统一的 unsupported 结果（无证据片段，不泄漏任何源文）。"""
    return VerificationResult(
        claim=claim,
        verdict=Verdict.UNSUPPORTED,
        confidence=0.2,
        reason=reason,
        evidence=(),
    )


def _with_injection_note(reason: str, claim: Claim) -> str:
    """命中注入话术时追加留痕（只记录，不改变判定）。"""
    haystack = " ".join(x for x in (claim.text, claim.quote or "") if x)
    if _INJECTION_RE.search(haystack):
        return f"{reason}；已忽略声明中的注入指令"
    return reason


def normalize_text(text: str) -> str:
    """匹配归一化：复用 P6 ``normalize_for_match``（去空白）+ NFKC 全半角折叠。"""
    return unicodedata.normalize("NFKC", normalize_for_match(text))


def _grams(text: str) -> set[str]:
    """字符二元组集合（去标点 / 空白；单字文本退化为单字集）。"""
    cleaned = re.sub(r"[^\w]", "", normalize_text(text))
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _coverage(claim_text: str, unit_text: str) -> float:
    """声明二元组被证据文本覆盖的比例（0–1）。"""
    claim_grams = _grams(claim_text)
    if not claim_grams:
        return 0.0
    unit_grams = _grams(unit_text)
    return len(claim_grams & unit_grams) / len(claim_grams)


def _year_ranges(text: str) -> set[tuple[str, str]]:
    """抽取「YYYY 至 YYYY」年份区间集合（单年陈述不参与区间冲突判定）。"""
    return {(start, end) for start, end in _YEAR_RANGE_RE.findall(normalize_text(text))}


def _units(text: str) -> set[str]:
    """抽取单位 token 集合（长单位优先匹配）。"""
    return set(_UNIT_RE.findall(normalize_text(text)))


def _has_negation(text: str) -> bool:
    """是否含否定 / 限定词（极性比较用）。"""
    norm = normalize_text(text)
    return any(marker in norm for marker in _NEGATION_MARKERS)


def _detect_conflict(claim_text: str, unit_text: str) -> str | None:
    """矛盾启发式：返回中文冲突理由，无冲突返回 ``None``。

    数值 / 日期 / 单位 / 否定极性冲突需覆盖率 ≥ ``CONFLICT_MIN_COVERAGE``
    （避免无关文本误报）；反义词对属强信号，命中即判冲突。
    """
    coverage = _coverage(claim_text, unit_text)
    if coverage >= CONFLICT_MIN_COVERAGE:
        claim_ranges, unit_ranges = _year_ranges(claim_text), _year_ranges(unit_text)
        if claim_ranges and unit_ranges and claim_ranges != unit_ranges:
            return f"年份区间不一致（{sorted(claim_ranges)} vs {sorted(unit_ranges)}）"
        claim_units, unit_units = _units(claim_text), _units(unit_text)
        if claim_units and unit_units and claim_units != unit_units:
            return f"单位不一致（{sorted(claim_units)} vs {sorted(unit_units)}）"
        if _has_negation(claim_text) != _has_negation(unit_text):
            return "否定极性相反"
    for positive, negative in _ANTONYM_PAIRS:
        if (positive in claim_text and negative in unit_text) or (
            negative in claim_text and positive in unit_text
        ):
            return f"反义表述冲突（{positive} / {negative}）"
    return None


def _iter_units(source: str) -> list[tuple[str, int, int]]:
    """把源文切成候选证据单元：整块 + 全部句子（归一化文本偏移）。

    整块单元保证「同一块内跨句组合」可被核验（如先出现实体、后出现属性）；
    句子单元保证证据定位尽量精确。返回顺序固定（整块在前、句子按出现序），
    最佳单元取覆盖率最高者，同分保留先出现者，故结果确定。
    """
    norm_source = normalize_text(source)
    units: list[tuple[str, int, int]] = []
    if norm_source:
        units.append((norm_source, 0, len(norm_source)))
    for match in _SENTENCE_RE.finditer(norm_source):
        text = match.group(0)
        if text.strip():
            units.append((text, match.start(), match.end()))
    return units
