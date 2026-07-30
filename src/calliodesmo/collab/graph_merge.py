"""图谱合并纯函数：实体 (name,type) 去重、关系并集、来源打标(provenance)。

B4【修订】：v1 按 name 精确合并（store name 唯一），``merge_decision`` 标注
``exact_name_type`` / ``same_name_diff_type`` / ``new``，为 v2 embedding 三段式
阈值（auto-merge≥0.95 / 人工复核 0.85-0.95 / 新节点<0.85 + type blocking）留接口位。
"""

from __future__ import annotations

import uuid
from typing import Any

from calliodesmo.auth.models import LibraryScope
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord


def _with_provenance(metadata: dict, provenance: dict, merge_decision: str) -> dict[str, Any]:
    meta = dict(metadata)
    meta["provenance"] = provenance
    meta["merge_decision"] = merge_decision
    return meta


def merge_entities(
    source_entities: list[EntityRecord],
    *,
    target_entities: list[EntityRecord],
    target_scope: LibraryScope,
    target_project_id: uuid.UUID | None,
    target_team_id: uuid.UUID | None,
    provenance: dict,
) -> list[EntityRecord]:
    """实体按 name 去重合并（store name 唯一）。

    目标已存：并 source_chunk_ids（去重保序）、描述拼接（去重换行）、access_level 取较严 max、
    template_conforming 取或、打 provenance + merge_decision。
    新实体：改写 scope + provenance + merge_decision="new"，access_level 保留源值（不降密）。
    """
    by_name: dict[str, EntityRecord] = {e.name: e for e in target_entities}
    for src in source_entities:
        existing = by_name.get(src.name)
        if existing is None:
            by_name[src.name] = EntityRecord(
                name=src.name,
                type=src.type,
                description=src.description,
                source_chunk_ids=list(src.source_chunk_ids),
                template_conforming=src.template_conforming,
                metadata=_with_provenance(src.metadata, provenance, "new"),
                access_level=src.access_level,  # 保留源值（不降密）
                library_scope=target_scope,
                owner_id=None,  # project/team 共享库无个人 owner
                project_id=target_project_id,
                team_id=target_team_id,
            )
            continue
        # 已存：同名同类型=exact_name_type；同名不同类型=same_name_diff_type
        # （v1 仍合并，标冲突供 v2 embedding 解决）
        decision = "exact_name_type" if existing.type == src.type else "same_name_diff_type"
        chunk_ids = list(dict.fromkeys(existing.source_chunk_ids + src.source_chunk_ids))
        descs = [d for d in (existing.description, src.description) if d]
        desc = "\n".join(dict.fromkeys(descs))
        by_name[src.name] = EntityRecord(
            name=existing.name,
            type=existing.type,
            description=desc,
            source_chunk_ids=chunk_ids,
            template_conforming=existing.template_conforming or src.template_conforming,
            metadata=_with_provenance(existing.metadata, provenance, decision),
            access_level=max(existing.access_level, src.access_level),  # 取较严
            library_scope=target_scope,
            owner_id=None,
            project_id=target_project_id,
            team_id=target_team_id,
        )
    return list(by_name.values())


def merge_relations(
    source_relations: list[RelationRecord],
    *,
    target_relations: list[RelationRecord],
    target_scope: LibraryScope,
    target_project_id: uuid.UUID | None,
    target_team_id: uuid.UUID | None,
    provenance: dict,
) -> list[RelationRecord]:
    """关系按 (source,target,type) 并集去重；并 source_chunk_ids、打 provenance。"""
    by_key: dict[tuple, RelationRecord] = {
        (r.source, r.target, r.type): r for r in target_relations
    }
    for src in source_relations:
        key = (src.source, src.target, src.type)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = RelationRecord(
                source=src.source,
                target=src.target,
                type=src.type,
                description=src.description,
                source_chunk_ids=list(src.source_chunk_ids),
                metadata=_with_provenance(src.metadata, provenance, "new"),
                access_level=src.access_level,
                library_scope=target_scope,
                owner_id=None,
                project_id=target_project_id,
                team_id=target_team_id,
            )
            continue
        chunk_ids = list(dict.fromkeys(existing.source_chunk_ids + src.source_chunk_ids))
        by_key[key] = RelationRecord(
            source=existing.source,
            target=existing.target,
            type=existing.type,
            description=existing.description,
            source_chunk_ids=chunk_ids,
            metadata=_with_provenance(existing.metadata, provenance, "exact_name_type"),
            access_level=max(existing.access_level, src.access_level),
            library_scope=target_scope,
            owner_id=None,
            project_id=target_project_id,
            team_id=target_team_id,
        )
    return list(by_key.values())


def prune_source_chunks(
    entities: list[EntityRecord],
    relations: list[RelationRecord],
    *,
    remove_chunk_ids: set[str],
) -> tuple[list[EntityRecord], list[RelationRecord], list[str]]:
    """P4.5 Task 3 Step 2：从 entities/relations 的 source_chunk_ids 移除指定 chunk_ids。

    ``merge_entities``/``merge_relations`` 的逆运算（纯函数，不碰 store）。删除文档时，
    先把该文档的 chunk_ids 从所有实体/关系的来源里剔除：
    - 实体 ``source_chunk_ids`` 变空 -> 孤儿（返回 orphan_entity_names，由 store 删）
    - 关系 ``source_chunk_ids`` 变空 -> 直接丢弃（无证据边）
    返回 ``(kept_entities, kept_relations, orphan_entity_names)``。
    """
    remove = set(remove_chunk_ids)

    kept_entities: list[EntityRecord] = []
    orphans: list[str] = []
    for e in entities:
        pruned = [c for c in e.source_chunk_ids if c not in remove]
        if not pruned:
            orphans.append(e.name)
            continue  # 孤儿实体（无剩余来源）-> 由 store 删除
        kept_entities.append(
            EntityRecord(
                name=e.name,
                type=e.type,
                description=e.description,
                source_chunk_ids=pruned,
                template_conforming=e.template_conforming,
                metadata=dict(e.metadata),
                access_level=e.access_level,
                library_scope=e.library_scope,
                owner_id=e.owner_id,
                project_id=e.project_id,
                team_id=e.team_id,
            )
        )

    kept_relations: list[RelationRecord] = []
    for r in relations:
        pruned = [c for c in r.source_chunk_ids if c not in remove]
        if not pruned:
            continue  # 关系无剩余来源 -> 丢弃
        kept_relations.append(
            RelationRecord(
                source=r.source,
                target=r.target,
                type=r.type,
                description=r.description,
                source_chunk_ids=pruned,
                metadata=dict(r.metadata),
                access_level=r.access_level,
                library_scope=r.library_scope,
                owner_id=r.owner_id,
                project_id=r.project_id,
                team_id=r.team_id,
            )
        )
    return kept_entities, kept_relations, orphans
