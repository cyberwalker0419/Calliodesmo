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


class RejectRequest(BaseModel):
    reason: str = ""


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
