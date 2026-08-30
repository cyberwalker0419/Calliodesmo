"""P6 Task 22 测试：自定义分析用户 schema 清洗与安全子集裁剪（纯函数，无夹具，CI 可覆盖）。

覆盖（对齐计划 Task 22 Step 1 与「范围外 · 注入面」）：

- ``sanitize_user_schema`` 五类拒绝路径各一条 + 合法 schema 通过：
  拒 ``$ref`` / 递归嵌套（循环引用）/ 嵌套深度 >4 / 字段（键）数 >30 /
  序列化超 ``analysis_custom_schema_max_bytes``；
- 默认字节上限与 ``Settings.analysis_custom_schema_max_bytes`` 对账（防漂移）；
- ``trim_to_safe_json_schema``：provider 发送前裁剪为 JSON Schema 安全子集
  （去未知键 / 限结构：仅保留白名单键，递归处理 properties / items）。

sanitize / trim 均为纯函数离线可测；违规抛可读 ``SchemaSanitizeError``（API 层转 400）。
完整 JSON Schema 校验（引 ``jsonschema``）随团队级模板注册表一并评估（P7，2026-W47），
本阶段只做安全闸门 + 安全子集裁剪，留痕见计划。
"""

import pytest

from calliodesmo.analysis.sanitize import (
    DEFAULT_CUSTOM_SCHEMA_MAX_BYTES,
    MAX_SCHEMA_DEPTH,
    MAX_SCHEMA_FIELDS,
    SchemaSanitizeError,
    sanitize_user_schema,
    trim_to_safe_json_schema,
)
from calliodesmo.config import Settings


def _legal_schema() -> dict:
    """合法自定义输出 schema（JSON Schema 子集，深度 ≤4、键数 ≤30、无 $ref / 循环）。"""
    return {
        "type": "object",
        "properties": {
            "风险等级": {"type": "string", "description": "低 / 中 / 高"},
            "关键要点": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["风险等级"],
    }


class TestSanitizeUserSchemaReject:
    """五类拒绝路径各一条（违规抛可读 SchemaSanitizeError）。"""

    def test_rejects_dollar_ref(self):
        """拒 $ref：引用外部 / 递归定义是注入与解析歧义面。"""
        schema = {
            "type": "object",
            "properties": {"x": {"$ref": "#/definitions/y"}},
            "definitions": {"y": {"type": "string"}},
        }
        with pytest.raises(SchemaSanitizeError, match=r"\$ref"):
            sanitize_user_schema(schema)

    def test_rejects_nested_dollar_ref(self):
        """$ref 出现在任意深度均拒（递归遍历）。"""
        schema = {"type": "object", "properties": {"a": {"items": {"$ref": "#/x"}}}}
        with pytest.raises(SchemaSanitizeError, match=r"\$ref"):
            sanitize_user_schema(schema)

    def test_rejects_recursive_cycle(self):
        """拒递归嵌套（循环引用）：字典自引用使遍历 / 序列化无终止。"""
        schema: dict = {"type": "object", "properties": {}}
        schema["properties"]["self"] = schema  # 构造循环
        with pytest.raises(SchemaSanitizeError, match=r"循环|递归"):
            sanitize_user_schema(schema)

    def test_rejects_list_cycle(self):
        """列表回指祖先同样判为循环。"""
        schema: dict = {"type": "object"}
        loop: list = []
        schema["items"] = loop
        loop.append(schema)
        with pytest.raises(SchemaSanitizeError, match=r"循环|递归"):
            sanitize_user_schema(schema)

    def test_rejects_depth_over_four(self):
        """拒嵌套深度 >4（根为第 1 层，5 层即超）。"""
        schema = {"a": {"b": {"c": {"d": {"e": "x"}}}}}
        with pytest.raises(SchemaSanitizeError, match="深度"):
            sanitize_user_schema(schema)

    def test_rejects_field_count_over_thirty(self):
        """拒字段（键）总数 >30（结构化 DoS 面，白名单内真实字段亦限）。"""
        schema = {"properties": {f"f{i}": {"type": "string"} for i in range(31)}}
        with pytest.raises(SchemaSanitizeError, match=r"字段|键"):
            sanitize_user_schema(schema)

    def test_rejects_serialized_bytes_over_limit(self):
        """拒序列化超字节上限（默认 4096）。"""
        schema = {"type": "object", "properties": {"big": {"description": "x" * 5000}}}
        with pytest.raises(SchemaSanitizeError, match="字节"):
            sanitize_user_schema(schema)

    def test_rejects_bytes_with_explicit_small_limit(self):
        """显式传入更小上限：超限即拒（API 侧经 settings 传 analysis_custom_schema_max_bytes）。"""
        schema = {"description": "x" * 50}
        with pytest.raises(SchemaSanitizeError, match="字节"):
            sanitize_user_schema(schema, max_bytes=16)


class TestSanitizeUserSchemaAccept:
    """合法 schema 通过（返回内容可用）。"""

    def test_accepts_legal_schema(self):
        result = sanitize_user_schema(_legal_schema())
        assert result == _legal_schema()

    def test_accepts_empty_object(self):
        assert sanitize_user_schema({}) == {}

    def test_accepts_schema_at_depth_boundary(self):
        """深度恰为 4（含等号）合法。"""
        schema = {"a": {"b": {"c": {"d": "x"}}}}  # 4 层
        assert sanitize_user_schema(schema) == schema

    def test_accepts_field_count_at_boundary(self):
        """键总数恰为 30（含等号）合法。"""
        schema = {f"k{i}": "v" for i in range(30)}
        assert sanitize_user_schema(schema) == schema

    def test_non_dict_root_rejected(self):
        """根非对象（列表 / 标量）拒：输出 schema 必须是 JSON 对象。"""
        with pytest.raises(SchemaSanitizeError, match="对象"):
            sanitize_user_schema(["not", "a", "dict"])  # type: ignore[arg-type]


class TestSanitizeDefaults:
    """默认常量与 Settings 对账（防漂移，仿 prompts 预算口径）。"""

    def test_default_max_bytes_mirrors_settings(self):
        assert DEFAULT_CUSTOM_SCHEMA_MAX_BYTES == Settings().analysis_custom_schema_max_bytes

    def test_limits_constants(self):
        assert MAX_SCHEMA_DEPTH == 4
        assert MAX_SCHEMA_FIELDS == 30


class TestTrimToSafeJsonSchema:
    """provider 发送前裁剪为 JSON Schema 安全子集（去未知键 / 限结构）。"""

    def test_drops_unknown_top_level_keys(self):
        schema = {
            "type": "object",
            "properties": {"风险": {"type": "string"}},
            "ignore_previous_instructions": "越权载荷",  # 未知键（注入面）被裁掉
            "$ref": "#/x",  # $ref 同样不在安全子集
        }
        trimmed = trim_to_safe_json_schema(schema)
        assert set(trimmed) == {"type", "properties"}
        assert trimmed["properties"] == {"风险": {"type": "string"}}

    def test_keeps_whitelist_and_recurses_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "风险": {"type": "string", "description": "等级", "unknown_key": 1},
            },
            "required": ["风险"],
        }
        trimmed = trim_to_safe_json_schema(schema)
        assert trimmed["properties"]["风险"] == {"type": "string", "description": "等级"}
        assert trimmed["required"] == ["风险"]

    def test_recurses_items(self):
        schema = {"type": "array", "items": {"type": "object", "evil": True}}
        trimmed = trim_to_safe_json_schema(schema)
        assert trimmed == {"type": "array", "items": {"type": "object"}}

    def test_non_dict_returns_empty(self):
        assert trim_to_safe_json_schema(["x"]) == {}  # type: ignore[arg-type]

    def test_empty_dict_returns_empty(self):
        assert trim_to_safe_json_schema({}) == {}

    def test_depth_limited(self):
        """裁剪自身限深（防御纵深）：超深层被截断，不递归失控（经白名单 properties 深嵌）。"""
        schema = {
            "properties": {
                "a": {
                    "properties": {
                        "b": {"properties": {"c": {"properties": {"d": {"type": "string"}}}}}
                    }
                }
            }
        }
        trimmed = trim_to_safe_json_schema(schema)
        assert isinstance(trimmed, dict)
        assert "properties" in trimmed


class TestBuildCustomSpecSecurityGate:
    """build_custom_spec：校验指令 + sanitize schema 的安全闸门（详见 specs 注册测试）。"""

    def test_blank_instruction_rejected(self):
        from calliodesmo.analysis.specs import build_custom_spec

        with pytest.raises(ValueError, match="指令"):
            build_custom_spec("   ")

    def test_bad_schema_raises_sanitize_error(self):
        from calliodesmo.analysis.specs import build_custom_spec

        with pytest.raises(SchemaSanitizeError):
            build_custom_spec("提取风险点", {"$ref": "#/x"})

    def test_returns_registered_custom_spec(self):
        from calliodesmo.analysis.schemas import AnalysisType, CustomReport
        from calliodesmo.analysis.specs import build_custom_spec

        spec = build_custom_spec("提取风险点", _legal_schema())
        assert spec.type is AnalysisType.CUSTOM
        assert spec.output_cls is CustomReport
        assert spec.template_name == "custom.txt"
        assert spec.stub_marker == "[ANALYSIS:custom]"
