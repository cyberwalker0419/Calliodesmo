"""P9 Task 8：压测基线工具（分位数 / 并发 runner / 结果汇总，纯标准库、离线可测）。

与检索精度 harness（``eval/harness.py``）分工：那边量「答得准不准」，这边量
「扛得住多少、慢在哪里」。规模结论只承诺**相对基线**（同机同语料可重复），
不外推为容量上限——真实容量取决于硬件与后端（pgvector / Neo4j 与内存后端差异极大）。

并发 runner 的纪律：

- 固定并发度的任务池（信号量），不用 ``gather`` 一次性铺满，避免把「并发 20」
  跑成「同时 20 个请求排队」；
- worker 抛异常计入 ``failed`` 而非中断整轮（压测里后端报错本身就是要观测的信号）；
- worker 返回布尔 ``leak``：本次请求是否把不该看见的内容带回来了——越权泄漏在
  压测里按**一票否决**计，泄漏数 > 0 即整轮判失败。
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

#: 记录的错误样本上限（只留可读前缀，不落正文）
MAX_ERROR_SAMPLES = 10


def percentile(values: list[float], quantile: float) -> float:
    """最近秩分位数（``ceil(q * n)`` 位，升序）；空输入返回 0.0。

    取最近秩而非线性插值：压测关心「95% 的请求不超过多少」，插值会给出样本中
    不存在的中间值，读数好看不可核对。
    """
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile 必须落在 [0, 1]")
    if not values:
        return 0.0
    ordered = sorted(values)
    if quantile <= 0.0:
        return ordered[0]
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize_latencies(latencies_ms: list[float]) -> dict[str, float]:
    """时延汇总：count / mean / p50 / p95 / p99 / max（毫秒，四位小数）。"""
    ordered = [float(x) for x in latencies_ms]
    count = len(ordered)
    return {
        "count": count,
        "mean": round(sum(ordered) / count, 4) if count else 0.0,
        "p50": round(percentile(ordered, 0.50), 4),
        "p95": round(percentile(ordered, 0.95), 4),
        "p99": round(percentile(ordered, 0.99), 4),
        "max": round(max(ordered), 4) if count else 0.0,
    }


@dataclass
class BenchResult:
    """一轮压测结果（结构稳定，便于 JSON 落盘与断言）。"""

    total: int
    concurrency: int
    ok: int = 0
    failed: int = 0
    leaks: int = 0
    wall_seconds: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        """可直接进证据 JSON 的汇总（时延 + 吞吐 + 计数）。"""
        stats = summarize_latencies(self.latencies_ms)
        throughput = self.total / self.wall_seconds if self.wall_seconds > 0 else 0.0
        return {
            "total": self.total,
            "ok": self.ok,
            "failed": self.failed,
            "leaks": self.leaks,
            "concurrency": self.concurrency,
            "error_samples": list(self.errors),
            "wall_seconds": round(self.wall_seconds, 4),
            "throughput_rps": round(throughput, 4),
            **stats,
        }


async def bench(
    worker: Callable[[int], Awaitable[bool]],
    *,
    total: int,
    concurrency: int,
) -> BenchResult:
    """以固定并发跑 ``total`` 次 ``worker(index)``。

    参数:
        worker: 异步工作函数；返回 ``True`` 表示该次请求出现越权泄漏。
        total: 请求总数（>0）。
        concurrency: 并发度（>0，信号量控制，峰值不超过该值）。
    """
    if total <= 0:
        raise ValueError("total 必须 > 0")
    if concurrency <= 0:
        raise ValueError("concurrency 必须 > 0")

    result = BenchResult(total=total, concurrency=concurrency)
    gate = asyncio.Semaphore(concurrency)

    async def _one(index: int) -> None:
        async with gate:
            started = time.perf_counter()
            try:
                leaked = await worker(index)
            except Exception as exc:  # 压测不中断：错误计入 failed
                result.latencies_ms.append((time.perf_counter() - started) * 1000)
                result.failed += 1
                if len(result.errors) < MAX_ERROR_SAMPLES:
                    result.errors.append(f"{type(exc).__name__}: {exc}"[:200])
                return
            result.latencies_ms.append((time.perf_counter() - started) * 1000)
            if leaked:
                result.leaks += 1
            else:
                result.ok += 1

    began = time.perf_counter()
    await asyncio.gather(*(_one(index) for index in range(total)))
    result.wall_seconds = time.perf_counter() - began
    return result


__all__ = ["BenchResult", "bench", "percentile", "summarize_latencies"]
