"""内容层 ORM（P4.5 Task 2）：三层知识图谱数据落 PG。

- 情景层：``documents`` + ``chunks``（pgvector Vector 嵌入）
- 语义层：``entities`` / ``relations``（PG 镜像供 visible_to 聚合；权威在 Neo4j）
- 摘要层：``communities``（摘要向量）
- 档案卡：``profile_cards``

全部内容表带三维权限字段（access_level / library_scope / owner_id / project_id / team_id），
对齐 :class:`~calliodesmo.interfaces.vector_store.ChunkRecord` 等 dataclass 的 access 字段，
供 ``visible_to`` 聚合过滤。需 ``pgvector`` 扩展（``uv sync --extra persistence``）；
``models.py`` 经 try/except 注册，未装 pgvector 时（CI）跳过——CI 以 ``-m "not db"`` 不触这些表。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base

# 向量维度在建表时由配置锁定（embedding_dimension）。运行时嵌入须与此一致。
_EMBEDDING_DIM = get_settings().embedding_dimension


class PublicVector(Vector):
    """``vector`` 类型显式限定到 ``public`` schema。

    测试隔离用专用 schema（``search_path=test``，不含 public 避免同名表遮蔽），但 pgvector
    扩展装在 ``public``、且 ``calliodesmo`` 角色无权迁移扩展到独立 schema。显式 ``public.vector``
    使列 DDL 与 HNSW 索引在任何 search_path 下都能解析类型，兼顾"无遮蔽"与"类型可解析"。
    """

    def get_col_spec(self, **kw):  # type: ignore[override]
        dim = getattr(self, "dim", None)
        return f"public.vector({dim})" if dim else "public.vector"


def _embedding_type() -> PublicVector:
    """构造 pgvector Vector 列类型（维度对齐 settings.embedding_dimension）。"""
    return PublicVector(_EMBEDDING_DIM)


class Document(Base):
    """文档元数据：标题 / 来源 / 内容指纹（Task 3 增量用）/ 大小 + 库归属。"""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    source_path: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChunkRecordORM(Base):
    """情景层 chunk：文本 + pgvector 嵌入 + access 字段（对齐 ChunkRecord dataclass）。"""

    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(_embedding_type(), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "public.vector_cosine_ops"},
        ),
    )


class EntityRecordORM(Base):
    """语义层实体（PG 镜像供 visible_to 聚合 fallback；权威在 Neo4j）。

    复合唯一：(name, library_scope, owner_id)——同库内实体名唯一。
    """

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256), index=True)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    template_conforming: Mapped[bool] = mapped_column(default=False)
    source_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    merge_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        Index("ix_entities_scope_unique", "name", "library_scope", "owner_id", unique=True),
    )


class RelationRecordORM(Base):
    """语义层关系（PG 镜像）：source->target 边。

    复合唯一：(source, target, type, library_scope, owner_id)。
    """

    __tablename__ = "relations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(256), index=True)
    target: Mapped[str] = mapped_column(String(256), index=True)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        Index(
            "ix_relations_scope_unique",
            "source",
            "target",
            "type",
            "library_scope",
            "owner_id",
            unique=True,
        ),
    )


class CommunityRecordORM(Base):
    """摘要层社区：标题 / 摘要 + 摘要向量 + 成员 + access 字段。"""

    __tablename__ = "communities"

    community_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_embedding: Mapped[list[float] | None] = mapped_column(_embedding_type(), nullable=True)
    member_doc_ids: Mapped[list] = mapped_column(JSON, default=list)
    member_entity_names: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_communities_summary_embedding_hnsw",
            "summary_embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"summary_embedding": "public.vector_cosine_ops"},
        ),
    )


class ProfileCardORM(Base):
    """档案卡：实体结构化字段 + 叙事。复合唯一 (entity_name, library_scope, owner_id)。"""

    __tablename__ = "profile_cards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_name: Mapped[str] = mapped_column(String(256), index=True)
    structured_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[str] = mapped_column(Text, default="")
    locked: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    library_scope: Mapped[LibraryScope] = mapped_column(
        Enum(LibraryScope, native_enum=False), default=LibraryScope.PERSONAL, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    access_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel, native_enum=False), default=ClearanceLevel.INTERNAL
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index(
            "ix_profile_cards_scope_unique",
            "entity_name",
            "library_scope",
            "owner_id",
            unique=True,
        ),
    )


__all__ = [
    "ChunkRecordORM",
    "CommunityRecordORM",
    "Document",
    "EntityRecordORM",
    "ProfileCardORM",
    "RelationRecordORM",
]
