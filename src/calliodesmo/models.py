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
from calliodesmo.collab.community_version import CommunityVersion
from calliodesmo.collab.models import Contribution
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.db.models_job import Job, JobStatus

# 内容层 ORM（P4.5 Task 2）需 pgvector 扩展（uv sync --extra persistence）。
# 未装时（CI / 未 sync extra）跳过注册——CI 以 -m "not db" 不触这些表，非 DB 测试不依赖。
try:
    from calliodesmo.db.models_content import (
        ChunkRecordORM,
        CommunityRecordORM,
        Document,
        EntityRecordORM,
        ProfileCardORM,
        RelationRecordORM,
    )
except ImportError:  # pragma: no cover - 仅缺 pgvector 时触发
    ChunkRecordORM = CommunityRecordORM = Document = None  # type: ignore[assignment,misc]
    EntityRecordORM = ProfileCardORM = RelationRecordORM = None  # type: ignore[assignment,misc]

__all__ = [
    "AnalysisReportORM",
    "AuditLog",
    "ChunkRecordORM",
    "CommunityRecordORM",
    "CommunityVersion",
    "Contribution",
    "Document",
    "EntityRecordORM",
    "Job",
    "JobStatus",
    "ProfileCardORM",
    "Project",
    "ProjectMember",
    "RelationRecordORM",
    "Role",
    "RolePermission",
    "Team",
    "TeamMember",
    "User",
    "UserRole",
]
