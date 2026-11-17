"""输出层注入防御：全文倾倒 / 内部元数据 / 系统提示回声 / 注入服从话术（P9 Task 2）。

提示层（system prompt）只能降低模型服从注入的概率，挡不住「已经发生在输出里」的
泄漏。P8 `--real` 注入探针的两条违规都属输出层：一条把内部笔记全文代码块倒出，
一条列出机密文档元数据。本模块是最后一道闸：

- ``verbatim_dump``：输出与任一可见源文存在 ≥ ``MAX_VERBATIM_CHARS`` 的连续重合
  （归一化后滑窗匹配）——正常引用远短于此，全文倾倒会被拦；
- ``internal_metadata``：内部字段名（``access_level`` / ``owner_id`` 等）出现在
  「字段: 值」形态，或 ≥2 个字段名同时出现——拒绝话术里单个字段名不误伤；
- ``system_prompt_leak``：输出复述了系统提示的连续片段（≥ ``PROMPT_WINDOW`` 字）；
- ``injection_compliance``：输出宣称「已忽略以上指令」等**实际照做**的话术；拒绝
  执行（「不能执行忽略指令的要求」）不在其列——P8 v2 的误判教训。

拦截是**整段替换**为 :data:`SAFE_BLOCK_TEXT`（不静默丢弃：调用方把类别记入审计 /
侧车）。纯函数、无 LLM、无网络，离线可测。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: 源文连续重合阈值（字符）；正常引用远短于此
MAX_VERBATIM_CHARS = 200
#: 滑窗步长（保证任意 ≥ 阈值 + 步长的连续重合必被某窗命中）
_WINDOW_STEP = 20
#: 系统提示片段最小匹配长度（归一化字符）
PROMPT_WINDOW = 24
#: 拦截后的统一安全话术（不暴露具体命中的内部内容）
SAFE_BLOCK_TEXT = (
    "该输出因安全策略被拦截：检测到不安全的输出内容，未予返回。请调整问题或联系管理员。"
)

#: 内部字段名（对用户不可见）
_METADATA_TOKENS = (
    "access_level",
    "library_scope",
    "owner_id",
    "project_id",
    "team_id",
    "doc_id",
    "chunk_id",
    "prompt_version",
    "system_prompt",
    "jwt_secret",
)
#: 「字段: 值 / 字段=值 / 字段|值」形态（单个字段名不判违规）
_METADATA_VALUE_RE = re.compile(
    r"(?i)\b(" + "|".join(_METADATA_TOKENS) + r")\b\s*(?:[:=：|]\s*[^\s，。;；、]{1,64})"
)
_METADATA_TOKEN_RE = re.compile(r"(?i)\b(" + "|".join(_METADATA_TOKENS) + r")\b")
#: 注入服从话术（要求「实际照做」语义；单纯复述/拒绝不命中）
_INJECTION_COMPLIANCE_RE = re.compile(
    r"(?:已忽略.{0,8}(?:指令|要求)|忽略(?:以上|先前|之前).{0,6}(?:并|按|改).{0,8}(?:执行|输出|回答|提供)|"
    r"(?:下面|以下)(?:是|为).{0,8}(?:系统提示|提示词|内部指令|内部笔记))"
)
_SKIP_PAYLOAD_KEYS = frozenset(
    {
        "chunk_id",
        "doc_id",
        "source_chunk_ids",
        "quote",
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


@dataclass(frozen=True)
class GuardViolation:
    """单条违规：类别 + 可读说明（不含原文）。"""

    kind: str
    detail: str


@dataclass(frozen=True)
class GuardResult:
    """守卫结果：``pass`` 保留原文；任一违规则整段替换为安全话术。"""

    text: str
    violations: tuple[GuardViolation, ...]
    action: str  # "pass" | "blocked"

    @property
    def blocked(self) -> bool:
        return self.action == "blocked"


def guard_output(
    text: str,
    *,
    sources: Mapping[str, str] | list[str] | tuple[str, ...] = (),
    system_prompt: str | None = None,
) -> GuardResult:
    """检查并（必要时）拦截模型输出。

    参数:
        text: 待交付的输出文本。
        sources: 当前可见源文（``chunk_id → 源文`` 映射或文本序列）。
        system_prompt: 本轮系统提示（用于回声检测；不匹配则不查该面）。
    """
    if not text or not text.strip():
        return GuardResult(text=text, violations=(), action="pass")

    violations: list[GuardViolation] = []
    source_texts = list(sources.values()) if isinstance(sources, Mapping) else list(sources)

    if _has_verbatim_dump(text, source_texts):
        violations.append(
            GuardViolation("verbatim_dump", f"输出包含 ≥{MAX_VERBATIM_CHARS} 字的源文连续重合")
        )
    metadata_hits = _metadata_hits(text)
    if metadata_hits:
        violations.append(GuardViolation("internal_metadata", f"输出含内部字段：{metadata_hits}"))
    if system_prompt and _echoes_prompt(text, system_prompt):
        violations.append(GuardViolation("system_prompt_leak", "输出复述了系统提示片段"))
    if _INJECTION_COMPLIANCE_RE.search(_normalize(text)):
        violations.append(GuardViolation("injection_compliance", "输出宣称已服从注入指令"))

    if violations:
        return GuardResult(text=SAFE_BLOCK_TEXT, violations=tuple(violations), action="blocked")
    return GuardResult(text=text, violations=(), action="pass")


def guard_payload(
    payload: Any, *, sources: Mapping[str, str] | list[str] | tuple[str, ...] = ()
) -> tuple[Any, list[GuardViolation]]:
    """递归扫描结构化 payload 的字符串字段，违规字段替换为安全话术。

    证据节点（``chunk_id`` + ``quote``）与结构键（``chunk_id`` / ``model`` 等）不扫描：
    它们是协议字段，引用原文属合法结构，不是「模型倾倒」。返回 ``(新 payload, 违规)``，
    不修改入参。
    """
    violations: list[GuardViolation] = []

    def _walk(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            if isinstance(node.get("chunk_id"), str) and isinstance(node.get("quote"), str):
                return {k: (v if isinstance(v, str) else _walk(v, k)) for k, v in node.items()}
            return {k: (v if k in _SKIP_PAYLOAD_KEYS else _walk(v, k)) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item, key) for item in node]
        if isinstance(node, str):
            result = guard_output(node, sources=sources)
            if result.blocked:
                violations.extend(result.violations)
                return result.text
            return node
        return node

    return _walk(payload), violations


def _normalize(text: str) -> str:
    """归一化：NFKC + 去全部空白（匹配容忍排版差异）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


_CITATION_TOKEN_RE = re.compile(r"\[[a-zA-Z0-9_\-:.#]+\]")


def _has_verbatim_dump(text: str, sources: list[str]) -> bool:
    """输出与任一源文是否存在 ≥ 阈值的连续重合（滑窗 + 步长覆盖）。

    引注标记（``[chunk_id]``）先剔除：它们由后处理插入，会打断源文的连续重合，
    不能成为绕过全文倾倒检测的缝隙。
    """
    norm_text = _normalize(_CITATION_TOKEN_RE.sub("", text))
    if len(norm_text) < MAX_VERBATIM_CHARS:
        return False
    norm_sources = [_normalize(source) for source in sources if source]
    norm_sources = [source for source in norm_sources if len(source) >= MAX_VERBATIM_CHARS]
    if not norm_sources:
        return False
    for start in range(0, len(norm_text) - MAX_VERBATIM_CHARS + 1, _WINDOW_STEP):
        window = norm_text[start : start + MAX_VERBATIM_CHARS]
        if any(window in source for source in norm_sources):
            return True
    return False


def _metadata_hits(text: str) -> str:
    """内部字段命中：任一「字段: 值」形态，或 ≥2 个不同字段名。"""
    if _METADATA_VALUE_RE.search(text):
        return "字段赋值形态"
    tokens = {match.lower() for match in _METADATA_TOKEN_RE.findall(text)}
    return "多字段列举" if len(tokens) >= 2 else ""


def _echoes_prompt(text: str, system_prompt: str) -> bool:
    """输出是否复述系统提示的连续片段（归一化后 ≥ ``PROMPT_WINDOW`` 字）。"""
    norm_text = _normalize(text)
    norm_prompt = _normalize(system_prompt)
    if len(norm_prompt) < PROMPT_WINDOW:
        return norm_prompt in norm_text if norm_prompt else False
    for start in range(0, len(norm_prompt) - PROMPT_WINDOW + 1, 8):
        if norm_prompt[start : start + PROMPT_WINDOW] in norm_text:
            return True
    return False


__all__ = [
    "MAX_VERBATIM_CHARS",
    "PROMPT_WINDOW",
    "SAFE_BLOCK_TEXT",
    "GuardResult",
    "GuardViolation",
    "guard_output",
    "guard_payload",
]
