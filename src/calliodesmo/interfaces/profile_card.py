"""ProfileCard：实体档案卡（结构化画像）接口与共享类型。

Task 7 在 Task 2/3 已抽取并消解的 ``Entity`` 基础上，从图邻居 + Covariate + Entity
**确定性聚合**出结构化档案卡，作为用户侧展示单元。

- **结构化字段**（别名/职务/组织/关联人/时间跨度/证据）是图与 Covariate 的客观投影，
  可进入模型上下文增强 LLM 可读性与精度（``to_context_text``，**不含 narrative**）。
- **叙述字段** ``narrative`` 为可选 LLM 生成概述，按"摘要不进模型"约束**不进入**
  检索/rerank/生成链路，仅供人阅读。
- ``provenance``/``locked``/``version`` 预留用户编辑接口（P4 review-gated），
  P1 恒为 ``AUTO``/``False``/``1``，不实现编辑逻辑。
"""

from __future__ import annotations

import enum
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.extractor import Covariate, Entity
from calliodesmo.interfaces.graph_store import GraphStore


class FieldProvenance(enum.StrEnum):
    AUTO = "auto"  # 自动聚合生成
    USER = "user"  # 用户编辑（P4）
    MERGED = "merged"  # 自动+用户合并（P4）


@dataclass
class ProfileField:
    value: str
    provenance: FieldProvenance = FieldProvenance.AUTO
    locked: bool = False  # 用户编辑过的字段不被自动覆盖（P4 生效；P1 恒 False）


@dataclass
class ProfileCard:
    entity_name: str
    entity_type: str | None
    aliases: list[ProfileField]
    role: ProfileField | None
    organization: ProfileField | None
    associates: list[ProfileField]
    timespan: ProfileField | None
    description: str
    narrative: str | None = None  # 可选 LLM 叙述（不进检索链路，仅供人读）
    evidence_chunk_ids: list[str] = field(default_factory=list)
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL
    library_scope: LibraryScope = LibraryScope.PERSONAL
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    version: int = 1  # P4 编辑版本，P1 恒 1

    def to_context_text(self) -> str:
        """序列化为结构化文本（喂模型上下文用）。

        **不含 narrative**：叙述字段不进检索/rerank/生成链路。仅含结构化字段 +
        description（自由文本汇总）+ 证据溯源。
        """
        parts = [f"实体: {self.entity_name}"]
        if self.entity_type:
            parts.append(f"类型: {self.entity_type}")
        alias_vals = [a.value for a in self.aliases]
        if alias_vals:
            parts.append("别名: " + ", ".join(alias_vals))
        if self.role:
            parts.append(f"职务: {self.role.value}")
        if self.organization:
            parts.append(f"所属组织: {self.organization.value}")
        assoc_vals = [a.value for a in self.associates]
        if assoc_vals:
            parts.append("关联人: " + ", ".join(assoc_vals))
        if self.timespan:
            parts.append(f"时间跨度: {self.timespan.value}")
        if self.description:
            parts.append(f"描述: {self.description}")
        if self.evidence_chunk_ids:
            parts.append("证据: " + ", ".join(self.evidence_chunk_ids))
        return "\n".join(parts)


class ProfileCardDeriver(ABC):
    @abstractmethod
    async def derive(
        self,
        entity_name: str,
        *,
        graph: GraphStore,
        covariates: list[Covariate],
        entity: Entity,
        access: AccessContext,
        aliases: list[str] | None = None,
    ) -> ProfileCard:
        """从已消解 Entity + 图邻居 + Covariate 聚合出 ProfileCard。"""


def _merge_field(existing: ProfileField | None, new: ProfileField | None) -> ProfileField | None:
    """合并单字段：existing 锁定则保留，否则取 new。"""
    if existing is not None and existing.locked:
        return existing
    return new


def _merge_list(existing: list[ProfileField], new: list[ProfileField]) -> list[ProfileField]:
    """合并列表字段：保留 existing 中锁定项，再追加 new 中未出现的值。"""
    merged = [f for f in existing if f.locked]
    seen = {f.value for f in merged}
    for f in new:
        if f.value not in seen:
            merged.append(f)
            seen.add(f.value)
    return merged


def merge_profile_card(existing: ProfileCard, new: ProfileCard) -> ProfileCard:
    """合并档案卡：保留 existing 中 locked 字段（P4 编辑保护），其余取 new，version+1。

    P1 无编辑（所有字段 AUTO/未锁），此函数退化为以 new 为主；接口预留给 P4。
    """
    return replace(
        new,
        aliases=_merge_list(existing.aliases, new.aliases),
        associates=_merge_list(existing.associates, new.associates),
        role=_merge_field(existing.role, new.role),
        organization=_merge_field(existing.organization, new.organization),
        timespan=_merge_field(existing.timespan, new.timespan),
        narrative=existing.narrative if existing.narrative else new.narrative,
        version=max(existing.version, new.version),
    )
