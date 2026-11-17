"""P9 Task 1：QA 答案后处理（模板前缀剥离 + 句级引注纪律）单测。"""

from __future__ import annotations

from calliodesmo.retrieval.answer_postprocess import (
    attach_sentence_citations,
    is_meta_sentence,
    strip_answer_boilerplate,
)

_SOURCES = {
    "c1": "APT28（又称 Fancy Bear）是疑似源自俄罗斯的威胁组织，长期针对政府与国防目标。",
    "c2": "镨钕氧化物报价小幅上行，主要受下游磁材需求拉动。",
}


class TestStripBoilerplate:
    def test_strips_context_preamble(self):
        assert (
            strip_answer_boilerplate("根据提供的上下文，APT28 是威胁组织。") == "APT28 是威胁组织。"
        )

    def test_strips_material_variants(self):
        for prefix in (
            "根据上下文，",
            "基于上述材料，",
            "依据所给资料：",
            "根据您提供的文档，",
            "参考检索结果，",
            "综上所述，",
            "总的来说，",
        ):
            assert strip_answer_boilerplate(prefix + "答案是 X。") == "答案是 X。"

    def test_idempotent(self):
        text = "根据提供的上下文，答案是 X。"
        once = strip_answer_boilerplate(text)
        assert strip_answer_boilerplate(once) == once

    def test_keeps_mid_sentence_context_phrase(self):
        text = "报告指出，根据上下文可知 APT28 长期活跃。"
        assert strip_answer_boilerplate(text) == text

    def test_empty_and_whitespace(self):
        assert strip_answer_boilerplate("   ") == ""
        assert strip_answer_boilerplate("") == ""


class TestAttachCitations:
    def test_attaches_when_supported(self):
        text, attachments = attach_sentence_citations("镨钕氧化物报价小幅上行。", _SOURCES)
        assert "[c2]" in text
        assert attachments and attachments[0]["chunk_id"] == "c2"

    def test_no_attach_when_unsupported(self):
        text, attachments = attach_sentence_citations("火星基地已经建成。", _SOURCES)
        assert text == "火星基地已经建成。"
        assert attachments == []

    def test_keeps_existing_valid_citation(self):
        text, attachments = attach_sentence_citations("APT28 是威胁组织 [c1]。", _SOURCES)
        assert text.count("[c1]") == 1
        assert attachments == []

    def test_removes_invalid_citation(self):
        text, _ = attach_sentence_citations("APT28 是威胁组织 [fake#0]。", _SOURCES)
        assert "fake" not in text
        assert "[c1]" in text

    def test_picks_best_chunk(self):
        sources = {
            "c1": "稀土市场保持平稳。",
            "c2": "镨钕氧化物报价小幅上行，主要受下游磁材需求拉动。",
        }
        _, attachments = attach_sentence_citations("镨钕氧化物报价小幅上行。", sources)
        assert attachments[0]["chunk_id"] == "c2"

    def test_skips_meta_sentence(self):
        text, attachments = attach_sentence_citations("以上信息仅供参考。", _SOURCES)
        assert attachments == []
        assert text == "以上信息仅供参考。"

    def test_preserves_newlines(self):
        text, _ = attach_sentence_citations("第一句无关。\n\n第二句无关。", _SOURCES)
        assert "\n\n" in text

    def test_deterministic(self):
        first = attach_sentence_citations("镨钕氧化物报价小幅上行。", _SOURCES)
        second = attach_sentence_citations("镨钕氧化物报价小幅上行。", _SOURCES)
        assert first == second


class TestMetaSentence:
    def test_meta_markers(self):
        assert is_meta_sentence("以上信息仅供参考。")
        assert is_meta_sentence("希望对你有帮助。")
        assert is_meta_sentence("如需更多信息，请告知。")

    def test_non_meta(self):
        assert not is_meta_sentence("APT28 是威胁组织。")
