"""Task 7：实体档案卡（ProfileCard）自动生成测试。"""

import json
import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.chunker import TextChunker
from calliodesmo.ecl.cognify import CognifyPipeline
from calliodesmo.ecl.community_deriver import DocumentCommunityDeriver
from calliodesmo.ecl.engine import ECLIndexingEngine
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
from calliodesmo.ecl.extractor import LLMExtractor
from calliodesmo.ecl.load import LoadService
from calliodesmo.ecl.profile_card_deriver import DeterministicProfileCardDeriver
from calliodesmo.interfaces.extractor import Entity
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.profile_card import (
    FieldProvenance,
    ProfileCard,
    ProfileField,
    merge_profile_card,
)
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.providers.registry import default_registry
from calliodesmo.stores.profile_card_store import InMemoryProfileCardStore


def _ctx(user) -> AccessContext:
    return AccessContext(user_id=user, username="u", clearance=ClearanceLevel.INTERNAL)


def _personal(owner):
    return {
        "library_scope": LibraryScope.PERSONAL,
        "owner_id": owner,
        "access_level": ClearanceLevel.INTERNAL,
    }


async def _loaded_graph_store(owner):
    gs = InMemoryGraphStore()
    ents = [
        EntityRecord(name="openai", type="organization", description="AI 公司", **_personal(owner)),
        EntityRecord(name="sam altman", type="person", description="CEO", **_personal(owner)),
        EntityRecord(name="gpt-4", type="model", description="大模型", **_personal(owner)),
    ]
    rels = [
        RelationRecord(
            source="openai", target="gpt-4", type="developed", description="", **_personal(owner)
        ),
        RelationRecord(
            source="sam altman", target="openai", type="leads", description="", **_personal(owner)
        ),
    ]
    await gs.upsert_graph(ents, rels)
    return gs


def _covariates():
    from calliodesmo.interfaces.extractor import Covariate

    return [
        Covariate(name="role", entity_name="Sam Altman", value="CEO", source_chunk_ids=["d#0"]),
        Covariate(
            name="timespan", entity_name="OpenAI", value="2015-至今", source_chunk_ids=["d#0"]
        ),
    ]


# ---- Step 1: 数据模型 ----


def test_profile_card_data_model():
    owner = uuid.uuid4()
    card = ProfileCard(
        entity_name="openai",
        entity_type="organization",
        aliases=[ProfileField("OpenAI")],
        role=None,
        organization=None,
        associates=[ProfileField("sam altman")],
        timespan=ProfileField("2015-至今"),
        description="AI 公司",
        evidence_chunk_ids=["d#0"],
        **_personal(owner),
    )
    assert card.entity_name == "openai"
    assert card.version == 1
    assert card.narrative is None
    assert card.access_level == ClearanceLevel.INTERNAL
    assert card.owner_id == owner
    assert card.aliases[0].provenance == FieldProvenance.AUTO
    assert card.aliases[0].locked is False


# ---- Step 2: 确定性聚合 ----


async def test_deterministic_deriver_aggregation():
    owner = uuid.uuid4()
    gs = await _loaded_graph_store(owner)
    deriver = DeterministicProfileCardDeriver(llm=None)
    entity = Entity(
        name="openai", type="organization", description="AI 公司", source_chunk_ids=["d#0", "d#1"]
    )
    card = await deriver.derive(
        "openai",
        graph=gs,
        covariates=_covariates(),
        entity=entity,
        access=_ctx(owner),
        aliases=["OpenAI", "openai"],
    )
    # associates：person 邻居 sam altman
    assert [a.value for a in card.associates] == ["sam altman"]
    # organization：openai 自身是 org，邻居无 org -> None
    assert card.organization is None
    # aliases 透传
    assert {a.value for a in card.aliases} == {"OpenAI", "openai"}
    # timespan 来自 Covariate
    assert card.timespan is not None and card.timespan.value == "2015-至今"
    # role 无（openai 无 role covariate）
    assert card.role is None
    # description/evidence
    assert card.description == "AI 公司"
    assert set(card.evidence_chunk_ids) == {"d#0", "d#1"}
    # 无 LLM -> 无 narrative
    assert card.narrative is None


async def test_deterministic_deriver_person_card():
    owner = uuid.uuid4()
    gs = await _loaded_graph_store(owner)
    deriver = DeterministicProfileCardDeriver(llm=None)
    entity = Entity(name="sam altman", type="person", description="CEO", source_chunk_ids=["d#0"])
    card = await deriver.derive(
        "sam altman",
        graph=gs,
        covariates=_covariates(),
        entity=entity,
        access=_ctx(owner),
    )
    # organization：邻居 openai 为 org
    assert card.organization is not None and card.organization.value == "openai"
    # role 来自 Covariate
    assert card.role is not None and card.role.value == "CEO"
    # 模型邻居 gpt-4 不是 person -> 不在 associates
    assert all("gpt" not in a.value for a in card.associates)


# ---- Step 3: 结构化字段进模型上下文，narrative 不进 ----


def test_to_context_text_excludes_narrative():
    card = ProfileCard(
        entity_name="openai",
        entity_type="organization",
        aliases=[ProfileField("OpenAI")],
        role=ProfileField("lab"),
        organization=None,
        associates=[ProfileField("sam altman")],
        timespan=None,
        description="AI 公司",
        narrative="这是一段叙述。",
    )
    text = card.to_context_text()
    assert "openai" in text and "organization" in text
    assert "sam altman" in text and "AI 公司" in text
    # narrative 不进上下文
    assert "叙述" not in text


# ---- Step 4: 可选 narrative（LLM），不进检索链路 ----


class _NarrLLM(LLMProvider):
    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"narrative": "OpenAI 是一家人工智能公司。"}, ensure_ascii=False),
            model="stub",
        )


async def test_narrative_via_llm_not_in_retrieval_stores():
    owner = uuid.uuid4()
    gs = await _loaded_graph_store(owner)
    deriver = DeterministicProfileCardDeriver(llm=_NarrLLM())
    entity = Entity(
        name="openai", type="organization", description="AI 公司", source_chunk_ids=["d#0"]
    )
    card = await deriver.derive(
        "openai",
        graph=gs,
        covariates=_covariates(),
        entity=entity,
        access=_ctx(owner),
    )
    assert card.narrative is not None and "人工智能" in card.narrative
    # narrative 不在 to_context_text（不进检索/rerank/生成）
    assert card.narrative not in card.to_context_text()


# ---- Step 5: InMemoryProfileCardStore ----


async def test_profile_card_store_visible_and_idempotent():
    owner = uuid.uuid4()
    store = InMemoryProfileCardStore()
    card = ProfileCard(
        entity_name="openai",
        entity_type="organization",
        aliases=[ProfileField("OpenAI")],
        role=None,
        organization=None,
        associates=[],
        timespan=None,
        description="v1",
        **_personal(owner),
    )
    await store.upsert([card])
    await store.upsert([card])  # 幂等
    assert len(store) == 1
    assert await store.get("openai", access=_ctx(owner)) is not None
    # 越权不可见
    assert await store.get("openai", access=_ctx(uuid.uuid4())) is None
    listed = await store.list(access=_ctx(owner))
    assert len(listed) == 1
    assert await store.list(access=_ctx(uuid.uuid4())) == []


# ---- Step 6: 引擎可选串联 ----


class _ExtLLM(LLMProvider):
    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(
                {
                    "entities": [
                        {"name": "OpenAI", "type": "organization", "description": "AI 公司"},
                        {"name": "Sam Altman", "type": "person", "description": "CEO"},
                        {"name": "GPT-4", "type": "model", "description": "大模型"},
                    ],
                    "relations": [
                        {
                            "source": "OpenAI",
                            "target": "GPT-4",
                            "type": "developed",
                            "description": "",
                        },
                        {
                            "source": "Sam Altman",
                            "target": "OpenAI",
                            "type": "leads",
                            "description": "",
                        },
                    ],
                    "claims": [],
                    "covariates": [
                        {"name": "role", "entity_name": "Sam Altman", "value": "CEO"},
                    ],
                },
                ensure_ascii=False,
            ),
            model="stub",
        )


class _SumLLM(LLMProvider):
    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(content='{"title":"T","summary":"S"}', model="stub")


def _build_engine(*, enable_profile=True):
    vs = InMemoryVectorStore()
    gs = InMemoryGraphStore()
    cs = InMemoryCommunityStore()
    pcs = InMemoryProfileCardStore()
    return ECLIndexingEngine(
        loader=default_registry(),
        chunker=TextChunker(),
        extractor=LLMExtractor(_ExtLLM(), ExtractionTemplateRegistry()),
        cognify=CognifyPipeline(summarizer=None),
        load_service=LoadService(vs, gs, cs, HashEmbeddingProvider(32)),
        deriver=DocumentCommunityDeriver(_SumLLM(), cs),
        profile_deriver=DeterministicProfileCardDeriver(llm=None),
        profile_card_store=pcs,
        enable_profile_cards=enable_profile,
    ), pcs


async def test_engine_chains_profile_cards(tmp_path):
    (tmp_path / "note.md").write_text(
        "OpenAI 开发了 GPT-4。Sam Altman 是 OpenAI 的 CEO。", encoding="utf-8"
    )
    owner = uuid.uuid4()
    engine, pcs = _build_engine(enable_profile=True)
    stats = await engine.ingest(tmp_path, access=_ctx(owner))
    assert stats.profile_cards > 0
    cards = await pcs.list(access=_ctx(owner))
    assert any(c.entity_name == "openai" for c in cards)


async def test_engine_profile_disabled(tmp_path):
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    owner = uuid.uuid4()
    engine, pcs = _build_engine(enable_profile=False)
    stats = await engine.ingest(tmp_path, access=_ctx(owner))
    assert stats.profile_cards == 0
    assert len(pcs) == 0


# ---- Step 7: provenance/locked 预留 ----


def test_all_fields_auto_and_unlocked():
    owner = uuid.uuid4()
    card = ProfileCard(
        entity_name="x",
        entity_type=None,
        aliases=[ProfileField("x")],
        role=ProfileField("r"),
        organization=ProfileField("o"),
        associates=[ProfileField("a")],
        timespan=ProfileField("t"),
        description="d",
        **_personal(owner),
    )
    fields = card.aliases + card.associates + [card.role, card.organization, card.timespan]
    for f in fields:
        assert f is not None
        assert f.provenance == FieldProvenance.AUTO
        assert f.locked is False
    assert card.version == 1


def test_merge_preserves_locked_field():
    # existing 用户锁定 role（P4 编辑场景），自动重派生不应覆盖
    existing = ProfileCard(
        entity_name="sam altman",
        entity_type="person",
        aliases=[],
        role=ProfileField("用户编辑职务", provenance=FieldProvenance.USER, locked=True),
        organization=None,
        associates=[],
        timespan=None,
        description="d",
    )
    new = ProfileCard(
        entity_name="sam altman",
        entity_type="person",
        aliases=[],
        role=ProfileField("自动职务"),
        organization=None,
        associates=[],
        timespan=None,
        description="d",
    )
    merged = merge_profile_card(existing, new)
    assert merged.role.value == "用户编辑职务"  # 锁定保留
    assert merged.role.locked is True
    assert merged.version >= existing.version
