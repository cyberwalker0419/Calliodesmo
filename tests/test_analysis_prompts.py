"""P6 Task 6 测试：提示词模板与构造（第一批 5 类 + 第二批 3 类，纯函数无夹具，CI 可覆盖）。

覆盖：
- ``{materials}`` / ``{question}`` / ``{schema}`` 令牌替换（材料最后替换，
  材料文本内的令牌字面量不会被二次替换）；
- 双闸预算在 render 侧执行（``analysis_max_chunks`` + ``analysis_max_input_chars``）：
  块数 / 字符边界恰等保留、超界截断、单块超预算裁剪首块（采集侧截断见 Task 9）；
- 版本号解析：模板首行 ``# version: N`` → ``prompt_version = "<type>.v<version>"``；
- 模板遵循 ``ecl/extractor.py`` 范式：系统角色声明 + 「严格只输出一个 JSON 对象」
  + 输出 schema 示例 + ``[ANALYSIS:<type>]`` StubLLM 分发锚点；
- 时间线模板含 ISO 8601 归一化 + 锚点换算 + 模糊时间落 ``relative`` 不得臆造精确日期；
- 关系映射模板含图谱复用口径（基于给定实体/关系数据组织、不重新抽取，Task 21）。
"""

import dataclasses
import json

import pytest

from calliodesmo.analysis.prompts import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_INPUT_CHARS,
    PromptTemplate,
    PromptTemplateError,
    RenderedPrompt,
    load_template,
    parse_template,
    render_prompt,
)
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.analysis.specs import get_spec

_FIRST_BATCH = [
    AnalysisType.SUMMARY,
    AnalysisType.KEY_INFORMATION,
    AnalysisType.TIMELINE,
    AnalysisType.ENTITY_RECOGNITION,
    AnalysisType.QA,
]

#: 第二批 3 类（关系映射 / 任务 / 概念，Task 21 接线）
_SECOND_BATCH = [
    AnalysisType.RELATION_MAPPING,
    AnalysisType.TASKS,
    AnalysisType.CONCEPTS,
]

_ALL_TEMPLATE_TYPES = _FIRST_BATCH + _SECOND_BATCH

#: 各模板输出 schema 示例应含的报告键（与 analysis/schemas.py 模型字段一致）
_SCHEMA_KEYS: dict[AnalysisType, tuple[str, ...]] = {
    AnalysisType.SUMMARY: ('"summary"', '"key_points"'),
    AnalysisType.KEY_INFORMATION: ('"items"', '"label"', '"value"'),
    AnalysisType.TIMELINE: ('"items"', '"date_raw"', '"date_normalized"', '"granularity"'),
    AnalysisType.ENTITY_RECOGNITION: ('"items"', '"name"', '"type"'),
    AnalysisType.QA: ('"question"', '"answer"', '"citations"'),
    AnalysisType.RELATION_MAPPING: ('"items"', '"head"', '"tail"', '"type"'),
    AnalysisType.TASKS: ('"items"', '"action"', '"owner_raw"', '"deadline_raw"'),
    AnalysisType.CONCEPTS: ('"items"', '"name"', '"definition"', '"related"'),
}

#: 合成模板（{schema} 令牌替换 / 版本解析 / 系统段替换等纯函数用例，不依赖文件）
_CUSTOM_TMPL = PromptTemplate(
    version=2,
    system="[ANALYSIS:custom] 你是自定义分析引擎。严格只输出一个 JSON 对象。",
    user="输出 schema：{schema}\n\n材料：{materials}",
)


@dataclasses.dataclass(frozen=True)
class _Material:
    """测试用材料替身：满足 Task 10 ``AnalysisMaterial`` 的鸭子类型形状（chunk_id / text）。"""

    chunk_id: str
    text: str


def _materials(count: int, width: int = 5) -> list[_Material]:
    """构造 count 条材料，每条文本长 2*width（i<10 时 ``x{i}`` 恒 2 字符）。"""
    assert count <= 10
    return [_Material(chunk_id=f"c{i}", text=f"x{i}" * width) for i in range(count)]


class TestParseTemplate:
    """parse_template：版本头 + SYSTEM/USER 分段（纯函数）。"""

    def test_parse_version_and_sections(self):
        raw = "# version: 3\n===SYSTEM===\n系统段内容\n===USER===\n用户段内容"
        template = parse_template(raw)
        assert template.version == 3
        assert template.system == "系统段内容"
        assert template.user == "用户段内容"

    @pytest.mark.parametrize(
        "raw",
        [
            "===SYSTEM===\n系统\n===USER===\n用户",  # 缺版本头
            "# version: abc\n===SYSTEM===\n系统\n===USER===\n用户",  # 版本非整数
            "#version 1\n===SYSTEM===\n系统\n===USER===\n用户",  # 版本头格式非法
        ],
    )
    def test_bad_version_header_raises(self, raw):
        with pytest.raises(PromptTemplateError, match="version"):
            parse_template(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            "# version: 1\n===SYSTEM===\n仅系统段",  # 缺 USER 段
            "# version: 1\n===USER===\n仅用户段",  # 缺 SYSTEM 段
            "# version: 1\n无分段内容",  # 两段皆缺
        ],
    )
    def test_missing_section_raises(self, raw):
        with pytest.raises(PromptTemplateError):
            parse_template(raw)


class TestLoadTemplate:
    """load_template：模板文件定位与读取。"""

    @pytest.mark.parametrize("task_type", _ALL_TEMPLATE_TYPES)
    def test_template_files_exist(self, task_type):
        """两批 8 类的模板文件按注册表 ``template_name`` 约定存在且版本为 1。"""
        spec = get_spec(task_type)
        assert spec.template_name == f"{task_type.value}.txt"
        template = load_template(spec.template_name)
        assert template.version == 1

    def test_missing_template_raises(self):
        with pytest.raises(PromptTemplateError):
            load_template("bogus.txt")

    def test_custom_template_dir(self, tmp_path):
        path = tmp_path / "demo.txt"
        path.write_text("# version: 9\n===SYSTEM===\ns\n===USER===\nu", encoding="utf-8")
        template = load_template("demo.txt", template_dir=tmp_path)
        assert template.version == 9
        assert (template.system, template.user) == ("s", "u")


class TestTemplateContracts:
    """实际模板文件遵循 ``ecl/extractor.py`` 范式（角色声明 + 单一 JSON + schema 示例）。"""

    @pytest.mark.parametrize("task_type", _ALL_TEMPLATE_TYPES)
    def test_extractor_paradigm(self, task_type):
        template = load_template(get_spec(task_type).template_name)
        system = template.system
        # 系统角色声明
        assert "你是" in system
        # StubLLM 分发锚点（契约测试锁定，Task 8 消费）
        assert get_spec(task_type).stub_marker in system
        # 「严格只输出一个 JSON 对象」
        assert "严格只输出一个 JSON 对象" in system
        # 输出 schema 示例（JSON 花括号 + 证据纪律键）
        assert "{" in system and "}" in system
        assert "evidence" in system

    @pytest.mark.parametrize("task_type", _ALL_TEMPLATE_TYPES)
    def test_output_schema_keys_match_report_model(self, task_type):
        """schema 示例键与 analysis/schemas.py 对应报告模型字段一致。"""
        template = load_template(get_spec(task_type).template_name)
        for key in _SCHEMA_KEYS[task_type]:
            assert key in template.system

    @pytest.mark.parametrize("task_type", _ALL_TEMPLATE_TYPES)
    def test_user_section_has_materials_token(self, task_type):
        template = load_template(get_spec(task_type).template_name)
        assert "{materials}" in template.user

    def test_qa_user_section_has_question_token(self):
        template = load_template("qa.txt")
        assert "{question}" in template.user


class TestTimelineTemplateGuidance:
    """时间线模板：ISO 8601 归一化 + 锚点换算 + 模糊时间落 relative 不得臆造。"""

    def test_timeline_guidance(self):
        template = load_template("timeline.txt")
        system = template.system
        assert "ISO 8601" in system  # 归一化格式
        assert "锚点" in system  # 相对时间表述按材料时间锚点换算
        assert "relative" in system  # 模糊时间落 relative
        assert "臆造" in system  # 不得臆造精确日期


class TestRelationMappingTemplateGuidance:
    """关系映射模板：图谱复用口径——基于给定实体/关系数据组织，不重新抽取。"""

    def test_relation_mapping_graph_reuse_guidance(self):
        template = load_template("relation_mapping.txt")
        system = template.system
        assert "实体" in system and "关系" in system  # 面向实体/关系数据
        assert "组织" in system  # LLM 只组织
        assert "抽取" in system  # 「不重新抽取」口径出现
        assert "不" in system  # 否定式约束（不新造 / 不重新抽取）

    def test_relation_mapping_schema_example_head_tail(self):
        """schema 示例含 head / tail / type / description 四键（对齐 RelationItem）。"""
        template = load_template("relation_mapping.txt")
        for key in ('"head"', '"tail"', '"type"', '"description"'):
            assert key in template.system

    def test_tasks_and_concepts_schema_examples(self):
        """任务 / 概念模板的 schema 示例对齐各自报告模型字段。"""
        tasks = load_template("tasks.txt")
        for key in ('"action"', '"owner_raw"', '"deadline_raw"'):
            assert key in tasks.system
        concepts = load_template("concepts.txt")
        for key in ('"name"', '"definition"', '"related"'):
            assert key in concepts.system


class TestRenderPromptTokens:
    """render_prompt：{materials} / {question} / {schema} 令牌替换。"""

    def test_materials_token_replaced(self):
        template = load_template("summary.txt")
        rendered = render_prompt(template, AnalysisType.SUMMARY, materials=_materials(2))
        assert "{materials}" not in rendered.user
        assert "[chunk_id=c0]\nx0x0x0x0x0" in rendered.user
        assert "[chunk_id=c1]\nx1x1x1x1x1" in rendered.user

    def test_empty_materials_placeholder(self):
        rendered = render_prompt(load_template("summary.txt"), AnalysisType.SUMMARY)
        assert "{materials}" not in rendered.user
        assert "(无材料)" in rendered.user
        assert rendered.included_chunk_ids == ()

    def test_question_token_replaced_in_qa(self):
        rendered = render_prompt(
            load_template("qa.txt"), AnalysisType.QA, question="项目何时立项？"
        )
        assert "{question}" not in rendered.user
        assert "项目何时立项？" in rendered.user

    def test_question_unused_by_non_qa_templates(self):
        rendered = render_prompt(
            load_template("summary.txt"), AnalysisType.SUMMARY, question="不应出现的问题"
        )
        assert "不应出现的问题" not in rendered.system
        assert "不应出现的问题" not in rendered.user

    def test_schema_token_replaced(self):
        schema = {"type": "object", "字段": "值"}
        rendered = render_prompt(_CUSTOM_TMPL, "summary", schema=schema)
        assert "{schema}" not in rendered.user
        assert json.dumps(schema, ensure_ascii=False) in rendered.user

    def test_schema_token_defaults_placeholder(self):
        rendered = render_prompt(_CUSTOM_TMPL, "summary")
        assert "(无)" in rendered.user

    def test_tokens_in_system_section_also_replaced(self):
        template = PromptTemplate(version=1, system="S:{question}", user="U:{question}")
        rendered = render_prompt(template, "summary", question="q1")
        assert rendered.system == "S:q1"
        assert rendered.user == "U:q1"

    def test_material_text_tokens_not_resubstituted(self):
        """材料最后替换：材料文本内的令牌字面量不被二次替换（注入边界）。"""
        rendered = render_prompt(
            _CUSTOM_TMPL,
            "summary",
            materials=[_Material("c1", "含有 {question} 与 {schema} 字面量")],
            question="真实问题",
        )
        assert "含有 {question} 与 {schema} 字面量" in rendered.user
        assert "真实问题" not in rendered.user


class TestInstructionTokenIsolation:
    """``{instruction}`` 令牌（Task 22）：自定义指令只进 user 消息，与 system 隔离。"""

    def test_instruction_token_replaced_in_user(self):
        rendered = render_prompt(
            load_template("custom.txt"), AnalysisType.CUSTOM, instruction="提取风险点"
        )
        assert "{instruction}" not in rendered.user
        assert "提取风险点" in rendered.user

    def test_instruction_not_substituted_into_system(self):
        """结构性隔离：即便模板 system 段误含 {instruction}，指令值也不进 system。"""
        template = PromptTemplate(
            version=1,
            system="[ANALYSIS:custom] S:{instruction}",
            user="U:{instruction}",
        )
        rendered = render_prompt(template, AnalysisType.CUSTOM, instruction="越权载荷")
        assert "越权载荷" in rendered.user
        assert "越权载荷" not in rendered.system
        # system 段的令牌被清除而非泄露指令内容
        assert "{instruction}" not in rendered.system

    def test_real_custom_template_instruction_only_in_user(self):
        """真实 custom.txt：{instruction} 仅存在于 user 段（与 system 隔离）。"""
        template = load_template("custom.txt")
        assert "{instruction}" in template.user
        assert "{instruction}" not in template.system

    def test_empty_instruction_leaves_no_token(self):
        rendered = render_prompt(load_template("custom.txt"), AnalysisType.CUSTOM)
        assert "{instruction}" not in rendered.user
        assert "{instruction}" not in rendered.system


class TestRenderPromptVersion:
    """prompt_version = "<type>.v<version>"（运行记录，评估按版本切片）。"""

    @pytest.mark.parametrize("task_type", _ALL_TEMPLATE_TYPES)
    def test_prompt_version_from_file_templates(self, task_type):
        template = load_template(get_spec(task_type).template_name)
        rendered = render_prompt(template, task_type, materials=_materials(1))
        assert rendered.prompt_version == f"{task_type.value}.v1"

    def test_prompt_version_accepts_str_type_and_custom_version(self):
        rendered = render_prompt(_CUSTOM_TMPL, "summary")
        assert rendered.prompt_version == "summary.v2"

    def test_invalid_task_type_raises(self):
        with pytest.raises(ValueError):
            render_prompt(_CUSTOM_TMPL, "bogus")

    def test_rendered_prompt_field_contract(self):
        assert {field.name for field in dataclasses.fields(RenderedPrompt)} == {
            "system",
            "user",
            "prompt_version",
            "included_chunk_ids",
        }

    def test_rendered_prompt_frozen(self):
        rendered = render_prompt(load_template("summary.txt"), AnalysisType.SUMMARY)
        with pytest.raises(dataclasses.FrozenInstanceError):
            rendered.prompt_version = "x"


class TestRenderBudget:
    """双闸预算在 render 侧执行（analysis_max_chunks + analysis_max_input_chars）。"""

    def test_defaults_mirror_settings(self):
        """默认预算与 config.py Settings 默认值一致（引擎侧经 settings 显式传入）。"""
        assert DEFAULT_MAX_CHUNKS == 40
        assert DEFAULT_MAX_INPUT_CHARS == 24000

    def test_chunk_gate_boundary_keeps_all(self):
        materials = _materials(5)
        rendered = render_prompt(
            load_template("summary.txt"), AnalysisType.SUMMARY, materials=materials, max_chunks=5
        )
        assert rendered.included_chunk_ids == ("c0", "c1", "c2", "c3", "c4")

    def test_chunk_gate_truncates_in_order(self):
        materials = _materials(5)
        rendered = render_prompt(
            load_template("summary.txt"), AnalysisType.SUMMARY, materials=materials, max_chunks=3
        )
        assert rendered.included_chunk_ids == ("c0", "c1", "c2")
        assert "[chunk_id=c3]" not in rendered.user

    def test_char_gate_boundary_keeps_all(self):
        """总字符恰等于预算：全部保留（边界含等号）。"""
        materials = _materials(3, width=5)  # 每条 10 字符，共 30
        rendered = render_prompt(
            load_template("summary.txt"),
            AnalysisType.SUMMARY,
            materials=materials,
            max_input_chars=30,
        )
        assert rendered.included_chunk_ids == ("c0", "c1", "c2")

    def test_char_gate_truncates_at_chunk_boundary(self):
        materials = _materials(3, width=5)  # 每条 10 字符
        rendered = render_prompt(
            load_template("summary.txt"),
            AnalysisType.SUMMARY,
            materials=materials,
            max_input_chars=25,
        )
        assert rendered.included_chunk_ids == ("c0", "c1")
        assert "[chunk_id=c2]" not in rendered.user

    def test_single_oversized_chunk_truncated_to_budget(self):
        """首块单独超预算：裁剪首块文本至预算（render 侧成本闸兜底）。"""
        materials = [_Material("c0", "y" * 50)]
        rendered = render_prompt(
            load_template("summary.txt"),
            AnalysisType.SUMMARY,
            materials=materials,
            max_input_chars=20,
        )
        assert rendered.included_chunk_ids == ("c0",)
        assert "y" * 20 in rendered.user
        assert "y" * 21 not in rendered.user

    def test_char_gate_dominates_when_tighter(self):
        materials = _materials(8, width=50)  # 每条 100 字符
        rendered = render_prompt(
            load_template("summary.txt"),
            AnalysisType.SUMMARY,
            materials=materials,
            max_chunks=8,
            max_input_chars=250,
        )
        assert rendered.included_chunk_ids == ("c0", "c1")

    def test_max_chunks_zero_yields_placeholder(self):
        rendered = render_prompt(
            load_template("summary.txt"),
            AnalysisType.SUMMARY,
            materials=_materials(3),
            max_chunks=0,
        )
        assert rendered.included_chunk_ids == ()
        assert "(无材料)" in rendered.user

    def test_default_chunk_gate_applies(self):
        """不传预算用默认值：41 条材料被默认块数闸截到 40。"""
        materials = _materials(10) + [_Material(chunk_id=f"d{i}", text="z") for i in range(31)]
        rendered = render_prompt(
            load_template("summary.txt"), AnalysisType.SUMMARY, materials=materials
        )
        assert len(rendered.included_chunk_ids) == 40
