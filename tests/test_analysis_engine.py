"""P6 Task 10 测试：分析引擎与 factory（第一批五类接线，离线可跑）。

覆盖：

- ``interfaces/analysis.py`` 形状冻结：九值 ``AnalysisType``、dataclass 全 frozen、
  ``AnalysisEngine`` 抽象、``Evidence`` ↔ ``EvidenceRef`` 互转、与 ``analysis`` 域
  类型的 re-export 同一性；
- ``build_analysis_engine`` 复用 ``retrieval/factory.build_llm_provider`` 路由规则：
  ``test/*`` → 桩；``analysis_model`` 空回退 ``llm_model``；localhost / ``ollama/`` /
  ``lm-studio/`` 豁免 key；缺 key ``RuntimeError`` 带配置指引；
- 第一批 4 个模板驱动类型离线端到端（材料 → prompt → 桩 → 解析 → 证据自验 →
  信封 status=ok 且 prompt_version/usage 落位）；
- 问答类经**构造注入** 的 ``SearchEngine``（内存 stores + test/stub 装配，不经
  ``api/deps.get_search_engine()``）``.query`` 包成 ``QAReport``（来源标注沿用
  ``[chunk_id]`` 约定，空候选输出「无可引用证据」）；
- 证据自验在引擎内生效（匹配保真 / 失配封顶 + 降 partial）；
- 回喂重试回路（假 provider 首次坏 JSON、二次正常；校验失败同样回喂）；
- 预算耗尽 → 失败信号可读；部分抢救 → partial；render 侧双闸截断落 ``source_chunk_ids``。

全部离线（无 DB 夹具，CI ``-m "not db"`` 可跑）；桩对生成质量零区分度，
本文件只承诺结构与契约。
"""

import dataclasses
import json
import uuid

import pytest

from calliodesmo.analysis.engine import QA_PROMPT_VERSION, DefaultAnalysisEngine
from calliodesmo.analysis.factory import build_analysis_engine
from calliodesmo.analysis.schemas import (
    AnalysisStatus,
    AnalysisType,
    Evidence,
    KeyInfoReport,
    QAReport,
    SummaryReport,
)
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.config import Settings
from calliodesmo.interfaces.analysis import (
    AnalysisEngine,
    AnalysisMaterial,
    AnalysisReport,
    AnalysisSpec,
    EvidenceRef,
)
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import SearchEngine
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.providers.litellm_provider import LiteLLMProvider
from calliodesmo.providers.stub_llm import StubLLMProvider
from calliodesmo.retrieval.factory import build_default_search_engine
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _offline_settings(**overrides) -> Settings:
    """离线 settings：test/stub LLM + hash 嵌入 + 关闭 P5 检索增强开关（零网络零重依赖）。"""
    return Settings(
        llm_model="test/stub",
        analysis_model="",
        llm_api_key="",
        llm_api_base="",
        embedding_provider="hash",
        reranker_provider="none",
        multi_query_enabled=False,
        contextual_retrieval_enabled=False,
        crag_enabled=False,
        selfcheck_enabled=False,
    ).model_copy(update=overrides)


def _access() -> AccessContext:
    return AccessContext(
        user_id=USER_ID,
        username="analyst",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


def _material(chunk_id="doc1#1", text="OpenAI 于 2015 年成立，总部在旧金山。", doc_id="doc1"):
    return AnalysisMaterial(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_label="文档一",
        text=text,
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=USER_ID,
    )


def _engine(llm=None, settings=None, search_engine=None) -> DefaultAnalysisEngine:
    return DefaultAnalysisEngine(
        llm=llm if llm is not None else StubLLMProvider(),
        settings=settings if settings is not None else _offline_settings(),
        search_engine=search_engine,
    )


class _ScriptedLLM(LLMProvider):
    """脚本化假 provider：按调用次序返回预设原文（末条重复），记录调用与温度。"""

    def __init__(self, outputs: list[str], model: str = "test/scripted"):
        self.outputs = list(outputs)
        self.model = model
        self.calls: list[list[LLMMessage]] = []
        self.temperatures: list[float] = []

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        self.calls.append(list(messages))
        self.temperatures.append(temperature)
        content = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
        return LLMResponse(
            content=content,
            model=self.model,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )


class TestInterfacesContract:
    """interfaces/analysis.py 形状冻结（架构节冻结口径）。"""

    def test_analysis_type_nine_values(self):
        assert len(AnalysisType) == 9
        assert {t.value for t in AnalysisType} == {
            "summary",
            "key_information",
            "timeline",
            "entity_recognition",
            "relation_mapping",
            "tasks",
            "concepts",
            "qa",
            "custom",
        }

    def test_reexport_identity(self):
        """AnalysisType / AnalysisMaterial 为 re-export（单一锚点，不重复定义）。"""
        from calliodesmo.analysis import materials as materials_mod
        from calliodesmo.analysis import schemas as schemas_mod
        from calliodesmo.interfaces import analysis as interfaces_mod

        assert interfaces_mod.AnalysisType is schemas_mod.AnalysisType
        assert interfaces_mod.AnalysisMaterial is materials_mod.AnalysisMaterial

    @pytest.mark.parametrize(
        ("obj", "attr"),
        [
            (AnalysisSpec(task_type=AnalysisType.SUMMARY), "task_type"),
            (EvidenceRef(chunk_id="c1", quote="q"), "quote"),
            (
                AnalysisReport(
                    task_type=AnalysisType.SUMMARY,
                    status="ok",
                    payload={},
                    model="m",
                    prompt_version="summary.v1",
                    usage={},
                ),
                "status",
            ),
            (_material(), "text"),
        ],
    )
    def test_dataclasses_frozen(self, obj, attr):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, attr, "x")

    def test_analysis_spec_defaults(self):
        spec = AnalysisSpec(task_type=AnalysisType.QA)
        assert spec.doc_ids is None
        assert spec.question == ""
        assert spec.custom_instruction == ""
        assert spec.custom_schema is None
        assert spec.top_k == 10
        assert spec.model_override is None

    def test_analysis_engine_is_abstract(self):
        with pytest.raises(TypeError):
            AnalysisEngine()  # type: ignore[abstract]
        assert issubclass(DefaultAnalysisEngine, AnalysisEngine)

    def test_evidence_ref_roundtrip(self):
        """Evidence ↔ EvidenceRef 一一对应互转（confidence 不参与互转）。"""
        ev = Evidence(chunk_id="c1", quote="引文", confidence=0.9)
        ref = ev.to_ref()
        assert isinstance(ref, EvidenceRef)
        assert (ref.chunk_id, ref.quote) == ("c1", "引文")
        back = Evidence.from_ref(ref)
        assert (back.chunk_id, back.quote, back.confidence) == ("c1", "引文", 1.0)


class TestBuildAnalysisEngineRouting:
    """build_analysis_engine 复用 retrieval/factory.build_llm_provider 路由规则。"""

    def test_test_model_routes_to_stub(self):
        engine = build_analysis_engine(_offline_settings(analysis_model="test/stub-analysis"))
        assert isinstance(engine._llm, StubLLMProvider)
        assert engine._llm.model == "test/stub-analysis"

    def test_analysis_model_falls_back_to_llm_model(self):
        engine = build_analysis_engine(
            _offline_settings(analysis_model="", llm_model="test/stub-base")
        )
        assert isinstance(engine._llm, StubLLMProvider)
        assert engine._llm.model == "test/stub-base"

    @pytest.mark.parametrize(
        "settings_update",
        [
            # localhost API base 豁免 key
            {"analysis_model": "openai/gpt-4o-mini", "llm_api_base": "http://localhost:8080/v1"},
            {"analysis_model": "openai/gpt-4o-mini", "llm_api_base": "http://127.0.0.1:8080/v1"},
            # ollama/ 与 lm-studio/ 前缀豁免
            {"analysis_model": "ollama/qwen2.5:7b"},
            {"analysis_model": "lm-studio/qwen2.5-7b-instruct"},
        ],
    )
    def test_local_and_local_prefix_exempt_from_key(self, settings_update):
        engine = build_analysis_engine(_offline_settings(**settings_update))
        assert isinstance(engine._llm, LiteLLMProvider)

    def test_missing_key_raises_with_config_guidance(self):
        with pytest.raises(RuntimeError, match="CALLIODESMO_LLM_API_KEY"):
            build_analysis_engine(_offline_settings(analysis_model="openai/gpt-4o-mini"))

    def test_search_engine_injection_passthrough(self):
        sentinel = object()
        engine = build_analysis_engine(_offline_settings(), search_engine=sentinel)
        assert engine._search_engine is sentinel


_FIRST_BATCH_TEMPLATE_TYPES = [
    AnalysisType.SUMMARY,
    AnalysisType.KEY_INFORMATION,
    AnalysisType.TIMELINE,
    AnalysisType.ENTITY_RECOGNITION,
]


class TestOfflineEndToEnd:
    """第一批模板驱动类型离线端到端：材料 → prompt → 桩 → 解析 → 证据自验 → 信封。"""

    @pytest.mark.parametrize("task_type", _FIRST_BATCH_TEMPLATE_TYPES)
    async def test_stub_end_to_end_status_ok(self, task_type):
        engine = _engine()
        report = await engine.run(AnalysisSpec(task_type=task_type), [_material()], _access())
        assert isinstance(report, AnalysisReport)
        assert report.task_type is task_type
        assert report.status == AnalysisStatus.OK.value
        assert report.model == "test/stub"
        assert report.prompt_version == f"{task_type.value}.v1"
        assert report.usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        assert report.source_chunk_ids == ["doc1#1"]
        # 桩输出不带证据 → 证据自验零节点，不产生 warning；缺证据降置信由模型校验器承担
        assert report.warnings == []
        # payload 经对应报告模型二次校验通过
        from calliodesmo.analysis.specs import get_spec

        get_spec(task_type).output_cls.model_validate(report.payload)

    async def test_evidence_matching_quote_keeps_status_ok(self):
        """证据自验：quote 为源文子串 → 校验通过，置信保持。"""
        payload = {
            "summary": "OpenAI 简介",
            "key_points": ["2015 年成立"],
            "confidence": 0.9,
            "evidence": [{"chunk_id": "doc1#1", "quote": "总部在旧金山", "confidence": 0.9}],
        }
        llm = _ScriptedLLM([json.dumps(payload, ensure_ascii=False)])
        report = await _engine(llm=llm).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY), [_material()], _access()
        )
        assert report.status == AnalysisStatus.OK.value
        assert report.warnings == []
        assert report.payload["evidence"][0]["confidence"] == 0.9

    async def test_evidence_mismatch_caps_confidence_and_demotes_partial(self):
        """证据自验：quote 失配 → 置信封顶 0.3 + warning；失败占比 >30% → partial。"""
        payload = {
            "summary": "OpenAI 简介",
            "key_points": [],
            "confidence": 0.9,
            "evidence": [{"chunk_id": "doc1#1", "quote": "总部在纽约（不在源文中）"}],
        }
        llm = _ScriptedLLM([json.dumps(payload, ensure_ascii=False)])
        report = await _engine(llm=llm).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY), [_material()], _access()
        )
        assert report.status == AnalysisStatus.PARTIAL.value
        assert report.payload["evidence"][0]["confidence"] == pytest.approx(0.3)
        assert any("证据校验失败" in w for w in report.warnings)

    async def test_chunk_gate_limits_source_chunk_ids(self):
        """render 侧双闸（块数闸）截断：source_chunk_ids 只含实际进入提示词的块。"""
        settings = _offline_settings(analysis_max_chunks=1)
        report = await _engine(settings=settings).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY),
            [_material(chunk_id="doc1#1"), _material(chunk_id="doc1#2", text="第二块文本")],
            _access(),
        )
        assert report.source_chunk_ids == ["doc1#1"]

    async def test_model_override_builds_one_off_provider(self):
        """spec.model_override：本次运行临时构造 provider（路由规则同 factory）。"""
        report = await _engine().run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY, model_override="test/stub-override"),
            [_material()],
            _access(),
        )
        assert report.model == "test/stub-override"


class TestQAViaSearchEngine:
    """问答类经构造注入的 SearchEngine（离线：内存 stores + test/stub 装配）。"""

    async def _build_offline_search_engine(self, chunks):
        settings = _offline_settings()
        vector_store = InMemoryVectorStore()
        sparse_index = InMemoryBM25Index()
        await vector_store.upsert_chunks(chunks)
        await sparse_index.index(chunks)
        return build_default_search_engine(
            settings,
            vector_store=vector_store,
            graph_store=InMemoryGraphStore(),
            community_store=InMemoryCommunityStore(),
            sparse_index=sparse_index,
        )

    def _chunk(self, chunk_id, content, settings):
        emb = HashEmbeddingProvider(dimension=settings.embedding_dimension)
        from calliodesmo.interfaces.vector_store import ChunkRecord

        return ChunkRecord(
            chunk_id=chunk_id,
            doc_id="doc1",
            content=content,
            vector=emb._embed_one(content),
            owner_id=USER_ID,
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
        )

    async def test_qa_wraps_answer_into_qa_report(self):
        settings = _offline_settings()
        chunks = [
            self._chunk("c1", "OpenAI developed GPT-4, a large language model", settings),
            self._chunk("c2", "Cooking recipes for dinner", settings),
        ]
        search_engine = await self._build_offline_search_engine(chunks)
        engine = _engine(search_engine=search_engine)
        question = "OpenAI 开发了什么模型？"
        report = await engine.run(
            AnalysisSpec(task_type=AnalysisType.QA, question=question, top_k=5), (), _access()
        )
        assert report.task_type is AnalysisType.QA
        assert report.status == AnalysisStatus.OK.value
        assert report.prompt_version == QA_PROMPT_VERSION
        payload = QAReport.model_validate(report.payload)
        assert payload.question == question
        assert payload.answer  # 桩合成器输出（结构承诺，非质量承诺）
        # 桩合成器不带 [chunk_id] 标注 → 回退全部候选；来源标注沿用 [chunk_id] 约定
        assert set(payload.citations) == {"c1", "c2"}
        assert set(report.source_chunk_ids) == set(payload.citations)
        assert report.usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def test_qa_empty_candidates_outputs_no_evidence(self):
        search_engine = await self._build_offline_search_engine([])
        report = await _engine(search_engine=search_engine).run(
            AnalysisSpec(task_type=AnalysisType.QA, question="任意问题"), (), _access()
        )
        assert report.status == AnalysisStatus.OK.value
        assert report.payload["answer"].startswith("无可引用证据")
        assert report.payload["citations"] == []
        assert report.source_chunk_ids == []

    async def test_qa_without_search_engine_raises_readable(self):
        with pytest.raises(RuntimeError, match="SearchEngine"):
            await _engine().run(
                AnalysisSpec(task_type=AnalysisType.QA, question="任意问题"), (), _access()
            )

    async def test_qa_blank_question_raises(self):
        search_engine = await self._build_offline_search_engine([])
        with pytest.raises(ValueError):
            await _engine(search_engine=search_engine).run(
                AnalysisSpec(task_type=AnalysisType.QA, question="   "), (), _access()
            )

    async def test_injected_engine_is_used_not_api_deps(self):
        """QA 只经构造注入的 SearchEngine：注入记录型替身即可断言 .query 被调用。"""

        from calliodesmo.interfaces.retriever import Answer, SearchMode

        class _RecordingEngine(SearchEngine):
            def __init__(self):
                self.query_calls: list[tuple] = []

            async def query(self, question, *, mode, top_k, access):
                self.query_calls.append((question, mode, top_k, access))
                return Answer(text="无可引用证据（替身）", source_chunk_ids=[], mode=mode)

        recorder = _RecordingEngine()
        report = await _engine(search_engine=recorder).run(
            AnalysisSpec(task_type=AnalysisType.QA, question="问题 X", top_k=3), (), _access()
        )
        assert len(recorder.query_calls) == 1
        question, mode, top_k, access = recorder.query_calls[0]
        assert question == "问题 X"
        assert mode == SearchMode.NATIVE_RAG
        assert top_k == 3
        assert access == _access()
        assert report.payload["answer"] == "无可引用证据（替身）"


class TestFeedbackRetry:
    """回喂重试回路：假 provider 首次坏输出、二次正常；预算耗尽 → 失败信号可读。"""

    async def test_bad_json_then_good_recovers(self):
        good = json.dumps(
            {"summary": "OpenAI 简介", "key_points": ["要点"], "confidence": 1.0},
            ensure_ascii=False,
        )
        llm = _ScriptedLLM(["这不是 JSON", good])
        settings = _offline_settings(analysis_temperature=0.3)
        report = await _engine(llm=llm, settings=settings).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY), [_material()], _access()
        )
        assert report.status == AnalysisStatus.OK.value
        assert SummaryReport.model_validate(report.payload)
        # 两次调用：首次坏输出，第二次收到回喂消息（第三消息为反馈）
        assert len(llm.calls) == 2
        assert [m.role for m in llm.calls[0]] == ["system", "user"]
        assert [m.role for m in llm.calls[1]] == ["system", "user", "user"]
        assert "不是合法 JSON" in llm.calls[1][2].content
        assert "原始输出片段" in llm.calls[1][2].content
        # 温度经 settings.analysis_temperature 传入；usage 跨重试累计
        assert llm.temperatures == [0.3, 0.3]
        assert report.usage == {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6}

    async def test_validation_error_fed_back_then_good(self):
        good = json.dumps({"summary": "正常摘要", "key_points": []}, ensure_ascii=False)
        bad_validation = json.dumps({"summary": "   "}, ensure_ascii=False)  # 空白 summary 校验失败
        llm = _ScriptedLLM([bad_validation, good])
        report = await _engine(llm=llm).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY), [_material()], _access()
        )
        assert report.status == AnalysisStatus.OK.value
        assert len(llm.calls) == 2
        assert "未通过结构校验" in llm.calls[1][2].content

    async def test_budget_exhausted_failed_signal_readable(self):
        llm = _ScriptedLLM(["始终不是合法 JSON 的散文输出"])
        report = await _engine(llm=llm).run(
            AnalysisSpec(task_type=AnalysisType.SUMMARY), [_material()], _access()
        )
        assert report.status == AnalysisStatus.FAILED.value
        assert report.payload == {}
        # 预算 analysis_parse_retries=2 → 共 3 次尝试
        assert len(llm.calls) == 3
        assert report.warnings
        assert "非法 JSON" in report.warnings[0]
        assert report.prompt_version == "summary.v1"

    async def test_budget_exhausted_salvages_partial(self):
        """预算耗尽 + 部分抢救：可校验条目保留，状态降 partial 并留降级原因。"""
        mixed = json.dumps(
            {
                "items": [
                    {"label": "时间", "value": "2026年", "confidence": 1.0},
                    {"label": "   ", "value": "空白标签非法"},
                ]
            },
            ensure_ascii=False,
        )
        llm = _ScriptedLLM([mixed])
        report = await _engine(llm=llm).run(
            AnalysisSpec(task_type=AnalysisType.KEY_INFORMATION), [_material()], _access()
        )
        assert report.status == AnalysisStatus.PARTIAL.value
        salvaged = KeyInfoReport.model_validate(report.payload)
        assert [item.label for item in salvaged.items] == ["时间"]
        assert any("部分抢救" in w for w in report.warnings)
        assert len(llm.calls) == 3
