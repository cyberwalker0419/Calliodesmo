"""报告契约公共层：分析类型 / 状态枚举、证据模型、公共信封（P6 Task 4 冻结）。

本模块是所有下游（注册表 / 解析 / 评估 / 前端）共用的契约锚点：

- ``AnalysisType``：9 类分析（roadmap 对 P6 的一句话定义）；``interfaces/analysis.py``
  （Task 10）re-export 本枚举，不重复定义，保证注册表 / 解析 / 评估 / 前端共用同一锚点。
- ``AnalysisStatus``：ok / partial / failed 三值。持久化规则为仅 ok / partial 落报告行，
  完全失败走 job failed（落库口径见计划「AnalysisReportORM 表结构」，Task 12 消费）。
- ``Evidence``：证据引用（契约层 pydantic 形态），与引擎侧 dataclass ``EvidenceRef``
  一一对应互转（见架构节「信封装配」）。
- ``AnalysisEnvelope``：报告公共信封（九字段），与前端 ``types.ts`` 逐字段对齐；
  引擎产出 ``AnalysisReport``，worker 落库时补 ``generated_at`` 装配为本信封。
"""

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

        ``interfaces/analysis.py`` 由 Task 10（2026-W39）冻结，此处运行时懒加载；
        落地前调用抛 ``ModuleNotFoundError``（测试中显式留痕，落地后翻为互转断言）。
        """
        from calliodesmo.interfaces.analysis import EvidenceRef  # 懒加载：interfaces 尚未落地

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
