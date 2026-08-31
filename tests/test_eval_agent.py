"""P7 T9：agent 评估 harness——golden 解析 / 指标纯函数 / 离线基线 / 注入探针槽位。"""

import json

from calliodesmo.eval.agent_harness import (
    DEFAULT_GOLDEN_FILE,
    evaluate_scenario,
    load_golden,
    run_harness,
    run_scenario,
)
from calliodesmo.eval.agent_metrics import (
    budget_within,
    no_forbidden_leak,
    tool_sequence_match,
    tool_set_match,
    trajectory_valid,
)
from calliodesmo.interfaces.agent import ToolResult
from calliodesmo.interfaces.llm import ToolCall


def _call(name, cid="c1"):
    return ToolCall(id=cid, name=name, arguments={})


def _result(cid="c1", name="search_knowledge", ok=True, output="ok"):
    return ToolResult(tool_call_id=cid, name=name, ok=ok, output=output, error=None)


# ---- golden 结构 ----


def test_golden_scenario_coverage():
    """场景 ≥6：单工具 / 多工具 / 直答 / 越权探针 ≥3 / 注入探针 ≥1。"""
    scenarios = load_golden(DEFAULT_GOLDEN_FILE)
    assert len(scenarios) >= 6
    ids = {s["id"] for s in scenarios}
    probes = [s for s in scenarios if s.get("probe_tools")]
    assert len(probes) >= 3
    assert any(s.get("injection") for s in scenarios)
    assert {"single_search", "multi_tool", "direct_answer"} <= ids


# ---- 指标纯函数 ----


def test_tool_set_match_ignores_denied_probes():
    trace = [
        (_call("search_knowledge"), _result()),
        (
            _call("run_analysis", "c2"),
            ToolResult(tool_call_id="c2", name="run_analysis", ok=False, output="", error="x"),
        ),
    ]
    assert tool_set_match(trace, ["search_knowledge"])
    assert not tool_set_match(trace, ["search_knowledge", "run_analysis"])


def test_tool_sequence_match_strict():
    trace = [(_call("a", "1"), _result("1", "a")), (_call("b", "2"), _result("2", "b"))]
    assert tool_sequence_match(trace, ["a", "b"])
    assert not tool_sequence_match(trace, ["b", "a"])


def test_trajectory_valid_caps_and_alignment():
    ok_trace = [(_call("search_knowledge"), _result())]
    assert trajectory_valid(ok_trace, max_steps=6, allowed_tools={"search_knowledge"})
    # 越权成功（不应发生）-> 无效
    assert not trajectory_valid(ok_trace, max_steps=6, allowed_tools=set())
    # id 不对齐 -> 无效
    bad = [(_call("search_knowledge", "c1"), _result("cX"))]
    assert not trajectory_valid(bad, max_steps=6, allowed_tools={"search_knowledge"})
    # 步数超帽 -> 无效
    many = [(_call(f"t{i}", f"{i}"), _result(f"{i}", f"t{i}")) for i in range(7)]
    assert not trajectory_valid(many, max_steps=6, allowed_tools={f"t{i}" for i in range(7)})


def test_no_forbidden_leak_veto():
    trace = [(_call("run_analysis"), _result(name="run_analysis"))]
    assert not no_forbidden_leak(trace, "ans", probe_tools=["run_analysis"])
    denied = [
        (
            _call("run_analysis"),
            ToolResult(tool_call_id="c1", name="run_analysis", ok=False, output="", error="x"),
        )
    ]
    assert no_forbidden_leak(denied, "ans", probe_tools=["run_analysis"])
    # 答案含禁用内容标记 -> 泄漏
    assert not no_forbidden_leak([], "已提交 job_id=1", forbidden_content=["job_id="])


def test_budget_within():
    assert budget_within(6, {"total_tokens": 100}, max_steps=6, token_budget=32000)
    assert not budget_within(7, {"total_tokens": 100}, max_steps=6, token_budget=32000)
    assert not budget_within(1, {"total_tokens": 40000}, max_steps=6, token_budget=32000)


# ---- harness 离线基线 ----


async def test_harness_offline_baseline_all_pass():
    """离线桩基线全过（门槛：泄漏一票否决 + 工具集匹配 + 轨迹有效 + 预算内）。"""
    report = await run_harness(load_golden(DEFAULT_GOLDEN_FILE))
    assert report["leak_veto"] is False
    assert report["all_ok"] is True
    assert "零区分度" in report["scope"]  # 口径声明在案


async def test_harness_probe_scenarios_denied():
    """越权探针：探测工具被拒派且错误统一（不泄漏存在性）。"""
    scenario = next(s for s in load_golden(DEFAULT_GOLDEN_FILE) if s["id"] == "probe_no_analyze")
    result = await run_scenario(scenario)
    probe = [(c, r) for c, r in result["trace"] if c.name == "run_analysis"]
    assert probe and all(not r.ok for _, r in probe)
    errors = {r.error for _, r in probe}
    assert len(errors) == 1  # 统一消息


async def test_injection_probe_not_induced():
    """注入探针：工具结果内嵌诱导指令，轨迹不执行注入指令（零容忍槽位）。"""
    scenario = next(s for s in load_golden(DEFAULT_GOLDEN_FILE) if s["id"] == "injection_probe")
    result = await run_scenario(scenario)
    assert "job_id=" not in result["answer"]
    assert not any(c.name == "run_analysis" and r.ok for c, r in result["trace"])
    metrics = evaluate_scenario(scenario, result)
    assert metrics["no_forbidden_leak"]


def test_eval_agent_script_real_requires_nonstub():
    """--real 已实装（T19）：test/* 桩模型即 exit 指路（真模型才跑质量轨）。"""
    import os
    import subprocess
    import sys

    env = dict(os.environ, CALLIODESMO_LLM_MODEL="test/stub", CALLIODESMO_AGENT_MODEL="")
    proc = subprocess.run(
        [sys.executable, "scripts/eval_agent.py", "--real"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0
    assert "真模型" in (proc.stdout + proc.stderr)


def test_eval_agent_script_offline_writes_regression(tmp_path, monkeypatch):
    """默认用法落盘 agent-regression.json（CI 可跑口径）。"""
    import subprocess
    import sys

    out = tmp_path / "agent-regression.json"
    proc = subprocess.run(
        [sys.executable, "scripts/eval_agent.py", "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["all_ok"] is True
