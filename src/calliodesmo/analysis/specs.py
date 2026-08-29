"""分析任务注册表：AnalysisType → 报告模型 / 模板 / 桩标记映射（P6 Task 5 冻结）。

注册表 / 解析 / 评估 / 前端渲染四方共用的契约锚点，类型无关：加类型 = 加一条
spec + 一份模板，引擎不改（见计划「注册表与提示词」）。

- ``BUILTIN_ANALYSIS_SPECS``：本批（Task 5）注册第一批 5 类；第二批 3 类
  （relation_mapping / tasks / concepts）接线留 Task 21（2026-W44）；
  ``custom`` 经 ``build_custom_spec`` 动态构造（Task 22）。
- ``get_spec``：未注册抛 ``KeyError``（API 层转 400）——未交付类型天然不可提交，
  无需额外开关。
"""

from dataclasses import dataclass

from pydantic import BaseModel

from calliodesmo.analysis.schemas import (
    AnalysisType,
    EntityRecognitionReport,
    KeyInfoReport,
    QAReport,
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


#: 内置规格注册表：本批注册第一批 5 类（契约完整、交付分批）；
#: 第二批 3 类追加留 Task 21（2026-W44）；custom 经 build_custom_spec（Task 22）。
BUILTIN_ANALYSIS_SPECS: dict[AnalysisType, AnalysisTaskSpec] = {
    spec.type: spec
    for spec in (
        _builtin(AnalysisType.SUMMARY, SummaryReport),
        _builtin(AnalysisType.KEY_INFORMATION, KeyInfoReport),
        _builtin(AnalysisType.TIMELINE, TimelineReport),
        _builtin(AnalysisType.ENTITY_RECOGNITION, EntityRecognitionReport),
        _builtin(AnalysisType.QA, QAReport),
    )
}


def get_spec(task_type: AnalysisType | str) -> AnalysisTaskSpec:
    """取指定分析类型的规格；未注册抛 ``KeyError``（API 层转 400）。

    接受枚举或其字符串值：非法类型字符串经枚举转换抛 ``ValueError``；
    合法但未注册的类型（第二批 3 类 / custom）抛 ``KeyError``——
    未交付类型天然不可提交。
    """
    key = AnalysisType(task_type)
    return BUILTIN_ANALYSIS_SPECS[key]


def build_custom_spec(instruction: str, schema: dict | None = None) -> AnalysisTaskSpec:
    """动态构造自定义分析规格（仅声明 / 占位，实现留 Task 22，2026-W44）。

    未竟：用户 schema sanitize（拒 $ref / 递归 / 超深 / 超大）+ JSON Schema 安全子集
    裁剪 + 指令注入防御 → P6 Task 22（2026-W44）；此前调用一律抛 ``NotImplementedError``。
    """
    raise NotImplementedError(
        "自定义分析规格构造为 P6 Task 22（2026-W44）范围："
        "需 sanitize_user_schema 与注入防御先行落地"
    )
