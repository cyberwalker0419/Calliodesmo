"""Extractor 抽象接口 + P1 全局共享抽取类型（Entity/Relation/Claim/Covariate/ExtractionResult）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from calliodesmo.auth.context import AccessContext


@dataclass
class Entity:
    name: str
    type: str | None
    description: str
    source_chunk_ids: list[str] = field(default_factory=list)
    template_conforming: bool = False  # 是否落入团队模板 preferred_entity_types


@dataclass
class Relation:
    source: str  # 实体 name
    target: str
    type: str | None
    description: str
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class Claim:
    text: str
    entity_name: str | None = None
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class Covariate:
    name: str
    entity_name: str
    value: str
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class ExtractionTemplate:
    """团队级抽取模板（软引导，非白名单）：每团队有且仅一套，user 可编辑、配置文件可改。"""

    team: str  # team_id 字符串
    preferred_entity_types: list[str] = field(default_factory=list)
    type_descriptions: dict[str, str] = field(default_factory=dict)
    relation_types: list[str] = field(default_factory=list)
    instructions: str = ""


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    covariates: list[Covariate] = field(default_factory=list)
    schema_mode: str = "free"  # "template-guided" | "free"
    discovered_types: list[str] = field(default_factory=list)  # 模板外新发现类型


class Extractor(ABC):
    @abstractmethod
    async def extract(self, chunks: list, *, access: AccessContext) -> ExtractionResult:
        """从 Chunk 列表抽取实体/关系/声明/协变量（chunks 元素为 Chunk）。"""
