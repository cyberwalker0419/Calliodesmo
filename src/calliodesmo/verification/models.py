"""证据核验数据契约（不可变 dataclass + 判定枚举）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    """声明级判定（顺序即优先级：contradicted > supported > uncertain > unsupported）。"""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class Claim:
    """待核验声明。

    参数:
        text: 声明原文（自由文本，v1 不要求自带引注）。
        chunk_id: 声明声称的证据块；不可见 / 不存在时与「无证据」同语义。
        quote: 声明附带的引注原文；为空则走跨文档检索。
        topic: 主题 / 实体名（跨文档检索的锚点，可选）。
    """

    text: str
    chunk_id: str | None = None
    quote: str | None = None
    topic: str | None = None


@dataclass(frozen=True)
class EvidenceSpan:
    """证据定位：``start`` / ``end`` 为**归一化源文**中的偏移（非原始字符偏移）。

    归一化会去除空白并做 NFKC 折叠，故偏移只用于同一归一化文本内的定位与高亮，
    不保证可直接切原始字符串；原始 quote 由 ``quote`` 字段保留。
    """

    chunk_id: str
    quote: str
    start: int
    end: int
    match_type: str  # quote | cross_document


@dataclass(frozen=True)
class VerificationResult:
    """单条声明的核验结果。

    ``confidence`` 是核验器自报置信（未经 ECE 校准，T4 再做温度缩放）；
    ``reason`` 为可审计的中文判定理由，不含原文片段以外的新信息。
    """

    claim: Claim
    verdict: Verdict
    confidence: float
    reason: str
    evidence: tuple[EvidenceSpan, ...] = field(default_factory=tuple)
