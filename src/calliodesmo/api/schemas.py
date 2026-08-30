"""API 请求/响应模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    clearance: str
    permissions: list[str]
    library_scopes: list[str]
    team_ids: list[uuid.UUID]
    project_ids: list[uuid.UUID]


class QueryRequest(BaseModel):
    question: str
    mode: str = "native_rag"
    top_k: int = Field(default=10, ge=1)


class QueryResponse(BaseModel):
    answer: str
    mode: str
    source_chunk_ids: list[str]
    context_chunks: list[dict[str, Any]]
    model: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6)
    clearance: str = "INTERNAL"


# ---- /admin 管理端 ----


class UserRoleOut(BaseModel):
    role: str
    scope: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    clearance: str
    is_active: bool
    roles: list[UserRoleOut]
    team_ids: list[uuid.UUID]
    project_ids: list[uuid.UUID]


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6)
    clearance: str = "INTERNAL"
    email: str | None = None


class UserUpdate(BaseModel):
    clearance: str | None = None
    is_active: bool | None = None
    email: str | None = None


class RoleAssign(BaseModel):
    role: str
    scope: str = "personal"


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    role_in_team: str


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    members: list[TeamMemberOut]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID
    role_in_team: str = "member"


class ProjectMemberOut(BaseModel):
    user_id: uuid.UUID
    role: str | None
    role_in_project: str


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    team_id: uuid.UUID
    members: list[ProjectMemberOut]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    team_id: uuid.UUID
    description: str = ""


class ProjectMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "analyst"
    role_in_project: str = "member"


# ---- /library 只读浏览 ----


class ProfileCardOut(BaseModel):
    entity_name: str
    entity_type: str | None
    aliases: list[str]
    role: str | None
    organization: str | None
    associates: list[str]
    timespan: str | None
    description: str
    narrative: str | None  # 概览叙述（不参与检索，仅供人读）
    evidence_chunk_ids: list[str]
    access_level: str
    library_scope: str


class CommunityOut(BaseModel):
    community_id: str
    level: int
    title: str
    summary: str
    member_entity_names: list[str]
    metadata: dict[str, Any]
    access_level: str
    library_scope: str


class EntityBrief(BaseModel):
    name: str
    type: str | None
    description: str


class RelationOut(BaseModel):
    source: str
    target: str
    type: str | None
    description: str


class EntityOut(BaseModel):
    name: str
    type: str | None
    description: str
    source_chunk_ids: list[str]
    template_conforming: bool
    access_level: str
    library_scope: str
    neighbors: list[EntityBrief]
    relations: list[RelationOut]


class SubgraphNode(BaseModel):
    name: str
    type: str | None
    description: str
    access_level: str


class SubgraphEdge(BaseModel):
    source: str
    target: str
    type: str | None
    description: str


class SubgraphResponse(BaseModel):
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]
    expanded_seeds: list[str]
    truncated: bool  # 达节点上限被截断


# ---- /admin/document-communities 手动管理（Task 7）----


class CommunityRename(BaseModel):
    title: str = Field(min_length=1)


class CommunityRetag(BaseModel):
    tags: list[str]


class CommunitySetAccess(BaseModel):
    access_level: str


class CommunityAddDoc(BaseModel):
    doc_id: str
    note: str = ""


class CommunityPatchRequest(BaseModel):
    title: str | None = None
    access_level: str | None = None


class CommunityRemoveDoc(BaseModel):
    doc_id: str


class CommunityVersionOut(BaseModel):
    id: uuid.UUID
    community_id: str
    version: int
    created_at: datetime
    created_by: uuid.UUID | None = None


class CommunityMergeRequest(BaseModel):
    target_id: str
    source_ids: list[str]


class CommunitySplitRequest(BaseModel):
    doc_groups: list[list[str]]


# ---- /collab 协作推送 ----


class ContributionCreate(BaseModel):
    source_scope: str
    target_scope: str
    target_project_id: uuid.UUID | None = None
    target_team_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    doc_ids: list[str] = Field(default_factory=list)
    description: str = ""


class ContributionOut(BaseModel):
    id: uuid.UUID
    source_user_id: uuid.UUID
    source_scope: str
    target_scope: str
    target_project_id: uuid.UUID | None
    target_team_id: uuid.UUID | None
    title: str
    description: str
    status: str
    doc_ids: list[str]
    assignee_id: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    merged_at: datetime | None
    created_at: datetime
    version: int


class DiffOut(BaseModel):
    """差异清单摘要 + 明细（供审核人审阅）。

    计数字段为聚合摘要；``*_names``/``*_summaries``/``*_ids`` 为明细清单，
    直接取自 ``contribution.manifest``（push 时已落库，零额外查询）。
    冲突仅给计数（``conflicts``）--同名不同义实体明细留 v2（见 push.compute_overlap）。
    """

    new_entities: int
    new_relations: int
    chunks: int
    communities: int
    conflicts: int
    entity_names: list[str]
    relation_summaries: list[list[str]]  # [source, target, type]
    chunk_ids: list[str]
    community_ids: list[str]
    alignment_pending: list[dict[str, Any]] = []


class RejectRequest(BaseModel):
    reason: str = ""


# ---- /collab 对齐复核（P4.5 Task 6）----


class AlignmentPending(BaseModel):
    """待审对齐候选对（diff 返回，取自 manifest alignment_pending）。"""

    pair_id: str
    source_name: str
    target_name: str
    score: float
    type: str | None = None
    source_type: str | None = None
    target_type: str | None = None
    source_description: str = ""
    target_description: str = ""
    status: str = "pending"


class AlignmentReviewRequest(BaseModel):
    pair_id: str = Field(min_length=1)


class AlignmentReviewOut(BaseModel):
    pair_id: str
    status: str
    source_name: str | None = None
    target_name: str | None = None


# ---- /collab 抽取模板 review-gated ----


class TemplateTypeOut(BaseModel):
    type: str
    count: int
    status: str


class TemplateTypeApproveRequest(BaseModel):
    team: str
    type: str = Field(min_length=1)


class TemplateTypeApproveOut(BaseModel):
    team: str
    type: str
    status: str


# ---- /ingest 文档上传 ----


class IngestStatsOut(BaseModel):
    documents: int
    chunks: int
    entities: int
    relations: int
    communities: int
    profile_cards: int


class IngestAcceptedOut(BaseModel):
    """POST /ingest 202 响应：异步 job 已受理，轮询 /jobs/{job_id} 取进度。"""

    job_id: uuid.UUID
    status: str
    filename: str


class JobOut(BaseModel):
    """GET /jobs/{id}：异步任务状态 + 进度 + 结果统计 / 错误。

    P6 Task 11 泛化兼容扩展：``task_type``（ingest / analyze，默认 ingest）与
    ``report_id``（analyze 任务指向报告行，ingest 恒 None）均带默认值，
    旧响应消费方（前端 useIngest.ts）不破坏。
    """

    id: uuid.UUID
    filename: str
    status: str
    progress: int
    progress_stage: str | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    task_type: str = "ingest"
    report_id: uuid.UUID | None = None


# ---- /analysis 分析任务（P6 Task 14）----


class AnalysisCustomRequest(BaseModel):
    """自定义分析请求体（custom 类型专用）：``instruction`` 必填，``schema`` 可选。

    ``instruction`` 只进 user 消息（与 system 隔离，收敛注入面）；``schema`` 经
    ``analysis/sanitize.py`` 清洗（拒根非对象 / $ref / 递归 / 超深 / 超大 / 超字节）
    后，于请求边界裁剪为 JSON Schema 安全子集再落 ``task_payload``（Task 22 交付）。
    """

    instruction: str = Field(
        default="", description="自定义分析指令（custom 类型必填，非空白；缺失边界 400）"
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="可选输出 schema（JSON Schema 子集，Task 22 sanitize）",
    )


class AnalysisJobRequest(BaseModel):
    """POST /analysis/tasks 请求体（与前端 AnalysisJobRequest 逐字段对齐）。

    - ``task_type``：分析类型字符串；未注册 / 未交付类型在请求边界 400
      （非法值经枚举转换拦截，合法但未注册经 ``get_spec`` KeyError 拦截）；
    - ``doc_ids``：成员筛选集合（默认空 = 全可见范围）；含不可见项 -> 400，
      仅作成员筛选不豁免可见性校验（红线一，见 ``analysis/materials.py``）；
    - ``question``：qa 必填（非空白）；``custom``：custom 必填（见上）；
    - ``top_k``：qa 检索候选数（同 QueryRequest 口径 ge=1）。
    """

    task_type: str = Field(description="分析类型（九类之一；未注册类型 400）")
    doc_ids: list[str] = Field(default_factory=list, description="文档成员筛选（空 = 全可见范围）")
    question: str | None = Field(default=None, description="qa 类问题（qa 必填）")
    custom: AnalysisCustomRequest | None = Field(
        default=None, description="custom 类指令与可选 schema"
    )
    top_k: int = Field(default=10, ge=1, description="qa 检索候选数")


class AnalysisAcceptedOut(BaseModel):
    """POST /analysis/tasks 202 响应：异步 analyze job 已受理，轮询 /jobs/{job_id}。

    ``task_type`` 回显提交的分析类型（如 summary / qa），与请求字段同义；
    Job 行内部的 ``task_type`` 恒为 "analyze"（Job 泛化口径，见 db/models_job.py）。
    """

    job_id: uuid.UUID
    status: str
    task_type: str


class AnalysisReportListItem(BaseModel):
    """报告历史列表项（与前端 ReportListItem 逐字段对齐）。"""

    id: uuid.UUID
    task_type: str
    status: str
    subject_label: str
    access_level: str  # ClearanceLevel.name（如 INTERNAL / SECRET）
    library_scope: str
    model: str
    created_at: datetime
    source_chunk_count: int


class AnalysisReportListOut(BaseModel):
    """GET /analysis/reports：可见报告历史（三维过滤 + 分页）。

    ``total`` 为过滤后全部可见行数（供前端分页器），``items`` 为当前页切片。
    """

    items: list[AnalysisReportListItem]
    total: int


class AnalysisDocumentOut(BaseModel):
    """GET /analysis/documents：可见文档聚合项（Task 19 MaterialPicker 数据源）。

    按 ``doc_id`` 聚合 ``list_chunks`` + ``visible_to`` 结果：``label`` 取 metadata
    标题或回退 doc_id（与 ``analysis/materials._source_label`` 约定一致）；
    ``access_level`` 取该文档全部可见块的密级最大值（ClearanceLevel.name）。
    """

    doc_id: str
    label: str
    access_level: str
    chunk_count: int


# ---- P7 Agent 模式（T14）：会话 / 执行 / 消息 ----


class AgentSessionCreate(BaseModel):
    """POST /agent/sessions 请求体：mode 未注册 400（v1 仅 react）。"""

    mode: str = "react"
    label: str = ""


class AgentSessionOut(BaseModel):
    """会话对外形态（前端 types.ts 对齐）。"""

    id: uuid.UUID
    mode: str
    label: str
    access_level: str
    library_scope: str
    created_at: datetime


class AgentSessionListOut(BaseModel):
    items: list[AgentSessionOut]
    total: int


class AgentRunRequest(BaseModel):
    """POST /agent/sessions/{id}/runs 请求体。"""

    question: str = Field(min_length=1, max_length=4000)


class AgentRunAccepted(BaseModel):
    """202 受理：job 范式最小指针（轮询 /jobs/{job_id}）。"""

    job_id: uuid.UUID
    status: str


class AgentMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    run_id: uuid.UUID | None
    created_at: datetime


class AgentRunOut(BaseModel):
    """GET /agent/sessions/{id}/runs：执行列表（轨迹供前端折叠展示与评估消费）。"""

    id: uuid.UUID
    session_id: uuid.UUID
    status: str
    steps: int
    usage: dict
    tool_trace: list
    error: str | None
    created_at: datetime
