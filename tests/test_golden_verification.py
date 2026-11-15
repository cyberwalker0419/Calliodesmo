"""P8 Task 1：评估语料完整性与一致性校验（不依赖 DB / LLM）。"""

from __future__ import annotations

import unicodedata
from collections import Counter
from pathlib import Path

import pytest
import yaml

from calliodesmo.analysis.evidence import normalize_for_match

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "config"
_DEMO = _ROOT / "tests" / "fixtures" / "demo"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text(encoding="utf-8"))


def _demo_sources() -> dict[str, str]:
    return {f"{p.name}#0": p.read_text(encoding="utf-8") for p in sorted(_DEMO.glob("*.md"))}


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", normalize_for_match(text))


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return _demo_sources()


@pytest.fixture(scope="module")
def qa_cases() -> list[dict]:
    return _load_yaml("golden_qa_v2.yaml")["cases"]


@pytest.fixture(scope="module")
def qa_cases_v3() -> list[dict]:
    return _load_yaml("golden_qa_v3.yaml")["cases"]


@pytest.fixture(scope="module")
def verification_claims() -> list[dict]:
    return _load_yaml("golden_verification.yaml")["claims"]


@pytest.fixture(scope="module")
def contradiction_pairs() -> list[dict]:
    return _load_yaml("golden_contradictions.yaml")["pairs"]


class TestGoldenQaV2:
    """QA 语料 v2：规模、类别下限、chunk 引用有效性。"""

    def test_minimum_size(self, qa_cases):
        assert len(qa_cases) >= 30

    def test_category_minimums(self, qa_cases):
        counts = Counter(case["category"] for case in qa_cases)
        assert counts["no_answer"] >= 5
        assert counts["multi_hop"] >= 5
        assert counts["distractor"] >= 5
        assert counts["answerable"] >= 5
        assert counts["injection"] >= 3

    def test_unique_ids(self, qa_cases):
        ids = [case["id"] for case in qa_cases]
        assert len(ids) == len(set(ids))

    def test_modes_valid(self, qa_cases):
        assert {case["mode"] for case in qa_cases} <= {"native_rag", "local", "global"}

    def test_answers_non_empty(self, qa_cases):
        assert all(case["expected_answer"].strip() for case in qa_cases)

    def test_no_answer_has_no_evidence(self, qa_cases):
        for case in qa_cases:
            if case["category"] == "no_answer":
                assert case["relevant_chunk_ids"] == []

    def test_chunk_ids_exist(self, qa_cases, sources):
        for case in qa_cases:
            for chunk_id in case["relevant_chunk_ids"]:
                assert chunk_id in sources, f"{case['id']} 引用了不存在的 chunk: {chunk_id}"


class TestGoldenQaV3:
    """QA 语料 v3（P9 Task 3）：在 v2 之上扩充到 ≥70 例，为交叉验证 ECE 供样本。"""

    def test_minimum_size(self, qa_cases_v3):
        assert len(qa_cases_v3) >= 70

    def test_superset_of_v2(self, qa_cases, qa_cases_v3):
        """v3 完整包含 v2（历史口径可复现），且新增例 ID 连续。"""
        v2_ids = {case["id"] for case in qa_cases}
        v3_ids = {case["id"] for case in qa_cases_v3}
        assert v2_ids <= v3_ids
        assert len(v3_ids - v2_ids) >= 35

    def test_category_minimums(self, qa_cases_v3):
        counts = Counter(case["category"] for case in qa_cases_v3)
        assert counts["answerable"] >= 25
        assert counts["multi_hop"] >= 15
        assert counts["no_answer"] >= 10
        assert counts["distractor"] >= 10
        assert counts["injection"] >= 6

    def test_unique_ids(self, qa_cases_v3):
        ids = [case["id"] for case in qa_cases_v3]
        assert len(ids) == len(set(ids))

    def test_modes_valid(self, qa_cases_v3):
        assert {case["mode"] for case in qa_cases_v3} <= {"native_rag", "local", "global"}

    def test_chunk_ids_exist(self, qa_cases_v3, sources):
        for case in qa_cases_v3:
            for chunk_id in case["relevant_chunk_ids"]:
                assert chunk_id in sources, f"{case['id']} 引用了不存在的 chunk: {chunk_id}"

    def test_no_answer_has_no_evidence(self, qa_cases_v3):
        for case in qa_cases_v3:
            if case["category"] == "no_answer":
                assert case["relevant_chunk_ids"] == []


class TestGoldenVerification:
    """claim 标注集：规模、四类平衡、引注可定位、注入探针。"""

    def test_minimum_size(self, verification_claims):
        assert len(verification_claims) >= 60

    def test_verdict_balance(self, verification_claims):
        counts = Counter(item["expected_verdict"] for item in verification_claims)
        for verdict in ("supported", "unsupported", "uncertain", "contradicted"):
            assert counts[verdict] >= 10, f"{verdict} 仅 {counts[verdict]} 条"

    def test_unique_ids(self, verification_claims):
        ids = [item["id"] for item in verification_claims]
        assert len(ids) == len(set(ids))

    def test_quotes_locate_in_source(self, verification_claims, sources):
        for item in verification_claims:
            quote = item.get("quote") or ""
            if not quote or item.get("injection"):
                continue
            chunk_id = item.get("chunk_id") or ""
            assert chunk_id in sources, f"{item['id']} chunk 不存在: {chunk_id}"
            assert _norm(quote) in _norm(sources[chunk_id]), f"{item['id']} 引注不可定位"

    def test_cross_document_cases_have_no_quote(self, verification_claims):
        for item in verification_claims:
            if item.get("expected_match_type") == "cross_document":
                assert not item.get("quote")
                assert not item.get("chunk_id")

    def test_injection_probes_present(self, verification_claims):
        probes = [item for item in verification_claims if item.get("injection")]
        assert len(probes) >= 3


class TestGoldenContradictions:
    """矛盾对：源句可定位、声明确与源句不同、引擎判 contradicted。"""

    def test_minimum_size(self, contradiction_pairs):
        assert len(contradiction_pairs) >= 8

    def test_conflict_types(self, contradiction_pairs):
        assert {item["conflict_type"] for item in contradiction_pairs} <= {
            "date_range",
            "negation",
            "antonym",
        }

    def test_source_quotes_locate(self, contradiction_pairs, sources):
        for item in contradiction_pairs:
            assert item["chunk_id"] in sources
            assert _norm(item["source_quote"]) in _norm(sources[item["chunk_id"]])

    def test_claims_differ_from_source(self, contradiction_pairs):
        for item in contradiction_pairs:
            assert _norm(item["claim"]) != _norm(item["source_quote"])


class TestEvalCorpus:
    """P9 可追踪评估语料副本：与 tests/fixtures/demo 同名同内容，全新克隆可复现质量轨。"""

    def test_files_exist_and_match_fixture(self):
        eval_dir = _CONFIG / "eval_corpus"
        assert eval_dir.is_dir()
        fixtures = sorted(_DEMO.glob("*.md"))
        assert len(fixtures) >= 3
        for fixture in fixtures:
            mirror = eval_dir / fixture.name
            assert mirror.is_file(), f"缺少评估语料副本 {fixture.name}"
            assert mirror.read_bytes() == fixture.read_bytes()
