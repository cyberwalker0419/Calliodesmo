"""PgVectorStore：情景层向量库真后端（pgvector + HNSW cosine），按 AccessContext 过滤。

P4.5 Task 2 Step 2。对齐 :class:`~calliodesmo.interfaces.vector_store.VectorStore` 契约：
``upsert_chunks``（ON CONFLICT 幂等）/ ``search``（``<=>`` 余弦距离 + visible_to SQL 过滤）/
``get_chunks_by_ids`` / ``list_chunks``。经 ``async_sessionmaker`` 自管会话。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_content import ChunkRecordORM, Document
from calliodesmo.interfaces.vector_store import ChunkRecord, VectorHit, VectorStore


def _chunk_to_doc_values(c: ChunkRecord) -> dict[str, Any]:
    """从 chunk 提取文档级 access 字段（同 doc 的 chunk 共享）。"""
    return {
        "doc_id": c.doc_id,
        "owner_id": c.owner_id,
        "library_scope": c.library_scope,
        "project_id": c.project_id,
        "team_id": c.team_id,
        "access_level": c.access_level,
    }


def _chunk_to_row(c: ChunkRecord) -> dict[str, Any]:
    """chunk -> 列值 dict（不含 metadata 列，因 ``metadata`` 与 SQLAlchemy 保留字冲突，
    另经列对象传）。"""
    return {
        "chunk_id": c.chunk_id,
        "doc_id": c.doc_id,
        "content": c.content,
        "summary": None,
        "embedding": c.vector,
        "owner_id": c.owner_id,
        "library_scope": c.library_scope,
        "project_id": c.project_id,
        "team_id": c.team_id,
        "access_level": c.access_level,
    }


def _row_to_chunk(row: ChunkRecordORM) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=row.chunk_id,
        doc_id=row.doc_id,
        content=row.content,
        vector=list(row.embedding) if row.embedding is not None else [],
        metadata=dict(row.metadata_) if row.metadata_ is not None else {},
        access_level=row.access_level,
        library_scope=row.library_scope,
        owner_id=row.owner_id,
        project_id=row.project_id,
        team_id=row.team_id,
    )


def _visible_filter(model, access: AccessContext):
    """复刻 visible_to 为 SQL 谓词：access_level <= clearance 且 scope 命中。"""
    allowed_levels = [lvl for lvl in ClearanceLevel if lvl.value <= access.clearance.value]
    return and_(
        model.access_level.in_(allowed_levels),
        or_(
            and_(
                model.library_scope == LibraryScope.PERSONAL,
                model.owner_id == access.user_id,
            ),
            and_(
                model.library_scope == LibraryScope.PROJECT,
                model.project_id.in_(access.project_ids),
            ),
            and_(
                model.library_scope == LibraryScope.TEAM,
                model.team_id.in_(access.team_ids),
            ),
        ),
    )


class PgVectorStore(VectorStore):
    """pgvector 向量库。经 session factory 自管会话；embedding 经 HNSW cosine 检索。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        async with self._session_factory() as session:
            # 1) upsert 文档行（满足 chunks.doc_id -> documents.doc_id 外键；ON CONFLICT 幂等）
            seen_docs: dict[str, dict[str, Any]] = {}
            for c in chunks:
                if c.doc_id not in seen_docs:
                    seen_docs[c.doc_id] = _chunk_to_doc_values(c)
            for doc_values in seen_docs.values():
                await session.execute(
                    pg_insert(Document)
                    .values(**doc_values)
                    .on_conflict_do_nothing(index_elements=["doc_id"])
                )
            # 2) upsert chunks（同 chunk_id 覆盖；metadata 经列对象传，避保留字冲突）
            for c in chunks:
                row = _chunk_to_row(c)
                values = {**row, ChunkRecordORM.metadata_: c.metadata}
                set_ = {**row, ChunkRecordORM.metadata_: c.metadata}
                await session.execute(
                    pg_insert(ChunkRecordORM)
                    .values(values)
                    .on_conflict_do_update(index_elements=["chunk_id"], set_=set_)
                )
            await session.commit()

    async def search(
        self, query_vector: list[float], *, top_k: int, access: AccessContext
    ) -> list[VectorHit]:
        distance = ChunkRecordORM.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(ChunkRecordORM, distance)
            .where(ChunkRecordORM.embedding.is_not(None))
            .where(_visible_filter(ChunkRecordORM, access))
            .order_by(distance)
            .limit(top_k)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            hits: list[VectorHit] = []
            for row, dist in result.all():
                metadata = dict(row.metadata_) if row.metadata_ is not None else {}
                metadata.setdefault("doc_id", row.doc_id)
                hits.append(
                    VectorHit(
                        chunk_id=row.chunk_id,
                        score=1.0 - float(dist),  # 余弦相似度 = 1 - 余弦距离
                        content=row.content,
                        metadata=metadata,
                    )
                )
            return hits

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(ChunkRecordORM).where(ChunkRecordORM.chunk_id.in_(chunk_ids))
            )
            return [_row_to_chunk(row) for row in result.scalars()]

    async def list_chunks(self, *, access: AccessContext) -> list[ChunkRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ChunkRecordORM)
                .where(_visible_filter(ChunkRecordORM, access))
                .order_by(ChunkRecordORM.chunk_id)
            )
            return [_row_to_chunk(row) for row in result.scalars()]
