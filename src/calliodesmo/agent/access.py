"""会话复检（密级不洗白）+ 落库前密级断言钩子（P7 T12，最大翻车面专项）。

读路径：当前 ``clearance >= clearance_at_create``（密级不洗白）+ 当前
AccessContext ``visible_to`` 复检（scope 移除后不可见）；不通过即 404 + 审计
（API 层 T14 消费）。跨用户会话 404 不泄漏存在性。

写路径：落库前密级断言——消息 / 证据密级不得高于会话密级（工具层 visible_to
为第一层防御，本钩子为写违例 fail-fast 第二层）。
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.stores.visibility import visible_to


def verify_session_access(session_row, *, access: AccessContext) -> bool:
    """读会话复检：密级不洗白 + 三维 visible_to。

    - 当前 clearance < 建时快照 -> False（降级后读旧会话 = 404）；
    - scope 移除 / 跨用户 -> visible_to False；
    - 全过 -> True。
    """
    if access.clearance < session_row.clearance_at_create:
        return False
    return visible_to(session_row, access)


class ClearanceViolationError(PermissionError):
    """落库前密级断言违例（证据密级高于会话密级）。"""


def assert_evidence_within_session(
    evidence_level: ClearanceLevel, *, session_level: ClearanceLevel
) -> None:
    """落库前密级断言钩子：证据密级不得高于会话密级，违例 fail-fast。"""
    if evidence_level > session_level:
        raise ClearanceViolationError(
            f"证据密级 {evidence_level.name} 高于会话密级 {session_level.name}，禁止落库"
        )
