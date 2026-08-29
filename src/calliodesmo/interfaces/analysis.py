"""分析引擎对外契约：AnalysisType / AnalysisMaterial / AnalysisSpec / EvidenceRef /
AnalysisReport / AnalysisEngine（P6 Task 10 冻结；与 LLMProvider / VectorStore 并列的可插拔抽象）。

形状按 [[docs/plans/phases/P6-llm-analysis-tasks|P6 计划]] 架构节冻结（dataclass 全 frozen）：

- ``AnalysisType``：re-export 自 ``analysis/schemas.py``（Task 5 先例：注册表 / 解析 /
  评估 / 前端共用单一契约锚点，不重复定义）；
- ``AnalysisMaterial``：re-export 自 ``analysis/materials.py``（Task 9 已定义引擎侧
  材料形态，不重复定义）；
- ``AnalysisSpec`` / ``EvidenceRef`` / ``AnalysisReport`` / ``AnalysisEngine``：本模块定义。

**材料装配不进引擎**：worker 负责 ``gather_materials``（含 ``visible_to``），引擎只吃
已过滤材料——保引擎纯逻辑可测；``access`` 入参供 QA 类 ``SearchEngine.query`` 与
审计溯源消费（见架构节「interfaces/analysis.py 形状」）。

``EvidenceRef`` 为 dataclass 形态（引擎内部流转），与契约层 pydantic 形态
``analysis/schemas.Evidence`` 一一对应互转（``Evidence.from_ref`` / ``to_ref``；
``confidence`` 不参与互转）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

from calliodesmo.analysis.materials import AnalysisMaterial
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext


@dataclass(frozen=True)
class AnalysisSpec:
    """分析任务规格（提交侧冻结的入参形态；worker 自 ``Job.task_payload`` 反序列化）。

    - ``doc_ids``：``None`` = 全可见范围；**仅作成员筛选，不豁免可见性校验**
      （红线一，见 ``analysis/materials.py``）；
    - ``question``：qa 必填（引擎侧校验，API 边界 400 见 Task 14）；
    - ``custom_instruction`` / ``custom_schema``：custom 必填 / 可选（注入防御见 Task 22）；
    - ``top_k``：qa 检索候选数；
    - ``model_override``：本次运行临时切换模型（经 ``retrieval/factory.build_llm_provider``
      同规则构造一次性 provider；缺 key 抛 ``RuntimeError``）。
    """

    task_type: AnalysisType
    doc_ids: tuple[str, ...] | None = None
    question: str = ""
    custom_instruction: str = ""
    custom_schema: dict | None = None
    top_k: int = 10
    model_override: str | None = None


@dataclass(frozen=True)
class EvidenceRef:
    """证据引用（引擎侧 dataclass 形态）：指向材料块的原文引文。

    与契约层 ``analysis/schemas.Evidence`` 一一对应互转；``quote`` 必填，
    缺失 / 失配由 ``analysis/evidence.verify_evidence`` 封顶置信 + warning。
    """

    chunk_id: str
    quote: str


@dataclass(frozen=True)
class AnalysisReport:
    """引擎产出：单次分析的结果信封前身（缺 ``generated_at``，worker 落库时补齐装配
    为契约层 ``AnalysisEnvelope``，见架构节「信封装配」）。

    - ``status``：``ok`` / ``partial``（契约枚举另含 ``failed``——解析预算耗尽等完全
      失败时引擎也返回本结构并带可读 warnings；落库规则为仅 ok / partial 落报告行，
      完全失败走 job failed，见计划「报告落库口径」，Task 12/13 消费）；
    - ``payload``：对应类型报告模型的 ``model_dump()``（failed 时为空字典）；
    - ``usage``：token 用量（跨回喂重试累计）。
    """

    task_type: AnalysisType
    status: str
    payload: dict
    model: str
    prompt_version: str
    usage: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)


class AnalysisEngine(ABC):
    """分析引擎抽象（可插拔）：吃已过滤材料，产出 ``AnalysisReport``。

    ``materials`` 必须已经过 ``visible_to`` 过滤（``gather_materials`` 职责，Task 9）；
    ``access`` 供 QA 类 ``SearchEngine.query`` 与审计溯源消费。
    """

    @abstractmethod
    async def run(
        self,
        spec: AnalysisSpec,
        materials: Sequence[AnalysisMaterial],
        access: AccessContext,
    ) -> AnalysisReport:
        """执行一次分析：prompt → LLM → 解析回喂重试 → 证据自验 → 结果装配。"""


__all__ = [
    "AnalysisEngine",
    "AnalysisMaterial",
    "AnalysisReport",
    "AnalysisSpec",
    "AnalysisType",
    "EvidenceRef",
]
