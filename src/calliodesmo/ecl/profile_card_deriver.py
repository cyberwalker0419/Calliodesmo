"""DeterministicProfileCardDeriver：从图邻居 + Covariate + Entity 确定性聚合档案卡。

- aliases：来自 NameEntityResolver 消解别名（经 engine 传入）
- associates：GraphStore.neighbors 中 person 类型邻居
- organization：邻居中 organization 类型（或关系 target 为组织类）
- role / timespan：Covariate 投影（按名称匹配）
- description / evidence：Entity 原文汇总与 source_chunk_ids
- narrative（可选）：经 LLMProvider 生成，**不进检索链路**，仅随 ProfileCard 供展示
- 全程零 LLM 调用（narrative 除外）；access 字段从 ingest 上下文派生
"""

from __future__ import annotations

import json

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.cognify import _data_access_fields, _normalize
from calliodesmo.interfaces.extractor import Covariate, Entity
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.profile_card import (
    ProfileCard,
    ProfileCardDeriver,
    ProfileField,
)

PERSON_TYPES = {"person", "people", "human", "individual", "人物"}
ORG_TYPES = {"organization", "organisation", "org", "company", "corporation", "组织"}
ROLE_NAMES = {"role", "title", "position", "职务", "职位", "头衔"}
TIMESPAN_NAMES = {"timespan", "time", "period", "时间跨度", "时间", "时期", "时段"}


class DeterministicProfileCardDeriver(ProfileCardDeriver):
    def __init__(self, llm: LLMProvider | None = None, *, temperature: float = 0.3) -> None:
        self.llm = llm
        self.temperature = temperature

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
        neighbors, _relations = await graph.neighbors(entity_name, access=access)

        associates = [
            ProfileField(value=n.name) for n in neighbors if (n.type or "").lower() in PERSON_TYPES
        ]
        org_neighbor = next((n for n in neighbors if (n.type or "").lower() in ORG_TYPES), None)
        organization = ProfileField(value=org_neighbor.name) if org_neighbor else None

        role = self._covariate(covariates, entity_name, ROLE_NAMES)
        timespan = self._covariate(covariates, entity_name, TIMESPAN_NAMES)

        alias_fields = [ProfileField(value=a) for a in (aliases or [])]
        fields = _data_access_fields(access)

        card = ProfileCard(
            entity_name=entity_name,
            entity_type=entity.type,
            aliases=alias_fields,
            role=role,
            organization=organization,
            associates=associates,
            timespan=timespan,
            description=entity.description,
            evidence_chunk_ids=list(entity.source_chunk_ids),
            **fields,
        )

        if self.llm is not None:
            card.narrative = await self._narrative(card)
        return card

    def _covariate(
        self, covariates: list[Covariate], entity_name: str, names: set[str]
    ) -> ProfileField | None:
        canon = entity_name.lower()
        for cv in covariates:
            if _normalize(cv.entity_name) == canon and cv.name.lower() in names:
                return ProfileField(value=cv.value)
        return None

    async def _narrative(self, card: ProfileCard) -> str:
        messages = [
            LLMMessage(
                "system",
                "你是实体档案卡叙述生成器。基于结构化字段写一段简短客观的叙述概述。"
                '严格只输出 JSON：{"narrative":"..."}，不要解释。',
            ),
            LLMMessage("user", card.to_context_text()),
        ]
        resp = await self.llm.complete(messages, temperature=self.temperature)
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> str:
        try:
            data = json.loads(content.strip().strip("`"))
            if isinstance(data, dict):
                return str(data.get("narrative", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
        return ""
