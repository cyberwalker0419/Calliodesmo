"""分析任务注册表：AnalysisType → 报告模型 / 模板 / 桩标记映射（P6 Task 5 冻结）。

注册表 / 解析 / 评估 / 前端渲染四方共用的契约锚点，类型无关：加类型 = 加一条
spec + 一份模板，引擎不改（见计划「注册表与提示词」）。

- ``BUILTIN_ANALYSIS_SPECS``：第一批 5 类（Task 5）+ 第二批 3 类
  （relation_mapping / tasks / concepts，Task 21 接线）+ ``custom``（Task 22 经
  ``build_custom_spec`` 动态构造后注册）= 9 类全注册。
- ``get_spec``：非法类型字符串经枚举转换抛 ``ValueError``（API 层转 400）。
"""

from dataclasses import dataclass

from pydantic import BaseModel

from calliodesmo.analysis.sanitize import sanitize_user_schema
from calliodesmo.analysis.schemas import (
    ActionItemReport,
    AnalysisType,
    ConceptReport,
    CustomReport,
    EntityRecognitionReport,
    KeyInfoReport,
    QAReport,
    RelationMappingReport,
    SummaryReport,
    TimelineReport,
)


@dataclass(frozen=True)
class AnalysisTaskSpec:
    """单一分析类型的规格：报告模型 + 模板 + 桩标记 + 重试预算。

    - ``template_name``：``config/analysis_prompts/`` 下的模板文件名（Task 6 落版本化模板）；
    - ``stub_marker``：系统提示中的 ``[ANALYSIS:<type>]`` 标记，StubLLM 分发锚点
      （Task 8 契约测试锁定，钉死「标记写错静默回退」的坑）；
    - ``max_retries``：None = 用全局 ``analysis_parse_retries`` 配置（可降 0 退化单次解析）。
    """

    type: AnalysisType
    output_cls: type[BaseModel]
    template_name: str
    stub_marker: str
    max_retries: int | None = None


def _builtin(task_type: AnalysisType, output_cls: type[BaseModel]) -> AnalysisTaskSpec:
    """内置规格构造：模板名与桩标记由类型值派生（命名约定锁定）。"""
    return AnalysisTaskSpec(
        type=task_type,
        output_cls=output_cls,
        template_name=f"{task_type.value}.txt",
        stub_marker=f"[ANALYSIS:{task_type.value}]",
    )


#: 内置规格注册表：第一批 5 类 + 第二批 3 类（关系映射 / 任务 / 概念）+
#: ``custom``（Task 22）= 9 类全注册（契约完整、交付分批）。
BUILTIN_ANALYSIS_SPECS: dict[AnalysisType, AnalysisTaskSpec] = {
    spec.type: spec
    for spec in (
        _builtin(AnalysisType.SUMMARY, SummaryReport),
        _builtin(AnalysisType.KEY_INFORMATION, KeyInfoReport),
        _builtin(AnalysisType.TIMELINE, TimelineReport),
        _builtin(AnalysisType.ENTITY_RECOGNITION, EntityRecognitionReport),
        _builtin(AnalysisType.QA, QAReport),
        _builtin(AnalysisType.RELATION_MAPPING, RelationMappingReport),
        _builtin(AnalysisType.TASKS, ActionItemReport),
        _builtin(AnalysisType.CONCEPTS, ConceptReport),
        _builtin(AnalysisType.CUSTOM, CustomReport),
    )
}


def get_spec(task_type: AnalysisType | str) -> AnalysisTaskSpec:
    """取指定分析类型的规格；非法类型字符串经枚举转换抛 ``ValueError``（API 层转 400）。

    接受枚举或其字符串值：9 类（含 ``custom``，Task 22）均已注册，合法类型恒可取到规格。
    """
    key = AnalysisType(task_type)
    return BUILTIN_ANALYSIS_SPECS[key]


def build_custom_spec(
    instruction: str, schema: dict | None = None, *, max_bytes: int | None = None
) -> AnalysisTaskSpec:
    """动态构造自定义分析规格（Task 22）：安全闸门 + 返回已注册的 custom 规格。

    职责（仅安全闸门）：

    - 校验 ``instruction`` 非空白（自定义指令必填）；
    - ``schema`` 非 ``None`` 时经 ``sanitize_user_schema`` 清洗（拒 ``$ref`` /
      递归 / 超深 / 超大 / 超字节），违规抛 ``SchemaSanitizeError``（API 层转 400）。

    返回 ``BUILTIN_ANALYSIS_SPECS`` 中已注册的 custom 规格（``CustomReport`` /
    ``custom.txt`` / ``[ANALYSIS:custom]``）——引擎经 ``get_spec`` 消费同一对象。
    ``instruction`` / ``schema`` 不进规格本身：二者经 ``AnalysisSpec`` 于渲染期注入，
    且只进 user 消息（与 system 隔离，见 ``prompts.render_prompt`` 与注入探针测试）。

    参数:
        instruction: 自定义分析指令（非空白，否则 ``ValueError``）。
        schema: 可选输出 schema；``None`` = 无结构约束。
        max_bytes: schema 序列化字节上限；``None`` = 用
            ``sanitize.DEFAULT_CUSTOM_SCHEMA_MAX_BYTES``（API 侧经 settings 显式传入）。

    异常:
        ValueError: ``instruction`` 为空白。
        SchemaSanitizeError: ``schema`` 未通过安全清洗。
    """
    if not instruction or not instruction.strip():
        raise ValueError("自定义分析指令不得为空（custom.instruction 必填，非空白）")
    if schema is not None:
        sanitize_user_schema(schema, max_bytes=max_bytes)
    return BUILTIN_ANALYSIS_SPECS[AnalysisType.CUSTOM]
