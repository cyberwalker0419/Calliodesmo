"""集中导入全部 ORM 模型，保证 Base.metadata 注册完整（create_all / 未来 Alembic 共用入口）。"""

from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import (
    Project,
    ProjectMember,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
    UserRole,
)
from calliodesmo.collab.models import Contribution

__all__ = [
    "AuditLog",
    "Contribution",
    "Project",
    "ProjectMember",
    "Role",
    "RolePermission",
    "Team",
    "TeamMember",
    "User",
    "UserRole",
]
