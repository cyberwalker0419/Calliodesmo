"""QA 答案后处理：模板前缀剥离 + 句级引注纪律（纯函数、确定性、无 LLM）。

P9 Task 1。真模型答案常见的两类「不可核验」噪声：

1. **模板套话**：「根据提供的上下文，」「综上所述，」不是可核查声明，却会进入
   声明切分，拉低 ``uncited_claim_rate`` 与接地度；
2. **缺引注**：答案句子没有 ``[chunk_id]`` 时，P8 口径只计入 uncited，不做支撑
   判定——但句子可能明明由某块证据支撑。

本模块只做两件事：剥离套话；**在可核验时**为无引注句子补引注（证据覆盖率达标
才补，绝不为无据句子编造引注）。引注补全的判定依据是核验引擎的同一覆盖率口径
（``verification.engine.evidence_coverage``），保证「补的引注」与「核验结论」一致。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from calliodesmo.verification.engine import evidence_coverage, normalize_text

#: 句级补引注的最低证据覆盖率（与跨文档「不确定」下界同量级，宁可少补不漏证）
DEFAULT_ATTACH_MIN_COVERAGE = 0.60

#: 句末标点 / 换行（与验证流水线同口径）
_SENTENCE_RE = re.compile(r"[^。！？；\n]+[。！？；\n]?")
#: 引注形态（与答案合成器 / 验证流水线一致）
_CITATION_RE = re.compile(r"\[([a-zA-Z0-9_\-:.#]+)\]")

#: 开头套话（「根据提供的上下文」类）
_PREAMBLE_RE = re.compile(
    r"^\s*(?:根据|基于|依据|按照|结合|参考)"
    r"(?:您|你)?(?:提供的|给定的|上述的?|以上的?|所给的?|给出的?|这些)?"
    r"(?:上下文|材料|资料|文档|信息|内容|文本|检索结果)"
    r"(?:信息|内容|数据)?[，,。:：、\s]*"
)
#: 总结 / 连接词开头（剥离后保留实质内容）
_CONNECTIVE_RE = re.compile(
    r"^\s*(?:综上所述|总的来说|总而言之|总之|综上|因此|所以|此外|另外|同时|而且|不过|然而|其中|"
    r"具体来说|具体而言|首先|其次|最后)[，,：:\s]*"
)
#: 纯元话语句子（不承载事实，不参与核验与引注）
_META_RE = re.compile(
    r"以上(?:信息|内容)?(?:仅供)?参考|希望(?:对你|对您)?(?:有)?帮助|"
    r"如需(?:更多|进一步|其他)|如有(?:疑问|需要)|请(?:告知|提供更多)"
)


def strip_answer_boilerplate(text: str) -> str:
    """剥离答案开头的模板套话与总结连接词（幂等，只动开头）。"""
    result = text.strip()
    for _ in range(8):
        before = result
        result = _PREAMBLE_RE.sub("", result)
        result = _CONNECTIVE_RE.sub("", result)
        if result == before:
            break
    return result.strip()


def is_meta_sentence(sentence: str) -> bool:
    """是否纯元话语 / 免责句（不作可核查声明参与核验）。"""
    return bool(_META_RE.search(normalize_text(sentence)))


def attach_sentence_citations(
    answer: str,
    candidates: Mapping[str, str],
    *,
    min_coverage: float = DEFAULT_ATTACH_MIN_COVERAGE,
) -> tuple[str, list[dict]]:
    """为无引注句子补引注（仅当某块证据覆盖率达标）。

    规则：
    - 已含**有效**引注（ID 在 ``candidates`` 中）的句子保持原样；
    - 引注 ID 不在候选集合中视为无效，删除后按无引注处理（不保留幻觉引注）；
    - 无引注句取覆盖率最高且 ≥ ``min_coverage`` 的单块补 ``[chunk_id]``；
    - 元话语句 / 过短句不补。

    返回 ``(新文本, 补注记录)``；补注记录形如
    ``{"sentence": ..., "chunk_id": ..., "coverage": ...}``，供调用方审计 / 统计。
    """
    if not answer or not candidates:
        return answer, []

    parts: list[str] = []
    attachments: list[dict] = []
    last = 0
    for match in _SENTENCE_RE.finditer(answer):
        parts.append(answer[last : match.start()])
        parts.append(_process_sentence(match.group(0), candidates, min_coverage, attachments))
        last = match.end()
    parts.append(answer[last:])
    return "".join(parts), attachments


def _process_sentence(
    sentence: str,
    candidates: Mapping[str, str],
    min_coverage: float,
    attachments: list[dict],
) -> str:
    """处理单句：删无效引注 → 有效引注则跳过 → 否则找最佳证据补注。"""
    cleaned = _drop_invalid_citations(sentence, candidates)
    if any(cid in candidates for cid in _CITATION_RE.findall(cleaned)):
        return cleaned
    body = cleaned.strip()
    if len(normalize_text(body)) < 4 or is_meta_sentence(body):
        return cleaned
    best: tuple[float, str] | None = None
    for chunk_id in sorted(candidates):
        coverage = evidence_coverage(body, candidates[chunk_id])
        if coverage >= min_coverage and (best is None or coverage > best[0]):
            best = (coverage, chunk_id)
    if best is None:
        return cleaned
    coverage, chunk_id = best
    attachments.append({"chunk_id": chunk_id, "coverage": round(coverage, 4)})
    return _append_citation(cleaned, chunk_id)


def _drop_invalid_citations(sentence: str, candidates: Mapping[str, str]) -> str:
    """删除不在候选集合中的引注 ID（模型幻觉引注）。"""

    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in candidates else ""

    return _CITATION_RE.sub(_replace, sentence)


def _append_citation(sentence: str, chunk_id: str) -> str:
    """在句末（尾部空白之前）追加引注，保留原有换行 / 空白。"""
    stripped = sentence.rstrip()
    trailing = sentence[len(stripped) :]
    return f"{stripped} [{chunk_id}]{trailing}"


__all__ = [
    "DEFAULT_ATTACH_MIN_COVERAGE",
    "attach_sentence_citations",
    "is_meta_sentence",
    "strip_answer_boilerplate",
]
