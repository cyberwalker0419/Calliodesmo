"""P8 证据验证域：确定性核验引擎、接地度侧车与置信度校准。

模块划分：
- ``models``：``Claim`` / ``EvidenceSpan`` / ``VerificationResult`` / ``Verdict`` 数据契约；
- ``engine``：纯函数核验（引注定位、矛盾启发式、跨文档检索）；
- ``pipeline``（T3）：材料收集 → claim 抽取 → 核验 → 汇总侧车；
- ``calibration``（T4）：温度缩放与 ECE。
"""

from calliodesmo.verification.models import Claim, EvidenceSpan, Verdict, VerificationResult

__all__ = ["Claim", "EvidenceSpan", "Verdict", "VerificationResult"]
