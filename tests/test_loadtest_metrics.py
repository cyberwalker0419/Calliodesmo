"""P9 Task 8：压测工具函数单测（分位数 / 并发 runner / 泄漏计数）。"""

from __future__ import annotations

import math
import os

import pytest

from calliodesmo.eval.loadtest import (
    BenchResult,
    bench,
    percentile,
    summarize_latencies,
)


class TestPercentile:
    def test_empty(self):
        assert percentile([], 0.95) == 0.0

    def test_single(self):
        assert percentile([1.5], 0.5) == 1.5
        assert percentile([1.5], 0.99) == 1.5

    def test_nearest_rank_semantics(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert percentile(values, 0.5) == 2.0
        assert percentile(values, 0.95) == 4.0
        assert percentile(values, 1.0) == 4.0
        assert percentile(values, 0.0) == 1.0

    def test_input_not_mutated_and_unsorted_ok(self):
        values = [4.0, 1.0, 3.0, 2.0]
        snapshot = list(values)
        assert percentile(values, 0.75) == 4.0 or percentile(values, 0.75) == 3.0
        assert values == snapshot

    def test_invalid_quantile(self):
        with pytest.raises(ValueError):
            percentile([1.0], 1.5)


class TestSummarize:
    def test_shape_and_values(self):
        summary = summarize_latencies([1.0, 2.0, 3.0, 4.0, 5.0])
        assert summary["count"] == 5
        assert summary["mean"] == pytest.approx(3.0)
        assert summary["max"] == 5.0
        assert summary["p50"] <= summary["p95"] <= summary["p99"]

    def test_empty(self):
        summary = summarize_latencies([])
        assert summary["count"] == 0
        assert summary["p95"] == 0.0
        assert math.isnan(summary["mean"]) is False


class TestBench:
    async def test_counts_and_order(self):
        calls: list[int] = []

        async def worker(index: int) -> bool:
            calls.append(index)
            return False  # 无泄漏

        result = await bench(worker, total=7, concurrency=3)
        assert isinstance(result, BenchResult)
        assert result.total == 7
        assert result.ok == 7
        assert result.failed == 0
        assert result.leaks == 0
        assert len(result.latencies_ms) == 7
        assert sorted(calls) == list(range(7))

    async def test_failures_counted_not_raised(self):
        async def worker(index: int) -> bool:
            if index % 2 == 0:
                raise RuntimeError("后端炸了")
            return False

        result = await bench(worker, total=6, concurrency=2)
        assert result.ok == 3
        assert result.failed == 3
        assert result.errors[0].startswith("RuntimeError")

    async def test_leaks_counted(self):
        async def worker(index: int) -> bool:
            return index == 1  # 一次越权命中

        result = await bench(worker, total=5, concurrency=5)
        assert result.leaks == 1

    async def test_concurrency_never_exceeded(self):
        import asyncio

        state = {"active": 0, "peak": 0}

        async def worker(index: int) -> bool:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0)  # 让出控制权，暴露并发峰值
            state["active"] -= 1
            return False

        await bench(worker, total=40, concurrency=4)
        assert 1 <= state["peak"] <= 4

    def test_invalid_params(self):
        import asyncio

        async def worker(index: int) -> bool:
            return False

        with pytest.raises(ValueError):
            asyncio.run(bench(worker, total=0, concurrency=1))
        with pytest.raises(ValueError):
            asyncio.run(bench(worker, total=1, concurrency=0))

    def test_bench_result_summary(self):
        result = BenchResult(
            total=3,
            concurrency=1,
            ok=3,
            failed=0,
            leaks=0,
            errors=[],
            latencies_ms=[10.0, 20.0, 30.0],
            wall_seconds=0.3,
        )
        summary = result.summary()
        assert summary["throughput_rps"] == pytest.approx(10.0)
        assert summary["p50"] == 20.0
        assert summary["p95"] == 30.0
        assert summary["p99"] == 30.0
        assert summary["concurrency"] == 1


class TestLoadtestScript:
    """脚本冒烟（子进程，与 test_eval_agent 同范式）：小语料跑通并落结构化证据。"""

    def test_small_run_writes_structured_json(self, tmp_path):
        import json
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        out = tmp_path / "load.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "loadtest_p9.py"),
                "--docs",
                "12",
                "--requests",
                "6",
                "--out",
                str(out),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",  # 写读两端都固定 UTF-8（否则父进程代码页影响解码）
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr[-800:]
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["phase"] == "P9"
        assert report["track"] == "loadtest"
        assert set(report["levels"]) == {"1", "5", "20"}
        assert report["leaks_total"] == 0
        assert report["failed_total"] == 0
        assert report["corpus"]["documents"] == 12
        for level in report["levels"].values():
            assert level["p50"] <= level["p95"] <= level["p99"]
            assert level["count"] == 6
            # 有效性：每级都必须真命中语料（零命中的时延数字没有意义）
            assert level["with_hits"] == 6

    def test_osint_sampling_falls_back_when_missing(self, tmp_path):
        import json
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        out = tmp_path / "load.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "loadtest_p9.py"),
                "--osint-corpus",
                str(tmp_path / "nope.json"),
                "--docs",
                "8",
                "--requests",
                "4",
                "--out",
                str(out),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",  # 写读两端都固定 UTF-8（否则父进程代码页影响解码）
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr[-800:]
        report = json.loads(out.read_text(encoding="utf-8"))
        assert "回退" in report["corpus"]["note"]
        assert report["leaks_total"] == 0


class TestOsintCorpusShape:
    """真实数据集抽样：结构不符时给出可读说明而不是抛栈。"""

    def test_cisa_like_structure(self, tmp_path):
        import json
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import importlib

        module = importlib.import_module("loadtest_p9")
        path = tmp_path / "kev.json"
        path.write_text(
            json.dumps(
                {
                    "vulnerabilities": [
                        {
                            "cveID": f"CVE-2026-{i:04d}",
                            "vendorProject": "示例厂商",
                            "product": "示例产品",
                            "dateAdded": "2026-01-01",
                        }
                        for i in range(4)
                    ]
                }
            ),
            encoding="utf-8",
        )
        corpus, note = module.osint_corpus(path, 3)
        assert len(corpus) == 3
        assert all(entry["query"] for entry in corpus)
        assert "抽样" in note
        assert corpus[0]["chunk_id"] == "osint-0000.md#0"
        assert [entry["access_level"].name for entry in corpus] == [
            "PUBLIC",
            "CONFIDENTIAL",
            "PUBLIC",
        ]

    def test_wrong_structure_returns_note(self, tmp_path):
        import importlib
        import json
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        module = importlib.import_module("loadtest_p9")
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"unexpected": 1}), encoding="utf-8")
        corpus, note = module.osint_corpus(path, 5)
        assert corpus == []
        assert "结构" in note
