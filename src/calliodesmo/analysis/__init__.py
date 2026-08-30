"""P6 分析域：报告契约、证据校验、提示词、解析、材料采集、密级继承、引擎与持久化。

分层约定：本包为分析业务域（契约层 pydantic 形态在此）；``interfaces/analysis.py``
为可插拔引擎抽象（dataclass 形态，Task 10 冻结，2026-W39）。两侧证据形状一一对应互转：
契约层 ``Evidence`` ↔ 引擎侧 ``EvidenceRef``（见 ``schemas.Evidence.from_ref`` / ``to_ref``）。
"""
