"""LLMExtractor：经 LLMProvider 抽取实体/关系/声明/协变量四类，团队模板软引导 + 打标。

- prompt 注入团队模板引导（优先类型/含义/关系类型/指令），同时**明确要求抽取模板外实体**
- 解析 LLM 返回的 JSON；非法/空 -> 抛 ``ExtractionError``（含原始响应片段），不静默吞
- ``source_chunk_ids`` 由抽取器按实体名扫描各 chunk 确定（含所有出现该实体的 chunk）
- ``template_conforming``/``discovered_types``/``schema_mode`` 据模板打标
- 全程经 ``LLMProvider``，离线测试用 ``sys.modules`` 桩，零真实请求
"""

from __future__ import annotations

import json
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
from calliodesmo.interfaces.extractor import (
    Claim,
    Covariate,
    Entity,
    ExtractionResult,
    ExtractionTemplate,
    Extractor,
    Relation,
)
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider


class ExtractionError(RuntimeError):
    """LLM 抽取输出无法解析时抛出（含原始响应片段）。"""


class LLMExtractor(Extractor):
    def __init__(
        self,
        llm: LLMProvider,
        registry: ExtractionTemplateRegistry | None = None,
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry or ExtractionTemplateRegistry()
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ---- prompt 构造（透明可测）----
    def _build_messages(
        self, chunks: list, template: ExtractionTemplate | None
    ) -> list[LLMMessage]:
        chunk_block = "\n\n".join(f"[chunk_id={c.chunk_id}]\n{c.content}" for c in chunks)
        if template is not None:
            type_lines = (
                "\n".join(
                    f"- {t}: {template.type_descriptions.get(t, '')}".rstrip()
                    for t in template.preferred_entity_types
                )
                or "（无）"
            )
            relation_lines = ", ".join(template.relation_types) or "（无）"
            guidance = (
                "【团队抽取模板（软引导，非白名单）】\n"
                f"优先实体类型:\n{type_lines}\n"
                f"引导关系类型: {relation_lines}\n"
                f"用户指令: {template.instructions or '（无）'}\n"
                "注意：模板外实体**仍需抽取**并在 type 中如实填写，不要丢弃。"
            )
        else:
            guidance = "【无团队模板】自由抽取，schema_mode=free。"

        system = (
            "你是知识图谱抽取引擎。从给定文本块中抽取实体(entities)、关系(relations)、"
            "声明(claims)、协变量(covariates)四类结构化信息。\n"
            f"{guidance}\n"
            "严格只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块标记。"
            "JSON 结构：\n"
            '{"entities":[{"name","type","description"}],'
            '"relations":[{"source","target","type","description"}],'
            '"claims":[{"text","entity_name"}],'
            '"covariates":[{"name","entity_name","value"}]}'
        )
        user = f"请抽取以下文本块的结构化信息：\n\n{chunk_block}"
        return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]

    async def extract(self, chunks: list, *, access: AccessContext) -> ExtractionResult:
        template = self.registry.get_for_access(access)
        messages = self._build_messages(chunks, template)
        resp = await self.llm.complete(
            messages, temperature=self.temperature, max_tokens=self.max_tokens
        )
        raw = (resp.content or "").strip()
        payload = self._parse_json(raw)
        return self._to_result(payload, chunks, template)

    # ---- 解析 ----
    def _parse_json(self, raw: str) -> dict[str, Any]:
        if not raw:
            raise ExtractionError("LLM 返回空内容")
        text = raw
        if text.startswith("```"):
            text = text.strip("`")
            nl = text.find("\n")
            if nl != -1 and text[:nl].strip().lower() in {"json", ""}:
                text = text[nl + 1 :]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            snippet = raw[:200].replace("\n", " ")
            raise ExtractionError(f"LLM 返回非法 JSON: {exc}；原始片段: {snippet}") from exc
        if not isinstance(data, dict):
            raise ExtractionError(f"LLM 返回非对象 JSON: {raw[:200]}")
        return data

    def _to_result(
        self, data: dict[str, Any], chunks: list, template: ExtractionTemplate | None
    ) -> ExtractionResult:
        preferred = set(template.preferred_entity_types) if template else set()

        entities: list[Entity] = []
        for e in data.get("entities", []) or []:
            if not isinstance(e, dict) or "name" not in e:
                continue
            name = str(e["name"])
            etype = e.get("type")
            etype = str(etype) if etype is not None else None
            entities.append(
                Entity(
                    name=name,
                    type=etype,
                    description=str(e.get("description", "")),
                    source_chunk_ids=self._find_chunks(name, chunks),
                    template_conforming=bool(template and etype in preferred),
                )
            )

        relations: list[Relation] = []
        for r in data.get("relations", []) or []:
            if not isinstance(r, dict) or "source" not in r or "target" not in r:
                continue
            src, tgt = str(r["source"]), str(r["target"])
            ids = self._find_chunks(src, chunks) or self._find_chunks(tgt, chunks)
            rtype = r.get("type")
            relations.append(
                Relation(
                    source=src,
                    target=tgt,
                    type=str(rtype) if rtype is not None else None,
                    description=str(r.get("description", "")),
                    source_chunk_ids=ids,
                )
            )

        claims: list[Claim] = []
        for c in data.get("claims", []) or []:
            if not isinstance(c, dict) or "text" not in c:
                continue
            ename = c.get("entity_name")
            ename = str(ename) if ename is not None else None
            ids = (
                self._find_chunks(ename, chunks)
                if ename
                else self._find_text_chunks(str(c["text"]), chunks)
            )
            claims.append(Claim(text=str(c["text"]), entity_name=ename, source_chunk_ids=ids))

        covariates: list[Covariate] = []
        for cv in data.get("covariates", []) or []:
            if not isinstance(cv, dict) or "name" not in cv or "entity_name" not in cv:
                continue
            ename = str(cv["entity_name"])
            covariates.append(
                Covariate(
                    name=str(cv["name"]),
                    entity_name=ename,
                    value=str(cv.get("value", "")),
                    source_chunk_ids=self._find_chunks(ename, chunks),
                )
            )

        if template is None:
            discovered = []
        else:
            discovered = sorted({e.type for e in entities if e.type and e.type not in preferred})
        schema_mode = "template-guided" if template is not None else "free"

        return ExtractionResult(
            entities=entities,
            relations=relations,
            claims=claims,
            covariates=covariates,
            schema_mode=schema_mode,
            discovered_types=discovered,
        )

    # ---- 来源打标 ----
    @staticmethod
    def _find_chunks(name: str | None, chunks: list) -> list[str]:
        if not name:
            return []
        needle = name.lower()
        return [c.chunk_id for c in chunks if needle in c.content.lower()]

    @staticmethod
    def _find_text_chunks(text: str, chunks: list) -> list[str]:
        if not text:
            return []
        needle = text.lower()[:80]
        return [c.chunk_id for c in chunks if needle in c.content.lower()]
