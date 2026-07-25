"""AccessContext：贯穿请求全生命周期的统一权限上下文，检索器/合成器/Agent 统一接收做过滤。"""

import uuid
from dataclasses import dataclass, field

from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission


@dataclass(frozen=True)
class AccessContext:
    user_id: uuid.UUID
    username: str
    clearance: ClearanceLevel
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    library_scopes: frozenset[LibraryScope] = field(default_factory=frozenset)
    group_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def can_access(self, access_level: ClearanceLevel) -> bool:
        """clearance >= access_level 才可见。"""
        return self.clearance >= access_level

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
