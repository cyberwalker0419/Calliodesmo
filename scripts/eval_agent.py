"""P7 agent 评估 harness CLI（T9 离线 / T19 --real 双轨）。

三用法：
- 默认：离线桩基线跑批并落盘 ``docs/verification/agent-regression.json``
  （CI 可跑口径；明确声明离线≠质量）；门槛不过 exit 1（T10 放行条件）。
- ``--dump-golden``：转储观测轨迹供人工复核（不自动接受为 golden）。
- ``--real``：真模型质量轨——P7 T19 实装（锚点 2026-W45）；预检后端原生
  tool calls，不支持则换模型并留痕，**不做 prompt-based 文本协议降级**。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

REAL_ANCHOR = (
    "--real 质量补跑由 P7 T19 实装（锚点 2026-W45）：预检后端原生 tool calls，不做文本协议降级"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="agent golden 轨迹评估")
    parser.add_argument("--real", action="store_true", help="真模型质量轨（T19）")
    parser.add_argument("--dump-golden", action="store_true", help="转储观测轨迹供人工复核")
    parser.add_argument("--golden", default="config/golden_agent.yaml")
    parser.add_argument("--out", default="docs/verification/agent-regression.json")
    args = parser.parse_args()

    if args.real:
        raise SystemExit(REAL_ANCHOR)

    from calliodesmo.eval.agent_harness import load_golden, run_harness, run_scenario

    scenarios = load_golden(args.golden)

    if args.dump_golden:
        observed = []
        for scenario in scenarios:
            result = asyncio.run(run_scenario(scenario))
            observed.append(
                {
                    "id": scenario["id"],
                    "trace": [
                        {"tool": c.name, "args": c.arguments, "ok": r.ok}
                        for c, r in result["trace"]
                    ],
                    "answer": result["answer"],
                }
            )
        print(json.dumps(observed, ensure_ascii=False, indent=2))
        return 0

    report = asyncio.run(run_harness(scenarios))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"all_ok={report['all_ok']} leak_veto={report['leak_veto']} "
        f"scenarios={len(report['scenarios'])} -> {out}"
    )
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
