"""API 请求/响应模型。"""

import uuid

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    clearance: str
    permissions: list[str]
    library_scopes: list[str]
    group_ids: list[uuid.UUID]
