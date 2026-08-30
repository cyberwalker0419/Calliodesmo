"""提示词模板加载与渲染：版本化模板 + 令牌替换 + 预算双闸（P6 Task 6）。

模板入 ``config/analysis_prompts/*.txt`` 版本化（头部 ``# version: N``），遵循
``ecl/extractor.py`` 范式：系统角色声明 + 「严格只输出一个 JSON 对象」+ 输出 schema
示例；系统段统一含 ``[ANALYSIS:<type>]`` 标记（StubLLM 分发锚点，Task 8 消费）。

- ``parse_template`` / ``render_prompt`` 为纯函数（无夹具、CI 可覆盖）；``load_template``
  默认从仓库根 ``config/analysis_prompts`` 读取（相对 CWD，与既有配置文件路径惯例一致，
  可经 ``template_dir`` 覆盖，测试用临时目录）。
- 模板分 ``===SYSTEM===`` / ``===USER===`` 两段：system 承载角色声明与输出契约，
  user 承载 ``{materials}`` / ``{question}`` 等令牌。
- 令牌替换：``{materials}`` / ``{question}`` / ``{schema}`` / ``{instruction}``。
  ``{instruction}`` 属自定义类（Task 22）：只替换进 user 段，system 段的该令牌被清除
  而非替换——指令与 system 约束隔离，收敛注入面。替换用逐令牌 ``str.replace`` 而非
  ``str.format``——模板内的输出 schema 示例含 JSON 花括号，``format`` 会误伤；且材料
  **最后**替换，材料文本中的令牌字面量不会被二次替换（注入边界，见测试锁定）。
- 预算双闸在 render 侧执行：``max_chunks``（材料块数）+ ``max_input_chars``（材料文本
  总字符）；采集侧截断属材料采集器（Task 9），此处为成本闸兜底。
- ``prompt_version = "<type>.v<version>"`` 落运行记录，评估可按版本切片。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from calliodesmo.analysis.schemas import AnalysisType

#: 默认模板目录（相对 CWD，与 ``config/`` 下既有配置文件路径惯例一致；可经入参覆盖）
DEFAULT_TEMPLATE_DIR: Path = Path("config/analysis_prompts")

#: 系统 / 用户段标记行（模板文件中独立成行）
SYSTEM_MARKER = "===SYSTEM==="
USER_MARKER = "===USER==="

#: 预算双闸默认值：镜像 ``config.py`` ``Settings.analysis_max_chunks`` /
#: ``analysis_max_input_chars`` 的默认值；引擎侧（Task 10）经 settings 显式传入，
#: 直接调用 ``render_prompt`` 时落此默认。配置默认值变更须双同步。
DEFAULT_MAX_CHUNKS = 40
DEFAULT_MAX_INPUT_CHARS = 24000

#: 空材料时 ``{materials}`` 令牌渲染的占位（提交侧空材料已由 worker 拦为失败，此处兜底）
_EMPTY_MATERIALS = "(无材料)"

#: ``{schema}`` 令牌未提供时的占位（自定义类的输出 schema，Task 22 消费）
_EMPTY_SCHEMA = "(无)"

#: 版本头：模板文件首行 ``# version: N``（N 为正整数）
_VERSION_RE = re.compile(r"^#\s*version:\s*(\d+)\s*$")


class PromptTemplateError(ValueError):
    """模板文件不存在或格式非法（版本头 / SYSTEM / USER 段缺失）。"""


@dataclass(frozen=True)
class PromptTemplate:
    """解析后的提示词模板：版本号 + system / user 两段。"""

    version: int
    system: str
    user: str


@dataclass(frozen=True)
class RenderedPrompt:
    """渲染产物：system / user 文本 + 提示词版本 + 预算截断后实际纳入的材料块 ID。

    ``included_chunk_ids`` 供引擎（Task 10）装配信封 ``source_chunk_ids``——
    render 侧预算可能截断材料，落库口径以实际进入提示词的块为准。
    """

    system: str
    user: str
    prompt_version: str
    included_chunk_ids: tuple[str, ...]


def parse_template(raw: str) -> PromptTemplate:
    """解析模板文本（纯函数）：首行版本头 + ``===SYSTEM===`` / ``===USER===`` 两段。

    首行非 ``# version: N``、任一段缺失或为空 → ``PromptTemplateError``。
    标记行之前（版本头所在行）之外的游离内容忽略，保持宽容。
    """
    lines = raw.splitlines()
    if not lines:
        raise PromptTemplateError("模板内容为空：首行必须为 `# version: N` 版本注释")
    match = _VERSION_RE.match(lines[0].strip())
    if match is None:
        raise PromptTemplateError(f"模板首行必须为 `# version: N` 版本注释，实际为: {lines[0]!r}")
    version = int(match.group(1))

    section: str | None = None
    system_lines: list[str] = []
    user_lines: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == SYSTEM_MARKER:
            section = "system"
            continue
        if stripped == USER_MARKER:
            section = "user"
            continue
        if section == "system":
            system_lines.append(line)
        elif section == "user":
            user_lines.append(line)

    system = "\n".join(system_lines).strip()
    user = "\n".join(user_lines).strip()
    if not system or not user:
        raise PromptTemplateError(f"模板必须包含非空的 {SYSTEM_MARKER} 与 {USER_MARKER} 两段")
    return PromptTemplate(version=version, system=system, user=user)


def load_template(template_name: str, *, template_dir: str | Path | None = None) -> PromptTemplate:
    """按文件名加载模板（``<template_dir>/<template_name>``，默认 ``config/analysis_prompts``）。

    文件不存在抛 ``PromptTemplateError``（未注册类型无模板即不可提交，与注册表口径一致）。
    """
    directory = Path(template_dir) if template_dir is not None else DEFAULT_TEMPLATE_DIR
    path = directory / template_name
    if not path.is_file():
        raise PromptTemplateError(f"模板文件不存在: {path}")
    return parse_template(path.read_text(encoding="utf-8"))


def _select_materials(
    materials: Sequence[Any], max_chunks: int, max_input_chars: int
) -> list[tuple[str, str]]:
    """双闸预算选择材料（保序）：先按块数闸取前 ``max_chunks`` 条，再按字符闸累计。

    - 字符闸按材料文本长度累计，累计不超 ``max_input_chars`` 的整块纳入；
    - 首块单独超预算时裁剪首块文本至预算（成本闸兜底，不产出空提示词）；
    - 材料项走鸭子类型（``chunk_id`` / ``text`` 属性），Task 10 的 ``AnalysisMaterial``
      满足该形状；缺属性抛 ``TypeError``（友好报错）。
    """
    selected: list[tuple[str, str]] = []
    total = 0
    for material in list(materials)[:max_chunks]:
        chunk_id = getattr(material, "chunk_id", None)
        text = getattr(material, "text", None)
        if chunk_id is None or text is None:
            raise TypeError("材料项须带 chunk_id 与 text 属性（AnalysisMaterial 鸭子类型）")
        text = str(text)
        if total + len(text) > max_input_chars:
            if not selected:
                selected.append((str(chunk_id), text[:max_input_chars]))
            break
        selected.append((str(chunk_id), text))
        total += len(text)
    return selected


def render_prompt(
    template: PromptTemplate,
    task_type: AnalysisType | str,
    *,
    materials: Sequence[Any] = (),
    question: str = "",
    schema: dict | None = None,
    instruction: str = "",
    max_chunks: int | None = None,
    max_input_chars: int | None = None,
) -> RenderedPrompt:
    """渲染分析提示词（纯函数）：令牌替换 + 预算双闸 + 版本号。

    - 令牌替换：``{materials}`` / ``{question}`` / ``{schema}`` / ``{instruction}``；
      材料最后替换，材料文本内的令牌字面量不被二次替换；
    - **``{instruction}`` 注入隔离（Task 22）**：自定义指令只替换进 user 段，system 段
      的该令牌被清除而非替换——指令与 system 约束隔离，收敛注入面（见注入探针测试）；
    - 预算双闸：``max_chunks``（默认 ``DEFAULT_MAX_CHUNKS``）+ ``max_input_chars``
      （默认 ``DEFAULT_MAX_INPUT_CHARS``），引擎侧经 settings 显式传入；
    - ``prompt_version = "<type>.v<version>"``，落运行记录，评估按版本切片。

    ``materials`` 项走鸭子类型（``chunk_id`` / ``text`` 属性）。``task_type`` 接受
    枚举或其字符串值，非法值经枚举转换抛 ``ValueError``。
    """
    t = AnalysisType(task_type)
    chunk_limit = DEFAULT_MAX_CHUNKS if max_chunks is None else max_chunks
    char_limit = DEFAULT_MAX_INPUT_CHARS if max_input_chars is None else max_input_chars
    selected = _select_materials(materials, chunk_limit, char_limit)
    materials_block = (
        "\n\n".join(f"[chunk_id={chunk_id}]\n{text}" for chunk_id, text in selected)
        or _EMPTY_MATERIALS
    )
    schema_block = json.dumps(schema, ensure_ascii=False) if schema is not None else _EMPTY_SCHEMA

    def _substitute(text: str, *, allow_instruction: bool) -> str:
        # question / schema / instruction 先行，材料最后：材料文本内的令牌字面量不被二次替换；
        # instruction 仅替换进 user 段（与 system 隔离），system 段令牌清除不泄露指令内容
        result = text.replace("{question}", question).replace("{schema}", schema_block)
        result = result.replace("{instruction}", instruction if allow_instruction else "")
        return result.replace("{materials}", materials_block)

    return RenderedPrompt(
        system=_substitute(template.system, allow_instruction=False),
        user=_substitute(template.user, allow_instruction=True),
        prompt_version=f"{t.value}.v{template.version}",
        included_chunk_ids=tuple(chunk_id for chunk_id, _ in selected),
    )
