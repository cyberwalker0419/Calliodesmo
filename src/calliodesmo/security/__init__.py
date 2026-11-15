"""安全护栏域：输出层注入防御与敏感输出拦截（P9 Task 2）。"""

from calliodesmo.security.output_guard import (
    SAFE_BLOCK_TEXT,
    GuardResult,
    GuardViolation,
    guard_output,
    guard_payload,
)

__all__ = [
    "SAFE_BLOCK_TEXT",
    "GuardResult",
    "GuardViolation",
    "guard_output",
    "guard_payload",
]
