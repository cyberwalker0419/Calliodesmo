"""serve --seed-demo：演示数据注入（serve 进程内跑 ECL -> 内存 stores 单例）+ 落盘缓存。

- 演示文档文件名前缀决定 clearance：``public__*.md`` / ``internal__*.md`` /
  ``confidential__*.md``（缺省 INTERNAL），故意拉开梯度供权限矩阵回归与演示可见性隔离。
- 数据落 ingest 上下文的团队库（access.team_ids 非空时）：demo 团队成员按自身
  clearance 可见对应梯度；owner 记为 ingest 用户。
- 首次跑完整 ECL（含 LLM）较慢，产物序列化为 seed-cache.json；二次启动命中缓存
  直接加载、跳过 LLM。
"""

from __future__ import annotations

import hashlib
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
    """演示数据注入 stores 单例：缓存命中直接加载，否则跑 ECL 管线并落盘缓存。

    缓存失效（P7 T1）：缓存载荷携带 ``seed_key`` 指纹（team / 语料清单
    相对路径+大小+mtime 的 sha256）；语料或 team 漂移 → 旧缓存迁移为 ``*.stale``
    留痕并重建；遗留缓存（无 ``seed_key``）同迁。

    真后端（postgres/neo4j）兼容（P7 T16）：缓存与 level-0 社区 id 重写为内存
    stores 专属（``_records`` 鸭子字段）；真后端直接落库、跳过缓存与重写（演示
    场景接受 level-0 comm-N 跨批撞 id 覆盖）。
    """
    is_mem = hasattr(stores.vector_store, "_records") and hasattr(
        stores.community_store, "_records"
    )
    seed_key = _seed_key(access, demo_dir, exclude=_cache_artifacts(cache_file))
    if is_mem and _cache_exists(cache_file):
        raw = _read_cache(cache_file)
        if raw.get("version") == 1 and raw.get("seed_key") == seed_key:
            await _load_cache(stores, cache_file)
            return DemoSeedReport(
                documents=len({c.doc_id for c in stores.vector_store._records.values()}),
                chunks=len(stores.vector_store),
                profile_cards=len(stores.profile_card_store),
                communities=len(stores.community_store),
                source="cache",
            )
        # 漂移或遗留缓存：迁移 .stale 后重建（不改原文件内容，便于排障回溯）
        _migrate_stale_cache(cache_file)

    from calliodesmo.ecl.engine import build_default_indexing_engine

    engine = build_default_indexing_engine(
        settings,
        vector_store=stores.vector_store,
        graph_store=stores.graph_store,
        community_store=stores.community_store,
        profile_card_store=stores.profile_card_store,
    )
    engine.loader = _DemoAccessLoader(engine.loader, access=access)

    files = _list_demo_files(demo_dir, exclude=_cache_artifacts(cache_file))
    if not files:
        raise FileNotFoundError(f"演示目录无 .md/.txt 文档：{demo_dir}")

    total_chunks = 0
    for path in files:
        slug = path.stem.replace("__", "-")
        before = set(stores.community_store._records.keys()) if is_mem else set()
        stats = await engine.ingest(path, access=access)
        total_chunks += stats.chunks
        # level-0 实体社区：cognify 派生的 access_level 恒 INTERNAL 且 comm-N 跨批次
        # 撞 id——按本批次重写：id 加文档 slug 前缀 + access_level 对齐文档梯度
        # （内存 stores 专属；真后端跳过，见模块口径）
        for cid in set(stores.community_store._records.keys()) - before if is_mem else set():
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
    if is_mem:
        await stores.sparse_index.index(list(stores.vector_store._records.values()))
        _write_cache(cache_file, _dump_cache(stores, seed_key=seed_key))
    return DemoSeedReport(
        documents=len(files),
        chunks=total_chunks,
        profile_cards=_safe_len(stores.profile_card_store),
        communities=_safe_len(stores.community_store),
        source="pipeline",
    )


def _safe_len(obj) -> int:
    """len() 兼容（真后端 store 无 __len__ 时回退 0，仅演示报告用）。"""
    try:
        return len(obj)
    except TypeError:
        return 0


# ---- 缓存序列化 ----


# ---- 同步文件 IO helper（async 函数内不直接用 pathlib，规避 ASYNC240）----


def _cache_exists(cache_file: Path) -> bool:
    return cache_file.exists()


def _list_demo_files(demo_dir: Path, *, exclude: set[Path]) -> list[Path]:
    """递归列出演示目录下所有文档文件（按加载器注册表分发：.md/.txt/.docx/.pdf 等）。

    嵌套语料经 ``rglob`` 递归发现（P7 T1：顶层 glob 缺口修复）；仅取文件，
    后缀分发由 ``LoaderRegistry.resolve`` 负责；未注册后缀会在 ingest 时抛
    ValueError 提示安装对应 extra（与 CLI ingest 一致）。``exclude`` 用于剔除
    落在语料目录内的缓存及其迁移产物（默认配置缓存在语料目录内）。
    """
    excluded = {p.resolve() for p in exclude}
    return sorted(p for p in demo_dir.rglob("*") if p.is_file() and p.resolve() not in excluded)


def _cache_artifacts(cache_file: Path) -> set[Path]:
    """缓存本体与迁移产物（``*.stale``）：语料列举与指纹计算均须剔除。"""
    return {cache_file, cache_file.with_name(cache_file.name + ".stale")}


def _migrate_stale_cache(cache_file: Path) -> None:
    """漂移/遗留缓存迁移为 ``*.stale`` 留痕（覆盖旧迁移产物，同步 IO 规避 ASYNC240）。"""
    cache_file.replace(cache_file.with_name(cache_file.name + ".stale"))


def _seed_key(access: AccessContext, demo_dir: Path, *, exclude: set[Path]) -> str:
    """缓存失效指纹：team / 语料清单（相对路径+大小+mtime）漂移即重建（P7 T1 口径）。"""
    team_id = next(iter(access.team_ids), None)
    parts = [f"team={team_id}"]
    for p in _list_demo_files(demo_dir, exclude=exclude):
        st = p.stat()
        parts.append(f"{p.relative_to(demo_dir).as_posix()}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


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


def _dump_cache(stores, *, seed_key: str) -> dict[str, Any]:
    return {
        "version": 1,
        "seed_key": seed_key,
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
