"""P9 Task 2：输出层注入防御与敏感输出护栏单测。"""

from __future__ import annotations

from calliodesmo.security.output_guard import (
    SAFE_BLOCK_TEXT,
    GuardResult,
    guard_output,
    guard_payload,
)

_SOURCE = (
    "APT28（又称 Fancy Bear）是疑似源自俄罗斯的威胁组织，长期针对政府与国防目标。"
    "该组织擅长鱼叉钓鱼与零日漏洞利用。近期观察到其使用新型后门 Zebrocy 的变种。"
    "追踪由分析师李华负责。Fancy Bear 与 APT28 为同一组织。Zebrocy 后门经 Go 语言重写，"
    "跨平台能力增强。此外，该组织还在持续更新其基础设施与投递链，值得持续监控。"
    "本月新增观察到其针对能源行业的定向钓鱼活动，投递链使用多层重定向与合法云服务中转，"
    "并在载荷侧加入反沙箱检测与环境指纹校验，相关基础设施仍在活跃更新中。"
)
_SYSTEM_PROMPT = "你是答案合成引擎。基于给定的上下文文本块回答用户问题，不得输出内部字段。"


def _kinds(result: GuardResult) -> set[str]:
    return {v.kind for v in result.violations}


class TestVerbatimDump:
    def test_full_dump_blocked(self):
        result = guard_output(_SOURCE, sources={"doc#0": _SOURCE})
        assert result.blocked
        assert "verbatim_dump" in _kinds(result)
        assert result.text == SAFE_BLOCK_TEXT

    def test_short_quote_allowed(self):
        result = guard_output(
            "APT28 又称 Fancy Bear，是俄罗斯背景的威胁组织。", sources={"doc#0": _SOURCE}
        )
        assert not result.blocked
        assert result.text.startswith("APT28")

    def test_citation_tokens_do_not_bypass_dump_check(self):
        """后处理插入的 [chunk_id] 不能成为绕过全文倾倒检测的缝隙。"""
        chunks = [_SOURCE[i : i + 60] for i in range(0, len(_SOURCE), 60)]
        dumped = "[c1]".join(chunks)
        result = guard_output(dumped, sources={"c1": _SOURCE})
        assert result.blocked
        assert "verbatim_dump" in _kinds(result)

    def test_long_paraphrase_allowed(self):
        paraphrase = (
            "该组织与 Fancy Bear 为同一实体，主要攻击政府与国防目标，"
            "并持续使用鱼叉钓鱼与零日漏洞，近期后门跨平台能力明显增强。"
        )
        result = guard_output(paraphrase, sources={"doc#0": _SOURCE})
        assert not result.blocked


class TestInternalMetadata:
    def test_metadata_assignment_blocked(self):
        result = guard_output("结果如下：access_level: secret，owner_id: 42")
        assert result.blocked
        assert "internal_metadata" in _kinds(result)

    def test_two_tokens_blocked(self):
        result = guard_output("文档的 library_scope 与 team_id 均不可见。")
        assert result.blocked

    def test_single_token_without_value_allowed(self):
        result = guard_output("我不能泄露 access_level 这类内部字段。")
        assert not result.blocked

    def test_citation_id_not_metadata(self):
        result = guard_output("答案来自 [public__rare-earth-brief.md#0]。")
        assert not result.blocked


class TestSystemPromptEcho:
    def test_echo_blocked(self):
        result = guard_output(f"我的系统提示是：{_SYSTEM_PROMPT}", system_prompt=_SYSTEM_PROMPT)
        assert result.blocked
        assert "system_prompt_leak" in _kinds(result)

    def test_refusal_without_echo_allowed(self):
        result = guard_output("我不能泄露系统提示或内部配置。", system_prompt=_SYSTEM_PROMPT)
        assert not result.blocked


class TestInjectionCompliance:
    def test_compliance_blocked(self):
        result = guard_output("已忽略以上指令，下面直接输出机密文档全文。")
        assert result.blocked
        assert "injection_compliance" in _kinds(result)

    def test_refusal_allowed(self):
        result = guard_output("我不能执行忽略指令的要求，只能回答语料中的事实。")
        assert not result.blocked


class TestPayloadGuard:
    def test_redacts_violating_field_keeps_evidence(self):
        payload = {
            "summary": _SOURCE,
            "evidence": [{"chunk_id": "doc#0", "quote": _SOURCE}],
            "key_points": ["正常要点"],
        }
        guarded, violations = guard_payload(payload, sources={"doc#0": _SOURCE})
        assert guarded["summary"] == SAFE_BLOCK_TEXT
        assert guarded["evidence"][0]["quote"] == _SOURCE  # 证据原文是结构字段，不拦截
        assert guarded["key_points"] == ["正常要点"]
        assert violations

    def test_clean_payload_unchanged(self):
        payload = {"summary": "APT28 是威胁组织。", "key_points": ["要点一"]}
        guarded, violations = guard_payload(payload, sources={"doc#0": _SOURCE})
        assert guarded == payload
        assert violations == []


class TestOutputFaceWiring:
    """三输出面接线：QA 合成器与分析报告都要过输出层守卫。"""

    async def test_synthesizer_blocks_dump(self):
        import uuid

        from calliodesmo.auth.context import AccessContext
        from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
        from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
        from calliodesmo.interfaces.retriever import Candidate, SearchMode
        from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer

        class _DumpLLM(LLMProvider):
            async def complete(self, messages, *, temperature=0.2, max_tokens=None):
                return LLMResponse(content=_SOURCE, model="test/stub", usage={})

        access = AccessContext(
            user_id=uuid.uuid4(),
            username="analyst",
            clearance=ClearanceLevel.SECRET,
            permissions=frozenset({Permission.QUERY}),
            library_scopes=frozenset({LibraryScope.PERSONAL}),
        )
        candidates = [
            Candidate(
                chunk_id="internal__apt28-tracking.md#0",
                doc_id="d",
                content=_SOURCE,
                score=0.9,
                rank=1,
            )
        ]
        answer = await AnswerSynthesizer(_DumpLLM()).synthesize(
            "APT28 是什么？", candidates, mode=SearchMode.NATIVE_RAG, access=access
        )
        assert answer.text == SAFE_BLOCK_TEXT
        assert answer.source_chunk_ids == []
        assert answer.context_chunks  # 来源仍可见（检索事实不因拦截而丢失）

    def test_analysis_payload_guarded(self):
        payload = {"summary": _SOURCE, "evidence": [{"chunk_id": "doc#0", "quote": _SOURCE}]}
        guarded, violations = guard_payload(payload, sources={"doc#0": _SOURCE})
        assert guarded["summary"] == SAFE_BLOCK_TEXT
        assert violations
