"""证据自验证：quote 子串校验 → 置信封顶 + warning（纯函数，无夹具，离线可测）。

P6 边界内的轻量自验证（跨文档证据核验 / 幻觉判定归 P8）：

- 每条证据的 ``quote`` 去全部空白后必须为对应材料源文（同样去空白）的子串；
- 失配条目（含 chunk_id 不在材料、空白 quote）``confidence`` 封顶 ``CONFIDENCE_CAP``
  并记 warning；封顶取 min，原置信更低者不上调；
- 失败占比 **>** ``FAILURE_RATIO_THRESHOLD``（30%）→ 信封状态降为 ``partial``
  （恰 30% 不降级；已 partial / failed 的信封不升级）。

证据节点判定：payload 递归遍历中同时含 ``chunk_id`` 与 ``quote`` 且两者均为字符串的
dict（即 ``Evidence.model_dump`` 形状）。自报置信仅作排序 / 复核标记，校准（ECE）留痕移交 P8。
"""

import copy
import re
from collections.abc import Iterator, Mapping
from typing import Any

from calliodesmo.analysis.schemas import (
    CONFIDENCE_CAP,  # 单一事实源（schemas）：失配封顶与缺证据降置信共用，本模块保持导出路径
    AnalysisEnvelope,
    AnalysisStatus,
)

#: 失败占比阈值：严格大于该值才降级 partial
FAILURE_RATIO_THRESHOLD = 0.3

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    """匹配归一化：去除全部空白字符（含全角空格 / 换行 / 制表符）后比较。

    空白差异属排版噪声（PDF 抽取 / 块边界），不应判为失配；归一化后做子串匹配。
    """
    return _WHITESPACE_RE.sub("", text)


def verify_evidence(envelope: AnalysisEnvelope, sources: Mapping[str, str]) -> AnalysisEnvelope:
    """校验信封 payload 内全部证据的 quote 是否为对应源文子串（纯函数，不改入参）。

    参数:
        envelope: 待校验信封（``payload`` 为对应报告模型的 ``model_dump``）。
        sources: ``chunk_id → 源文`` 映射（材料采集器提供，见 Task 9）。

    返回:
        新信封：失配证据置信封顶 0.3、warnings 追加可读原因；失败占比 >30% 时
        ``status`` 降为 ``partial``（不升级）。入参信封与 payload 不被就地修改。
    """
    payload = copy.deepcopy(envelope.payload)
    new_warnings: list[str] = []
    total = 0
    failed = 0
    for node in _iter_evidence_nodes(payload):
        total += 1
        reason = _check_quote(node, sources)
        if reason is None:
            continue
        failed += 1
        _cap_confidence(node)
        new_warnings.append(f"证据校验失败：chunk_id={node['chunk_id']}，{reason}")

    status = envelope.status
    if total > 0 and failed / total > FAILURE_RATIO_THRESHOLD and status is AnalysisStatus.OK:
        status = AnalysisStatus.PARTIAL

    return envelope.model_copy(
        update={
            "payload": payload,
            "warnings": [*envelope.warnings, *new_warnings],
            "status": status,
        }
    )


def _iter_evidence_nodes(node: Any) -> Iterator[dict[str, Any]]:
    """深度优先遍历，产出全部证据节点（同时含字符串 ``chunk_id`` 与 ``quote`` 的 dict）。"""
    if isinstance(node, dict):
        if isinstance(node.get("chunk_id"), str) and isinstance(node.get("quote"), str):
            yield node
        for value in node.values():
            yield from _iter_evidence_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_evidence_nodes(item)


def _check_quote(node: dict[str, Any], sources: Mapping[str, str]) -> str | None:
    """单条证据校验：返回失败原因（可读），通过返回 None。"""
    quote = normalize_for_match(node["quote"])
    if not quote:
        return "quote 去空白后为空"
    source = sources.get(node["chunk_id"])
    if source is None:
        return "chunk_id 不在材料中"
    if quote not in normalize_for_match(source):
        return "quote 非对应源文子串（去空白后匹配）"
    return None


def _cap_confidence(node: dict[str, Any]) -> None:
    """失配证据置信封顶：取 min（原置信更低不上调；缺省 / 非法值按 1.0 处理）。"""
    current = node.get("confidence")
    base = current if isinstance(current, (int, float)) and not isinstance(current, bool) else 1.0
    node["confidence"] = min(base, CONFIDENCE_CAP)
