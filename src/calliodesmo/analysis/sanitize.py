"""自定义分析用户 schema 清洗：拒 $ref / 递归 / 超深 / 超大 + 安全子集裁剪（P6 Task 22）。

自定义分析的用户输出 schema 是显式注入面（经 ``{schema}`` 令牌进提示词，最终发往
provider），故发送前须经**安全闸门**（``sanitize_user_schema``）与**安全子集裁剪**
（``trim_to_safe_json_schema``）两道：

- ``sanitize_user_schema``：拒 ``$ref``（引用外部 / 递归定义）/ 递归嵌套（循环引用）/
  嵌套深度 >``MAX_SCHEMA_DEPTH`` / 字段（键）总数 >``MAX_SCHEMA_FIELDS`` /
  序列化字节超 ``analysis_custom_schema_max_bytes``（默认 ``DEFAULT_CUSTOM_SCHEMA_MAX_BYTES``）；
  违规抛可读 ``SchemaSanitizeError``（API 层转 400，错误信息供前端展示）。
- ``trim_to_safe_json_schema``：provider 发送前裁剪为 JSON Schema 安全子集——
  仅保留白名单键（``_SAFE_SCHEMA_KEYS``），未知键（注入面）一律去除；
  递归处理 ``properties`` / ``items`` 并限深（防御纵深）。

全链纯函数、离线可测。**完整 JSON Schema 语义校验**（引 ``jsonschema``）随团队级
模板注册表一并评估（P7，锚点 2026-W47，见计划「范围外」）；本阶段只做安全闸门 +
结构裁剪，不引入重依赖。

注入边界（与 ``prompts.render_prompt`` 协同）：自定义 ``instruction`` 与 ``schema``
只进 **user** 消息，与 **system** 隔离（见 ``tests/test_analysis_engine.py`` 注入探针）；
材料仍全经 ``visible_to`` 红线（``analysis/materials.py``），本模块不放松该边界。
"""

from __future__ import annotations

import json
from typing import Any

#: 嵌套深度上限（根为第 1 层）；``> MAX_SCHEMA_DEPTH`` 拒绝
MAX_SCHEMA_DEPTH = 4

#: 字段（键）总数上限（结构化 DoS 面，跨层累计）；``> MAX_SCHEMA_FIELDS`` 拒绝
MAX_SCHEMA_FIELDS = 30

#: 序列化字节上限默认值：镜像 ``config.py`` ``Settings.analysis_custom_schema_max_bytes``。
#: 配置默认值变更须双同步（``tests/test_analysis_sanitize.py`` 有对账断言锚点）。
DEFAULT_CUSTOM_SCHEMA_MAX_BYTES = 4096

#: JSON Schema 安全子集白名单：裁剪仅保留这些键，未知键一律去除（收敛注入面）。
#: 取结构化 / 描述性常用键；``$ref`` 等引用键与任意自定义键均不在列。
_SAFE_SCHEMA_KEYS = frozenset(
    {"type", "properties", "items", "required", "enum", "title", "description"}
)


class SchemaSanitizeError(ValueError):
    """用户输出 schema 未通过安全清洗：消息可读（API 层转 400 供前端展示）。"""


def sanitize_user_schema(schema: Any, *, max_bytes: int | None = None) -> dict:
    """清洗用户输出 schema；违规抛 ``SchemaSanitizeError``，通过则返回原 schema。

    拒绝路径（五类 + 根形态）：

    - 根非 JSON 对象（输出 schema 必须是对象）；
    - 任意深度含 ``$ref``（引用外部 / 递归定义，注入与解析歧义面）；
    - 递归嵌套（循环引用：同一容器再次出现在自身遍历路径上，遍历 / 序列化无终止）；
    - 嵌套深度 > ``MAX_SCHEMA_DEPTH``（根为第 1 层）；
    - 字段（键）总数 > ``MAX_SCHEMA_FIELDS``（跨层累计，结构化 DoS 面）；
    - 序列化字节 > ``max_bytes``（默认 ``DEFAULT_CUSTOM_SCHEMA_MAX_BYTES``）。

    参数:
        schema: 用户提交的输出 schema（API 侧 ``AnalysisCustomRequest.schema_``）。
        max_bytes: 序列化字节上限；``None`` = 用 ``DEFAULT_CUSTOM_SCHEMA_MAX_BYTES``
            （API 侧经 ``settings.analysis_custom_schema_max_bytes`` 显式传入）。

    返回:
        通过清洗的原 schema（调用方随后经 ``trim_to_safe_json_schema`` 裁剪为安全子集）。
    """
    if not isinstance(schema, dict):
        raise SchemaSanitizeError("自定义输出 schema 必须是 JSON 对象")
    _walk(schema, depth=1, ancestors=set(), key_count=[0])
    try:
        encoded = json.dumps(schema, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SchemaSanitizeError(f"自定义输出 schema 不可序列化：{exc}") from exc
    limit = DEFAULT_CUSTOM_SCHEMA_MAX_BYTES if max_bytes is None else max_bytes
    if len(encoded.encode("utf-8")) > limit:
        raise SchemaSanitizeError(f"自定义输出 schema 序列化大小超过上限（{limit} 字节）")
    return schema


def _walk(node: Any, depth: int, ancestors: set[int], key_count: list[int]) -> None:
    """深度优先遍历校验：循环引用 / 深度 / 键数 / ``$ref``（违规即抛，先于序列化）。

    ``ancestors`` 记录当前递归路径上的容器 ``id``（引用环判定，仅祖先算循环）；
    ``key_count`` 为单元素列表（可变计数器，跨层累计字典键总数）。标量不递归。
    """
    if isinstance(node, dict):
        if id(node) in ancestors:
            raise SchemaSanitizeError("自定义输出 schema 含递归嵌套（循环引用）")
        if depth > MAX_SCHEMA_DEPTH:
            raise SchemaSanitizeError(f"自定义输出 schema 嵌套深度超过 {MAX_SCHEMA_DEPTH} 层")
        ancestors.add(id(node))
        for key, value in node.items():
            key_count[0] += 1
            if key_count[0] > MAX_SCHEMA_FIELDS:
                raise SchemaSanitizeError(
                    f"自定义输出 schema 字段（键）数量超过 {MAX_SCHEMA_FIELDS}"
                )
            if key == "$ref":
                raise SchemaSanitizeError(
                    "自定义输出 schema 不得包含 $ref（引用外部 / 递归定义，注入面）"
                )
            _walk(value, depth + 1, ancestors, key_count)
        ancestors.discard(id(node))
    elif isinstance(node, list):
        if id(node) in ancestors:
            raise SchemaSanitizeError("自定义输出 schema 含递归嵌套（循环引用）")
        if depth > MAX_SCHEMA_DEPTH:
            raise SchemaSanitizeError(f"自定义输出 schema 嵌套深度超过 {MAX_SCHEMA_DEPTH} 层")
        ancestors.add(id(node))
        for item in node:
            _walk(item, depth + 1, ancestors, key_count)
        ancestors.discard(id(node))
    # 标量（字符串 / 数值 / 布尔 / None）：不计深度、不递归


def trim_to_safe_json_schema(schema: Any, *, _depth: int = 1) -> dict:
    """裁剪为 JSON Schema 安全子集：仅保留白名单键，去未知键，限深递归。

    - 仅保留 ``_SAFE_SCHEMA_KEYS`` 白名单键，未知键（注入面）一律去除；
    - ``properties``（逐字段 schema）与 ``items`` 递归裁剪；其余白名单键
      （``type`` / ``required`` / ``enum`` / ``title`` / ``description``）按值保留；
    - 限深（防御纵深，与 ``sanitize_user_schema`` 同口径）：超深层裁为空对象，
      不递归失控；非对象输入返回空对象（兜底，正常路径调用方已过 sanitize）。

    入参应已经 ``sanitize_user_schema``（有界、无环）；本函数只做结构裁剪，
    产物用于 ``AnalysisSpec.custom_schema`` 落 ``task_payload``，provider 只见到裁剪后子集。
    """
    if not isinstance(schema, dict) or _depth > MAX_SCHEMA_DEPTH:
        return {}
    trimmed: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SAFE_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            trimmed[key] = {
                str(name): trim_to_safe_json_schema(sub, _depth=_depth + 1)
                for name, sub in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            trimmed[key] = trim_to_safe_json_schema(value, _depth=_depth + 1)
        else:
            trimmed[key] = value
    return trimmed


__all__ = [
    "DEFAULT_CUSTOM_SCHEMA_MAX_BYTES",
    "MAX_SCHEMA_DEPTH",
    "MAX_SCHEMA_FIELDS",
    "SchemaSanitizeError",
    "sanitize_user_schema",
    "trim_to_safe_json_schema",
]
