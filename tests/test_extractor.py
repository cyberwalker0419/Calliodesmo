"""Task 2 Step 4-8：LLMExtractor 模板引导抽取 + 打标 + 健壮性测试。"""

import json
import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
from calliodesmo.ecl.extractor import ExtractionError, LLMExtractor
from calliodesmo.interfaces.chunker import Chunk
from calliodesmo.interfaces.extractor import ExtractionTemplate
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse


class _FakeLLM(LLMProvider):
    def __init__(self, content: str) -> None:
        self._content = content
        self.captured: list[LLMMessage] = []
        self.kwargs: dict = {}

    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        self.captured = messages
        self.kwargs = {"temperature": temperature, "max_tokens": max_tokens}
        return LLMResponse(content=self._content, model="fake")


def _ctx(team=None) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        team_ids=frozenset({team}) if team else frozenset(),
    )


def _chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id="d#0",
            doc_id="d",
            content="OpenAI 开发了 GPT-4。Sam Altman 是 CEO。",
            ordinal=0,
        ),
        Chunk(chunk_id="d#1", doc_id="d", content="OpenAI 位于旧金山。GPT-4 是大模型。", ordinal=1),
    ]


PAYLOAD = {
    "entities": [
        {"name": "OpenAI", "type": "organization", "description": "AI 公司"},
        {"name": "GPT-4", "type": "model", "description": "大语言模型"},
        {"name": "Sam Altman", "type": "person", "description": "CEO"},
    ],
    "relations": [
        {"source": "OpenAI", "target": "GPT-4", "type": "developed", "description": "开发"},
    ],
    "claims": [{"text": "OpenAI 位于旧金山", "entity_name": "OpenAI"}],
    "covariates": [{"name": "role", "entity_name": "Sam Altman", "value": "CEO"}],
}


async def test_template_guided_tagging():
    team = uuid.uuid4()
    template = ExtractionTemplate(
        team=str(team),
        preferred_entity_types=["organization", "person"],
        relation_types=["developed"],
    )
    reg = ExtractionTemplateRegistry({str(team): template})
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, reg, temperature=0.05, max_tokens=512)
    result = await ext.extract(_chunks(), access=_ctx(team))
    assert result.schema_mode == "template-guided"
    by_name = {e.name: e for e in result.entities}
    assert by_name["OpenAI"].template_conforming is True  # organization 在模板内
    assert by_name["Sam Altman"].template_conforming is True  # person 在模板内
    assert by_name["GPT-4"].template_conforming is False  # model 模板外
    assert "model" in result.discovered_types
    assert "organization" not in result.discovered_types
    assert "person" not in result.discovered_types


async def test_free_mode_no_template():
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    result = await ext.extract(_chunks(), access=_ctx())
    assert result.schema_mode == "free"
    assert all(not e.template_conforming for e in result.entities)
    assert result.discovered_types == []


async def test_source_chunk_ids_cover_all_occurrences():
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    result = await ext.extract(_chunks(), access=_ctx())
    openai = {e.name: e for e in result.entities}["OpenAI"]
    assert set(openai.source_chunk_ids) == {"d#0", "d#1"}
    gpt = {e.name: e for e in result.entities}["GPT-4"]
    assert set(gpt.source_chunk_ids) == {"d#0", "d#1"}


async def test_four_types_non_empty():
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    result = await ext.extract(_chunks(), access=_ctx())
    assert result.entities and result.relations and result.claims and result.covariates
    assert result.relations[0].source == "OpenAI"
    assert result.covariates[0].name == "role"


async def test_invalid_json_raises_extraction_error():
    llm = _FakeLLM("这不是 JSON {{{")
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    with pytest.raises(ExtractionError, match="非法 JSON"):
        await ext.extract(_chunks(), access=_ctx())


async def test_empty_response_raises_extraction_error():
    llm = _FakeLLM("")
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    with pytest.raises(ExtractionError, match="空内容"):
        await ext.extract(_chunks(), access=_ctx())


async def test_json_in_code_fence_tolerated():
    llm = _FakeLLM("```json\n" + json.dumps(PAYLOAD, ensure_ascii=False) + "\n```")
    ext = LLMExtractor(llm, ExtractionTemplateRegistry())
    result = await ext.extract(_chunks(), access=_ctx())
    assert len(result.entities) == 3


async def test_prompt_contains_template_guidance():
    team = uuid.uuid4()
    template = ExtractionTemplate(
        team=str(team),
        preferred_entity_types=["person", "organization"],
        type_descriptions={"person": "an individual"},
        relation_types=["works_for"],
        instructions="重点关注人物与组织。",
    )
    reg = ExtractionTemplateRegistry({str(team): template})
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, reg)
    await ext.extract(_chunks(), access=_ctx(team))
    system_text = llm.captured[0].content
    assert "person" in system_text and "organization" in system_text
    assert "works_for" in system_text
    assert "重点关注人物与组织" in system_text
    assert "模板外" in system_text
    assert "[chunk_id=d#0]" in llm.captured[1].content


async def test_model_params_passthrough():
    llm = _FakeLLM(json.dumps(PAYLOAD, ensure_ascii=False))
    ext = LLMExtractor(llm, ExtractionTemplateRegistry(), temperature=0.3, max_tokens=256)
    await ext.extract(_chunks(), access=_ctx())
    assert llm.kwargs["temperature"] == 0.3
    assert llm.kwargs["max_tokens"] == 256
