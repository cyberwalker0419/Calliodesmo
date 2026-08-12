"""json_safe 边界工具单测：锁定真后端 store 的 metadata JSON 序列化修复。

回归背景（全链路仿真发现）：``/ingest`` 端点经 ``_DemoAccessLoader`` 注入的
``owner_id``(UUID) / ``access_level``(ClearanceLevel) / ``library_scope``(LibraryScope)
进入 chunk ``metadata``，PgVectorStore 写 JSONB 列时 ``TypeError: Object of type
UUID is not JSON serializable``。本测试锁定 shared :func:`json_safe` 的清洗契约。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.utils.json import json_safe


def test_json_safe_uuid_to_str() -> None:
    u = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert json_safe(u) == "00000000-0000-0000-0000-000000000001"


def test_json_safe_enum_to_value() -> None:
    # ClearanceLevel 是 IntEnum（value 为 0..3），LibraryScope 是 StrEnum
    assert json_safe(ClearanceLevel.SECRET) == 3
    assert json_safe(LibraryScope.PERSONAL) == "personal"


def test_json_safe_datetime_to_iso() -> None:
    dt = datetime(2026, 7, 31, 12, 0, 0)
    assert json_safe(dt) == "2026-07-31T12:00:00"


def test_json_safe_nested_dict_list_roundtrip_serializable() -> None:
    """模拟 _DemoAccessLoader 注入的 metadata：含 UUID / 枚举，嵌套 dict+list。"""
    payload = {
        "owner_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "team_id": None,
        "project_id": None,
        "access_level": ClearanceLevel.INTERNAL,
        "library_scope": LibraryScope.PERSONAL,
        "tags": ["a", ClearanceLevel.SECRET, {"nested": uuid.UUID(int=2)}],
    }
    safe = json_safe(payload)
    # 清洗后必须可被标准 json 序列化（即 PgVectorStore/Neo4j 写入路径不再报错）
    serialized = json.dumps(safe)
    again = json.loads(serialized)
    assert again["owner_id"] == "11111111-1111-1111-1111-111111111111"
    assert again["access_level"] == 1  # IntEnum -> int
    assert again["library_scope"] == "personal"
    assert again["tags"][1] == 3  # ClearanceLevel.SECRET -> 3
    assert again["tags"][2]["nested"] == str(uuid.UUID(int=2))


def test_json_safe_passes_through_plain_scalars() -> None:
    assert json_safe("s") == "s"
    assert json_safe(1) == 1
    assert json_safe(1.5) == 1.5
    assert json_safe(None) is None
    assert json_safe(True) is True
