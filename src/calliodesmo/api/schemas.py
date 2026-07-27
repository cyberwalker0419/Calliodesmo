"""API 请求/响应模型。"""

import uuid
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
