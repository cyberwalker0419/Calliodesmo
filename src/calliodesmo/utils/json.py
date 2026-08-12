"""JSON 边界工具：递归把含 UUID / 枚举 / datetime 的对象转为 JSON 可序列化结构。

真后端 stores 的 ``metadata`` 等 JSON/JSONB 列在写入前须经 ``json_safe`` 清洗，
避免上游（loader / cognify / 协作改写）注入的 :class:`uuid.UUID` /
:class:`~calliodesmo.auth.models.ClearanceLevel` /
:class:`~calliodesmo.auth.models.LibraryScope` / :class:`datetime.datetime` 触发
``TypeError: Object of type UUID is not JSON serializable``。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any


def json_safe(obj: Any) -> Any:
    """递归转 JSON 可序列化（UUID/datetime -> str，Enum -> .value，dict/list 递归）。

    纯函数、无外部依赖，可供所有 store 边界复用。
    """
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj
