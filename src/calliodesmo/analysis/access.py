"""报告密级继承：``compute_report_access_level = max(材料各级, INTERNAL)``（纯函数）。

P6 决策 4：报告 ``access_level = max(材料各级, INTERNAL)``，``library_scope = personal``，
``owner = 提交者``。``ClearanceLevel`` 为有序 ``IntEnum``，``max()`` 直接可用；
INTERNAL 下限避免报告默认公开，堵住低密账户借分析「洗」高密内容的通道
（材料获取侧的全程 ``visible_to`` 红线见 ``analysis/materials.py``）。

Task 12 报告落库时消费本函数；离线单测锁定边界（全 public 材料 -> INTERNAL；
含 secret 材料 -> SECRET；空材料 -> INTERNAL）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from calliodesmo.auth.models import ClearanceLevel


def compute_report_access_level(materials: Iterable[Any]) -> ClearanceLevel:
    """报告密级 = ``max(材料各级, INTERNAL)``（纯函数，无夹具可离线单测）。

    参数:
        materials: 材料序列（``AnalysisMaterial`` 鸭子类型，取 ``access_level`` 属性）；
            亦可直接接收 ``ClearanceLevel`` 序列。

    返回:
        报告应继承的 ``ClearanceLevel``：

        - 全 PUBLIC 材料 -> INTERNAL（下限，报告不默认公开）；
        - 含 SECRET 材料 -> SECRET（密级不洗白）；
        - 空材料 -> INTERNAL（下限兜底；空材料实际由 worker 拦为失败，见 Task 13）。

    异常:
        TypeError: 条目既非 ``ClearanceLevel`` 也不带 ``access_level`` 属性时。
    """
    level = ClearanceLevel.INTERNAL
    for item in materials:
        item_level = getattr(item, "access_level", item)
        if not isinstance(item_level, ClearanceLevel):
            raise TypeError(f"材料条目须带 access_level 属性或为 ClearanceLevel，实际为: {item!r}")
        level = max(level, item_level)
    return level
