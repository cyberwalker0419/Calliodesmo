"""报告契约层：分析类型 / 状态枚举、证据模型、公共信封、9 类报告模型（P6 Task 4/5 冻结）。

本模块是所有下游（注册表 / 解析 / 评估 / 前端）共用的契约锚点：

- ``AnalysisType``：9 类分析（roadmap 对 P6 的一句话定义）；``interfaces/analysis.py``
  （Task 10）re-export 本枚举，不重复定义，保证注册表 / 解析 / 评估 / 前端共用同一锚点。
- ``AnalysisStatus``：ok / partial / failed 三值。持久化规则为仅 ok / partial 落报告行，
  完全失败走 job failed（落库口径见计划「AnalysisReportORM 表结构」，Task 12 消费）。
- ``Evidence``：证据引用（契约层 pydantic 形态），与引擎侧 dataclass ``EvidenceRef``
  一一对应互转（见架构节「信封装配」）。
- ``AnalysisEnvelope``：报告公共信封（九字段），与前端 ``types.ts`` 逐字段对齐；
  引擎产出 ``AnalysisReport``，worker 落库时补 ``generated_at`` 装配为本信封。
- 9 类报告模型（Task 5 一次性定义，契约完整、交付分批）：聚合形态
  （``SummaryReport`` / ``QAReport`` / ``CustomReport``）的置信与证据在顶层，
  条目形态（其余六类）的置信与证据在每条 item 上，均由 ``ConfidenceEvidenceBase``
  承载「0–1 区间校验 + 缺证据自动降置信」。第二批 3 类（关系映射 / 任务 / 概念）
  契约先立、接线留 Task 21（2026-W44）；``CustomReport`` 的注入防御留 Task 22。
"""

import enum
import re
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: 不可核验置信封顶：证据失配（``evidence.verify_evidence``）与缺证据自动降置信
#: （``ConfidenceEvidenceBase`` 校验器）共用该值；封顶取 min，原置信更低不上调。
#: 自报置信仅作排序 / 复核标记，校准（ECE）留痕移交 P8。
CONFIDENCE_CAP = 0.3


class AnalysisType(enum.StrEnum):
    """9 类分析任务类型（第一批 5 类 + 第二批 3 类 + 自定义，见计划决策 7）。"""

    SUMMARY = "summary"  # 摘要
    KEY_INFORMATION = "key_information"  # 关键信息
    TIMELINE = "timeline"  # 时间线
    ENTITY_RECOGNITION = "entity_recognition"  # 实体识别
    RELATION_MAPPING = "relation_mapping"  # 关系映射
    TASKS = "tasks"  # 任务（报告模型名 ActionItemReport，避免与 Job 混淆）
    CONCEPTS = "concepts"  # 概念
    QA = "qa"  # 问答
    CUSTOM = "custom"  # 自定义


class AnalysisStatus(enum.StrEnum):
    """报告状态：ok 正常 / partial 降级（部分抢救或证据失配超阈值）/ failed 完全失败。"""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class Evidence(BaseModel):
    """证据引用（契约层形态）：指向材料块的原文引文。

    与 ``interfaces/analysis.py`` 的 dataclass ``EvidenceRef(chunk_id, quote)`` 一一对应互转：
    引擎内部流转 ``EvidenceRef``、契约层用 ``Evidence``。``confidence`` 为契约层字段，
    不参与互转（转 ``EvidenceRef`` 时舍弃；自 ``EvidenceRef`` 转入时默认 1.0），
    证据失配时由 ``evidence.verify_evidence`` 封顶。
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(description="证据指向的材料块 ID")
    quote: str = Field(description="源文原文引文（去空白后必须为对应源文子串）")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="该条证据置信度（0–1）")

    @field_validator("chunk_id", "quote")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """非空校验：去空白后为空即拒绝（空白引文无证据价值）。"""
        if not value.strip():
            raise ValueError("不得为空或仅空白字符")
        return value

    @classmethod
    def from_ref(cls, ref: Any) -> "Evidence":
        """自引擎侧 ``EvidenceRef`` 互转（鸭子类型：带 ``chunk_id`` / ``quote`` 属性的对象）。

        鸭子类型使本方法在 ``interfaces/analysis.py``（Task 10）落地前即可离线单测；
        ``confidence`` 不参与互转，默认 1.0。
        """
        return cls(chunk_id=ref.chunk_id, quote=ref.quote)

    def to_ref(self) -> Any:
        """转为引擎侧 ``EvidenceRef``（dataclass，引擎内部流转）。

        ``interfaces/analysis.py`` 已于 P6 Task 10（2026-W39）冻结；此处运行时懒加载，
        避免契约层对可插拔抽象层的顶层依赖。
        """
        from calliodesmo.interfaces.analysis import EvidenceRef  # 懒加载：契约层不顶层依赖接口层

        return EvidenceRef(chunk_id=self.chunk_id, quote=self.quote)


class AnalysisEnvelope(BaseModel):
    """报告公共信封（九字段）：任何类型报告的统一出参形状。

    引擎产出 ``AnalysisReport`` 后，worker 落库时补 ``generated_at``（UTC now）装配为本信封；
    落库后 ORM ``created_at`` 与之一致，报告详情出参直接取信封。``payload`` 为对应类型
    报告模型的 ``model_dump()``（Task 5 冻结 9 类模型，按 ``task_type`` 判别）。
    """

    model_config = ConfigDict(extra="forbid")

    task_type: AnalysisType = Field(description="分析类型（9 类之一）")
    status: AnalysisStatus = Field(description="报告状态：ok / partial / failed")
    generated_at: datetime = Field(description="报告生成时刻（UTC，worker 落库时装配）")
    model: str = Field(description="生成所用模型名（运行记录）")
    prompt_version: str = Field(description="提示词版本（形如 <type>.v<version>，评估按版本切片）")
    usage: dict[str, int] = Field(description="token 用量（如 prompt_tokens / completion_tokens）")
    warnings: list[str] = Field(default_factory=list, description="降级与证据失配等告警（可读）")
    source_chunk_ids: list[str] = Field(
        default_factory=list, description="本次分析消费的材料块 ID 列表"
    )
    payload: dict[str, Any] = Field(
        description="对应类型报告模型的 model_dump（按 task_type 判别）"
    )


# ---------------------------------------------------------------------------
# 9 类报告模型（Task 5 冻结：契约完整、交付分批；扁平、键名语义化、每字段 description）
# ---------------------------------------------------------------------------


def _require_not_blank(value: str) -> str:
    """非空校验：去空白后为空即拒绝（核心字段缺失即无报告价值）。"""
    if not value.strip():
        raise ValueError("不得为空或仅空白字符")
    return value


class ConfidenceEvidenceBase(BaseModel):
    """置信 + 证据承载基类：聚合报告顶层与各报告条目共用该契约。

    自动降置信校验（契约层第一道闸）：``evidence`` 为空表示结论不可核验，
    ``confidence`` 封顶 ``CONFIDENCE_CAP``（取 min，原置信更低不上调）；
    证据引文失配的第二道闸由 ``evidence.verify_evidence`` 承担（失配同样封顶 +
    warning，失败占比 >30% 降 partial）。
    """

    model_config = ConfigDict(extra="forbid")

    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="置信度（0–1）；缺证据时自动降置信"
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="证据引用列表；空列表触发置信自动降低"
    )

    @model_validator(mode="after")
    def _lower_confidence_without_evidence(self) -> Self:
        """缺证据自动降置信：封顶不上调（原置信低于封顶值者保持）。"""
        if not self.evidence:
            self.confidence = min(self.confidence, CONFIDENCE_CAP)
        return self


class SummaryReport(ConfidenceEvidenceBase):
    """摘要报告（第一批）：全文摘要 + 要点列表。"""

    summary: str = Field(description="分析对象的全文摘要")
    key_points: list[str] = Field(default_factory=list, description="要点列表")

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class KeyInfoItem(ConfidenceEvidenceBase):
    """关键信息条目：label/value 对（如 时间 / 地点 / 当事方 / 金额）。"""

    label: str = Field(description="信息项名称")
    value: str = Field(description="信息项内容")

    @field_validator("label", "value")
    @classmethod
    def _core_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class KeyInfoReport(BaseModel):
    """关键信息报告（第一批）：label/value 条目集。"""

    model_config = ConfigDict(extra="forbid")

    items: list[KeyInfoItem] = Field(default_factory=list, description="关键信息条目列表")


class TimelineGranularity(enum.StrEnum):
    """时间线精度：exact 精确日期 / approximate 约略 / relative 相对。

    模糊时间（如「会后不久」）应落 ``relative`` 且 ``date_normalized`` 缺省，
    不得臆造精确日期（Task 6 模板指引锁定）。
    """

    EXACT = "exact"
    APPROXIMATE = "approximate"
    RELATIVE = "relative"


#: ISO 8601 宽松式样：允许 YYYY / YYYY-MM / YYYY-MM-DD，可选时间部分
#: （时:分[:秒[.小数]] 与可选时区）；月 / 日 / 时按历法范围约束（拒 2026-13-01 之类）。
_ISO_8601_RE = re.compile(
    r"\d{4}"
    r"(?:-(?:0[1-9]|1[0-2])"
    r"(?:-(?:0[1-9]|[12]\d|3[01]))?)?"
    r"(?:[T ](?:[01]\d|2[0-3]):[0-5]\d"
    r"(?::[0-5]\d(?:\.\d+)?)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?"
)


class TimelineEvent(ConfidenceEvidenceBase):
    """时间线条目：源文原始时间表述 + ISO 8601 归一化 + 精度。"""

    date_raw: str = Field(description="源文原始时间表述（如「上个月」/「2026年8月29日」）")
    date_normalized: str | None = Field(
        default=None,
        description="ISO 8601 归一化日期时间（宽松年/月精度）；relative 可缺省，其余必填",
    )
    granularity: TimelineGranularity = Field(description="时间精度：exact / approximate / relative")
    description: str = Field(default="", description="事件描述")

    @field_validator("date_raw")
    @classmethod
    def _date_raw_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)

    @field_validator("date_normalized")
    @classmethod
    def _iso_8601(cls, value: str | None) -> str | None:
        """ISO 8601 式样校验（宽松年 / 月精度，拒非法历法与非 ISO 格式）。"""
        if value is None:
            return None
        stripped = value.strip()
        if not _ISO_8601_RE.fullmatch(stripped):
            raise ValueError("必须为 ISO 8601 格式（YYYY / YYYY-MM / YYYY-MM-DD 可带时间部分）")
        return stripped

    @model_validator(mode="after")
    def _normalized_required_unless_relative(self) -> Self:
        """exact / approximate 必须给归一化日期（模糊时间应落 relative，不得臆造）。"""
        if self.granularity is not TimelineGranularity.RELATIVE and not self.date_normalized:
            raise ValueError("exact / approximate 必须提供 date_normalized（ISO 8601 归一化日期）")
        return self


class TimelineReport(BaseModel):
    """时间线报告（第一批）：时间线条目列表（叙述顺序由提示词约束）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[TimelineEvent] = Field(default_factory=list, description="时间线条目列表")


class RecognizedEntity(ConfidenceEvidenceBase):
    """实体识别条目：名称 / 类型 / 描述（图谱数据组织而来，不重新抽取）。"""

    name: str = Field(description="实体名称")
    type: str = Field(default="", description="实体类型（组织 / 人物 / 地点 / …）")
    description: str = Field(default="", description="实体描述")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class EntityRecognitionReport(BaseModel):
    """实体识别报告（第一批）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[RecognizedEntity] = Field(default_factory=list, description="实体条目列表")


class RelationItem(ConfidenceEvidenceBase):
    """关系映射条目：头 / 尾 / 类型 / 描述（图谱数据组织而来，不重新抽取）。"""

    head: str = Field(description="头实体名称")
    tail: str = Field(description="尾实体名称")
    type: str = Field(description="关系类型")
    description: str = Field(default="", description="关系描述")

    @field_validator("head", "tail", "type")
    @classmethod
    def _core_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class RelationMappingReport(BaseModel):
    """关系映射报告（第二批接线，契约先立；接线留 Task 21，2026-W44）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[RelationItem] = Field(default_factory=list, description="关系条目列表")


class ActionItem(ConfidenceEvidenceBase):
    """任务 / 行动条目：行动内容 + 源文责任方与期限原始表述。

    命名 ActionItem（而非 Task/Job）：避免与异步任务 ``Job``、分析 ``task_type`` 混淆。
    """

    action: str = Field(description="行动项内容")
    owner_raw: str = Field(default="", description="源文责任方原始表述（可缺失）")
    deadline_raw: str = Field(default="", description="源文期限原始表述（可缺失）")

    @field_validator("action")
    @classmethod
    def _action_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class ActionItemReport(BaseModel):
    """任务报告（「任务」类模型名避免与 Job 混淆；第二批接线，契约先立）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ActionItem] = Field(default_factory=list, description="行动条目列表")


class ConceptItem(ConfidenceEvidenceBase):
    """概念条目：名称 / 定义 / 相关概念。"""

    name: str = Field(description="概念名称")
    definition: str = Field(default="", description="概念定义")
    related: list[str] = Field(default_factory=list, description="相关概念名称列表")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class ConceptReport(BaseModel):
    """概念报告（第二批接线，契约先立；接线留 Task 21，2026-W44）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ConceptItem] = Field(default_factory=list, description="概念条目列表")


class QAReport(ConfidenceEvidenceBase):
    """问答报告（第一批）：引擎经 SearchEngine（见架构节），来源标注沿用
    ``answer_synthesizer`` 的 ``[chunk_id]`` 强制引注约定，空候选输出「无可引用证据」。"""

    question: str = Field(description="用户问题")
    answer: str = Field(description="答案正文（空候选输出「无可引用证据」）")
    citations: list[str] = Field(default_factory=list, description="引用的材料块 ID 列表")

    @field_validator("question", "answer")
    @classmethod
    def _core_not_blank(cls, value: str) -> str:
        return _require_not_blank(value)


class CustomReport(ConfidenceEvidenceBase):
    """自定义报告：fields 为用户 schema 驱动的开放字典。

    用户 schema/指令的 sanitize 与注入防御留 Task 22（2026-W44）。
    """

    fields: dict[str, Any] = Field(
        default_factory=dict, description="开放字段字典（用户自定义 schema 驱动）"
    )
