"""可见性谓词：按三维正交权限（clearance + scope + owner/team/project）过滤记录。

所有 store 记录（ChunkRecord/EntityRecord/RelationRecord/CommunityRecord）均携带
access_level/library_scope/owner_id/project_id/team_id 五字段，本谓词据此与
AccessContext 比对，实现"越权记录不可见"。
"""

from __future__ import annotations

from typing import Protocol

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import LibraryScope


class AccessOwned(Protocol):
    """携带 access 字段的记录（duck typing，供 visible_to 复用）。"""

    access_level: int  # ClearanceLevel 为 IntEnum
    library_scope: LibraryScope
    owner_id: object | None
    project_id: object | None
    team_id: object | None


def visible_to(record: AccessOwned, ctx: AccessContext) -> bool:
    """record 对 ctx 是否可见：clearance >= access_level 且 scope 命中。"""
    if ctx.clearance < record.access_level:
        return False
    match record.library_scope:
        case LibraryScope.PERSONAL:
            return record.owner_id == ctx.user_id
        case LibraryScope.PROJECT:
            return record.project_id in ctx.project_ids
        case LibraryScope.TEAM:
            return record.team_id in ctx.team_ids
    return False
