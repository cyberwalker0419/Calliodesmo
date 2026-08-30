"""P6 Task 16 测试：分析 golden 集加载 + 字段 / 元组级 P-R-F1（确定性硬指标）。

离线证据只承诺结构 / 契约：``field_f1`` / ``tuple_f1`` 为确定性纯函数（手算样例：
空预测 / 全命中 / 部分命中 / 双向匹配边界）；``config/golden_analysis.yaml`` 第一批
5 类 × 每类 2 例 + 第二批 3 类（关系映射 / 任务 / 概念，Task 21 补入）小金标，复用
``data/demo`` 三件语料同源材料（chunk_id 前缀约定与 ``config/golden_qa.yaml`` 一致）。
QA 类 ``expected_answer`` 自 P2 以来首次被指标消费，``expected_answer`` 为空跳过该指标。
分析质量证据由 ``scripts/eval_p6.py --real`` 承担（Task 17/23，锚点 2026-W45），
本测试不表述为「分析质量好」。
"""

from collections.abc import Sequence
from pathlib import Path

from calliodesmo.eval.golden_analysis import GoldenAnalysisCase, load_golden_analysis
from calliodesmo.eval.metrics_analysis import PRF1, answer_field_pair, field_f1, tuple_f1

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FILE = REPO_ROOT / "config" / "golden_analysis.yaml"

#: 第一批 5 类（Task 5/6 已冻结契约）
FIRST_BATCH_TYPES = ("summary", "key_information", "timeline", "entity_recognition", "qa")
#: 第二批 3 类（Task 21 接线；custom 无固定金标，不在本 golden 集）
SECOND_BATCH_TYPES = ("relation_mapping", "tasks", "concepts")


class TestLoadGoldenAnalysis:
    def test_missing_file_returns_empty(self):
        assert load_golden_analysis("nonexistent.yaml") == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        assert load_golden_analysis(f) == []

    def test_no_cases_key_returns_empty(self, tmp_path):
        f = tmp_path / "nocases.yaml"
        f.write_text("version: 1\n", encoding="utf-8")
        assert load_golden_analysis(f) == []

    def test_minimal_case_parses(self, tmp_path):
        f = tmp_path / "one.yaml"
        f.write_text(
            """
cases:
  - case_id: "qa-x"
    task_type: "qa"
    question: "Q?"
    expected_answer: "A"
""",
            encoding="utf-8",
        )
        cases = load_golden_analysis(f)
        assert len(cases) == 1
        c = cases[0]
        assert isinstance(c, GoldenAnalysisCase)
        assert c.case_id == "qa-x"
        assert c.task_type == "qa"
        assert c.question == "Q?"
        assert c.expected_answer == "A"
        # 缺省字段
        assert c.doc_ids == []
        assert c.relevant_chunk_ids == []
        assert c.expected_fields == []
        assert c.expected_tuples == []

    def test_fields_and_tuples_parse(self, tmp_path):
        f = tmp_path / "full.yaml"
        f.write_text(
            """
cases:
  - case_id: "ki"
    task_type: "key_information"
    doc_ids: ["d.md"]
    expected_fields:
      - label: "供应方"
        value: "北方稀土"
      - "纯量要点"
    expected_tuples:
      - ["组织", "北方稀土"]
""",
            encoding="utf-8",
        )
        c = load_golden_analysis(f)[0]
        assert c.doc_ids == ["d.md"]
        assert c.expected_fields[0] == {"label": "供应方", "value": "北方稀土"}
        assert c.expected_fields[1] == "纯量要点"
        assert c.expected_tuples == [("组织", "北方稀土")]

    def test_real_golden_two_batches_structure(self):
        from collections import Counter

        cases = load_golden_analysis(GOLDEN_FILE)
        counts = Counter(c.task_type for c in cases)
        # 第一批 5 类 + 第二批 3 类（关系映射 / 任务 / 概念，Task 21 补入）
        assert set(counts) == set(FIRST_BATCH_TYPES) | set(SECOND_BATCH_TYPES)
        for t in FIRST_BATCH_TYPES:
            assert counts[t] == 2  # 第一批每类恰 2 例
        # 第二批：关系映射 / 任务各 2 例、概念 1 例（每类 1–2 例口径）
        assert counts["relation_mapping"] == 2
        assert counts["tasks"] == 2
        assert counts["concepts"] == 1
        assert len(cases) == 15
        assert all(c.case_id for c in cases)
        assert all(c.doc_ids for c in cases)  # 每条都有材料范围

    def test_real_golden_second_batch_metric_shapes(self):
        """第二批金标形状：关系映射三元组、任务 / 概念字段条目（对齐确定性指标入参）。"""
        cases = {c.case_id: c for c in load_golden_analysis(GOLDEN_FILE)}
        rel = cases["relation-mapping-rare-earth"]
        assert rel.expected_tuples and all(len(t) == 3 for t in rel.expected_tuples)
        tasks = cases["tasks-rare-earth"]
        assert tasks.expected_fields and all(isinstance(f, dict) for f in tasks.expected_fields)
        assert any("action" in f for f in tasks.expected_fields)
        concepts = cases["concepts-apt28"]
        assert concepts.expected_fields and all("name" in f for f in concepts.expected_fields)

    def test_real_golden_qa_has_expected_answer(self):
        cases = load_golden_analysis(GOLDEN_FILE)
        qa = [c for c in cases if c.task_type == "qa"]
        assert len(qa) == 2
        assert all(c.question for c in qa)
        assert all(c.expected_answer for c in qa)  # QA 类 expected_answer 落地

    def test_default_path_consumes_settings(self, tmp_path, monkeypatch):
        from calliodesmo.config import get_settings

        f = tmp_path / "ga.yaml"
        f.write_text('cases:\n  - case_id: "x"\n    task_type: "summary"\n', encoding="utf-8")
        monkeypatch.setenv("CALLIODESMO_EVAL_ANALYSIS_GOLDEN_FILE", str(f))
        get_settings.cache_clear()
        try:
            cases = load_golden_analysis()  # path=None -> 消费 Settings 配置
            assert [c.case_id for c in cases] == ["x"]
        finally:
            get_settings.cache_clear()


class TestFieldF1:
    def test_both_empty_is_perfect(self):
        assert field_f1([], []) == PRF1(1.0, 1.0, 1.0)

    def test_empty_prediction_all_zero(self):
        r = field_f1([{"label": "供应方", "value": "北方稀土"}], [])
        assert r == PRF1(0.0, 0.0, 0.0)

    def test_full_hit(self):
        exp = [{"label": "供应方", "value": "北方稀土"}]
        pred = [{"label": "供应方", "value": "北方稀土"}]
        assert field_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)

    def test_normalization_case_and_whitespace(self):
        exp = [{"label": "地点", "value": "内蒙古包头"}]
        pred = [{"label": "地点", "value": " 内蒙古包头 "}]
        assert field_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)
        # 大小写不敏感
        assert field_f1([{"v": "Zebrocy"}], [{"v": "zebrocy"}]) == PRF1(1.0, 1.0, 1.0)

    def test_partial_hit(self):
        exp = [
            {"label": "主要供应商", "value": "北方稀土与盛和资源"},
            {"label": "镨钕氧化物用途", "value": "制造钕铁硼永磁材料"},
        ]
        pred = [{"label": "主要供应商", "value": "北方稀土与盛和资源"}]
        r = field_f1(exp, pred)
        assert r.precision == 1.0
        assert r.recall == 0.5
        assert r.f1 == round(2 / 3, 4)

    def test_scalar_items(self):
        # 摘要 key_points 等纯字符串条目按规范化单值参与匹配
        exp = ["镨钕氧化物报价小幅上行", "北方稀土是主要供应商"]
        pred = ["北方稀土是主要供应商"]
        r = field_f1(exp, pred)
        assert r.precision == 1.0
        assert r.recall == 0.5

    def test_dict_key_order_irrelevant(self):
        exp = [{"label": "a", "value": "b"}]
        pred = [{"value": "b", "label": "a"}]
        assert field_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)


class TestTupleF1:
    def test_both_empty_is_perfect(self):
        assert tuple_f1([], []) == PRF1(1.0, 1.0, 1.0)

    def test_empty_prediction_all_zero(self):
        r = tuple_f1([("组织", "北方稀土")], [])
        assert r == PRF1(0.0, 0.0, 0.0)

    def test_full_hit(self):
        exp = [("组织", "北方稀土"), ("人物", "张明")]
        pred = [("组织", "北方稀土"), ("人物", "张明")]
        assert tuple_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)

    def test_normalization(self):
        exp = [("组织", "北方稀土")]
        pred = [(" 组织 ", " 北方稀土 ")]
        assert tuple_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)

    def test_partial_hit(self):
        exp = [("组织", "北方稀土"), ("组织", "盛和资源"), ("人物", "张明")]
        pred = [("组织", "北方稀土"), ("人物", "张明")]
        r = tuple_f1(exp, pred)
        assert r.precision == 1.0
        assert r.recall == round(2 / 3, 4)
        assert r.f1 == 0.8

    def test_extra_prediction_lowers_precision(self):
        # 双向匹配：多出金标外的元组压低 precision（幻觉惩罚）
        exp = [("组织", "北方稀土")]
        pred = [("组织", "北方稀土"), ("组织", "虚构实体")]
        r = tuple_f1(exp, pred)
        assert r.precision == 0.5
        assert r.recall == 1.0
        assert r.f1 == round(2 / 3, 4)

    def test_tuple_order_matters(self):
        # (类型, 头, 尾) 有向：头尾颠倒不算命中
        exp = [("隶属", "夜莺", "张三")]
        pred = [("隶属", "张三", "夜莺")]
        assert tuple_f1(exp, pred) == PRF1(0.0, 0.0, 0.0)

    def test_mixed_arity(self):
        # 实体 (类型, 名) 与关系 (类型, 头, 尾) 可同集比较
        exp = [("组织", "夜莺"), ("隶属", "夜莺", "张三")]
        pred = [("组织", "夜莺")]
        r = tuple_f1(exp, pred)
        assert r.precision == 1.0
        assert r.recall == 0.5


class TestAnswerFieldPair:
    def test_empty_expected_answer_skips(self):
        assert answer_field_pair("", "任意答案") is None
        assert answer_field_pair("   ", "任意答案") is None

    def test_nonempty_returns_field_inputs(self):
        pair = answer_field_pair("内蒙古包头", "内蒙古包头")
        assert pair is not None
        exp, pred = pair
        assert isinstance(exp, Sequence) and isinstance(pred, Sequence)
        assert field_f1(exp, pred) == PRF1(1.0, 1.0, 1.0)

    def test_mismatched_answer_zero(self):
        pair = answer_field_pair("内蒙古包头", "北京")
        assert pair is not None
        exp, pred = pair
        assert field_f1(exp, pred) == PRF1(0.0, 0.0, 0.0)
