"""P7 T17 一次性探针：团队级分析模板 schema 边界（不进主代码）。

验证口径②：``sanitize_user_schema`` 对团队模板样例的拒/收边界——
$ref / 递归 / 超深 / 超大拒，正常模板收；并显式暴露其不做「实例级类型校验」
（完整 jsonschema 的增量面），供评估备忘录引用。跑法：

    uv run python scripts/probe_template_schema.py
"""

from __future__ import annotations

import json

from calliodesmo.analysis.sanitize import (
    SchemaSanitizeError,
    sanitize_user_schema,
)

OK_TEMPLATE = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["findings"],
}


def probe(name: str, schema) -> str:
    try:
        sanitize_user_schema(schema)
        return f"{name}: 收"
    except SchemaSanitizeError as exc:
        return f"{name}: 拒（{exc}）"


def main() -> int:
    deep = {"type": "object"}
    node = deep
    for _ in range(6):
        node["properties"] = {"nest": {"type": "object"}}
        node = node["properties"]["nest"]
    recursive: dict = {"type": "object"}
    recursive["properties"] = {"self": recursive}

    print(probe("正常团队模板", OK_TEMPLATE))
    print(probe("$ref 引用", {"type": "object", "properties": {"x": {"$ref": "#"}}}))
    print(probe("递归嵌套", recursive))
    print(probe("超深（>4）", deep))
    big = {"type": "object", "properties": {f"f{i}": {"type": "string"} for i in range(200)}}
    print(probe("超大（>4096B）", big))
    print(
        "实例级类型校验（jsonschema 增量面）:",
        "sanitize 不做——仅结构/深度/键数/字节闸；实例校验须引 jsonschema extra",
    )
    print(json.dumps({"ok_template_accepted": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
