"""serve --seed-demo：演示数据注入（serve 进程内跑 ECL -> 内存 stores 单例）+ 落盘缓存。

- 演示文档文件名前缀决定 clearance：``public__*.md`` / ``internal__*.md`` /
  ``confidential__*.md``（缺省 INTERNAL），故意拉开梯度供权限矩阵回归与演示可见性隔离。
- 数据落 ingest 上下文的团队库（access.team_ids 非空时）：demo 团队成员按自身
  clearance 可见对应梯度；owner 记为 ingest 用户。
- 首次跑完整 ECL（含 LLM）较慢，产物序列化为 seed-cache.json；二次启动命中缓存
  直接加载、跳过 LLM。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.config import Settings
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.document_loader import DocumentLoader
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.profile_card import FieldProvenance, ProfileCard, ProfileField
from calliodesmo.interfaces.vector_store import ChunkRecord

#: 文件名前缀（``<level>__<slug>.md``）-> 数据 access_level
DEMO_FILE_LEVELS: dict[str, ClearanceLevel] = {
    "public": ClearanceLevel.PUBLIC,
    "internal": ClearanceLevel.INTERNAL,
    "confidential": ClearanceLevel.CONFIDENTIAL,
    "secret": ClearanceLevel.SECRET,
}


@dataclass
class DemoSeedReport:
    documents: int
    chunks: int
    profile_cards: int
    communities: int
    source: str  # "pipeline" | "cache"


class _DemoAccessLoader(DocumentLoader):
    """包装默认 registry loader：按文件名前缀注入 access 元数据（chunk 继承）。"""

    def __init__(self, inner: DocumentLoader, *, access: AccessContext) -> None:
        self.inner = inner
        self.access = access

    async def load(self, source: str | Path):
        docs = await self.inner.load(source)
        team_id = next(iter(self.access.team_ids), None)
        project_id = next(iter(self.access.project_ids), None)
        for doc in docs:
            prefix = Path(str(doc.doc_id)).name.split("__", 1)[0].lower()
            level = DEMO_FILE_LEVELS.get(prefix, ClearanceLevel.INTERNAL)
            doc.metadata.update(
                {
                    "access_level": level,
                    "library_scope": (
                        LibraryScope.TEAM
                        if team_id
                        else (LibraryScope.PROJECT if project_id else LibraryScope.PERSONAL)
                    ),
                    "owner_id": self.access.user_id,
                    "team_id": team_id,
                    "project_id": project_id,
                }
            )
        return docs


async def seed_demo_stores(
    stores,
    settings: Settings,
    *,
    demo_dir: Path,
    cache_file: Path,
    access: AccessContext,
) -> DemoSeedReport:
    """演示数据注入 stores 单例：缓存命中直接加载，否则跑 ECL 管线并落盘缓存。"""
    if _cache_exists(cache_file):
        await _load_cache(stores, cache_file)
        return DemoSeedReport(
            documents=len({c.doc_id for c in stores.vector_store._records.values()}),
            chunks=len(stores.vector_store),
            profile_cards=len(stores.profile_card_store),
            communities=len(stores.community_store),
            source="cache",
        )

    from calliodesmo.ecl.engine import build_default_indexing_engine

    engine = build_default_indexing_engine(
        settings,
        vector_store=stores.vector_store,
        graph_store=stores.graph_store,
        community_store=stores.community_store,
        profile_card_store=stores.profile_card_store,
    )
    engine.loader = _DemoAccessLoader(engine.loader, access=access)

    files = _list_demo_files(demo_dir)
    if not files:
        raise FileNotFoundError(f"演示目录无 .md/.txt 文档：{demo_dir}")

    total_chunks = 0
    for path in files:
        slug = path.stem.replace("__", "-")
        before = set(stores.community_store._records.keys())
        stats = await engine.ingest(path, access=access)
        total_chunks += stats.chunks
        # level-0 实体社区：cognify 派生的 access_level 恒 INTERNAL 且 comm-N 跨批次
        # 撞 id——按本批次重写：id 加文档 slug 前缀 + access_level 对齐文档梯度
        for cid in set(stores.community_store._records.keys()) - before:
            rec = stores.community_store._records[cid]
            if rec.level != 0:
                continue  # level-1 文档社区已从 chunk 继承正确梯度，id 按 doc 唯一
            del stores.community_store._records[cid]
            level = DEMO_FILE_LEVELS.get(
                path.stem.split("__", 1)[0].lower(), ClearanceLevel.INTERNAL
            )
            await stores.community_store.upsert_communities(
                [replace(rec, community_id=f"{cid}-{slug}", access_level=level)]
            )

    # 稀疏索引随 seed 构建（native_rag 混合路召回可用）
    await stores.sparse_index.index(list(stores.vector_store._records.values()))

    _write_cache(cache_file, _dump_cache(stores))
    return DemoSeedReport(
        documents=len(files),
        chunks=total_chunks,
        profile_cards=len(stores.profile_card_store),
        communities=len(stores.community_store),
        source="pipeline",
    )


# ---- 缓存序列化 ----


# ---- 同步文件 IO helper（async 函数内不直接用 pathlib，规避 ASYNC240）----


def _cache_exists(cache_file: Path) -> bool:
    return cache_file.exists()


def _list_demo_files(demo_dir: Path) -> list[Path]:
    """列出演示目录下所有文档文件（按加载器注册表分发：.md/.txt/.docx/.pdf 等）。

    仅 glob 文件，后缀分发由 ``LoaderRegistry.resolve`` 负责；未注册后缀会在
    ingest 时抛 ValueError 提示安装对应 extra（与 CLI ingest 一致）。
    """
    return sorted(p for p in demo_dir.glob("*") if p.is_file())


def _write_cache(cache_file: Path, payload: dict) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_cache(cache_file: Path) -> dict:
    return json.loads(cache_file.read_text(encoding="utf-8"))


def _json_safe(obj):
    """递归转 JSON 可序列化（委托 shared :func:`json_safe`，保留本名兼容旧调用点）。"""
    from calliodesmo.utils.json import json_safe

    return json_safe(obj)


def _access_dict(rec) -> dict[str, Any]:
    return {
        "access_level": int(rec.access_level),
        "library_scope": rec.library_scope.value,
        "owner_id": str(rec.owner_id) if rec.owner_id else None,
        "project_id": str(rec.project_id) if rec.project_id else None,
        "team_id": str(rec.team_id) if rec.team_id else None,
    }


def _access_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_level": ClearanceLevel(int(raw["access_level"])),
        "library_scope": LibraryScope(raw["library_scope"]),
        "owner_id": uuid.UUID(raw["owner_id"]) if raw.get("owner_id") else None,
        "project_id": uuid.UUID(raw["project_id"]) if raw.get("project_id") else None,
        "team_id": uuid.UUID(raw["team_id"]) if raw.get("team_id") else None,
    }


def _field_out(f: ProfileField | None) -> dict[str, Any] | None:
    if f is None:
        return None
    return {"value": f.value, "provenance": f.provenance.value, "locked": f.locked}


def _field_in(raw: dict[str, Any] | None) -> ProfileField | None:
    if raw is None:
        return None
    return ProfileField(
        value=raw["value"],
        provenance=FieldProvenance(raw.get("provenance", "auto")),
        locked=bool(raw.get("locked", False)),
    )


def _dump_cache(stores) -> dict[str, Any]:
    return {
        "version": 1,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "content": c.content,
                "vector": c.vector,
                "metadata": _json_safe(c.metadata),
                **_access_dict(c),
            }
            for c in stores.vector_store._records.values()
        ],
        "entities": [{**asdict(e), **_access_dict(e)} for e in _entity_dump(stores)],
        "relations": [
            {
                "source": r.source,
                "target": r.target,
                "type": r.type,
                "description": r.description,
                "source_chunk_ids": r.source_chunk_ids,
                "metadata": _json_safe(r.metadata),
                **_access_dict(r),
            }
            for r in stores.graph_store._relations.values()
        ],
        "communities": [
            {
                "community_id": c.community_id,
                "level": c.level,
                "title": c.title,
                "summary": c.summary,
                "member_entity_names": c.member_entity_names,
                "metadata": _json_safe(c.metadata),
                **_access_dict(c),
            }
            for c in stores.community_store._records.values()
        ],
        "profile_cards": [
            {
                "entity_name": c.entity_name,
                "entity_type": c.entity_type,
                "aliases": [_field_out(a) for a in c.aliases],
                "role": _field_out(c.role),
                "organization": _field_out(c.organization),
                "associates": [_field_out(a) for a in c.associates],
                "timespan": _field_out(c.timespan),
                "description": c.description,
                "narrative": c.narrative,
                "evidence_chunk_ids": c.evidence_chunk_ids,
                "version": c.version,
                **_access_dict(c),
            }
            for c in stores.profile_card_store._cards.values()
        ],
    }


def _entity_dump(stores) -> list[EntityRecord]:
    out = []
    for e in stores.graph_store._entities.values():
        out.append(
            EntityRecord(
                name=e.name,
                type=e.type,
                description=e.description,
                source_chunk_ids=e.source_chunk_ids,
                template_conforming=e.template_conforming,
                metadata=e.metadata,
                access_level=e.access_level,
                library_scope=e.library_scope,
                owner_id=e.owner_id,
                project_id=e.project_id,
                team_id=e.team_id,
            )
        )
    return out


async def _load_cache(stores, cache_file: Path) -> None:
    raw = _read_cache(cache_file)
    if raw.get("version") != 1:
        raise ValueError(f"未知 seed 缓存版本：{raw.get('version')}")

    chunks = [
        ChunkRecord(
            chunk_id=c["chunk_id"],
            doc_id=c["doc_id"],
            content=c["content"],
            vector=[float(v) for v in c["vector"]],
            metadata=dict(c.get("metadata") or {}),
            **_access_kwargs(c),
        )
        for c in raw["chunks"]
    ]
    await stores.vector_store.upsert_chunks(chunks)

    entities = [
        EntityRecord(
            name=e["name"],
            type=e.get("type"),
            description=e.get("description", ""),
            source_chunk_ids=list(e.get("source_chunk_ids") or []),
            template_conforming=bool(e.get("template_conforming", False)),
            metadata=dict(e.get("metadata") or {}),
            **_access_kwargs(e),
        )
        for e in raw["entities"]
    ]
    relations = [
        RelationRecord(
            source=r["source"],
            target=r["target"],
            type=r.get("type"),
            description=r.get("description", ""),
            source_chunk_ids=list(r.get("source_chunk_ids") or []),
            metadata=dict(r.get("metadata") or {}),
            **_access_kwargs(r),
        )
        for r in raw["relations"]
    ]
    await stores.graph_store.upsert_graph(entities, relations)

    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id=c["community_id"],
                level=int(c["level"]),
                title=c["title"],
                summary=c.get("summary", ""),
                member_entity_names=list(c.get("member_entity_names") or []),
                metadata=dict(c.get("metadata") or {}),
                **_access_kwargs(c),
            )
            for c in raw["communities"]
        ]
    )

    await stores.profile_card_store.upsert(
        [
            ProfileCard(
                entity_name=c["entity_name"],
                entity_type=c.get("entity_type"),
                aliases=[_field_in(a) for a in c.get("aliases", []) if a],
                role=_field_in(c.get("role")),
                organization=_field_in(c.get("organization")),
                associates=[_field_in(a) for a in c.get("associates", []) if a],
                timespan=_field_in(c.get("timespan")),
                description=c.get("description", ""),
                narrative=c.get("narrative"),
                evidence_chunk_ids=list(c.get("evidence_chunk_ids") or []),
                version=int(c.get("version", 1)),
                **_access_kwargs(c),
            )
            for c in raw["profile_cards"]
        ]
    )

    # 稀疏索引随缓存重建
    await stores.sparse_index.index(list(stores.vector_store._records.values()))
