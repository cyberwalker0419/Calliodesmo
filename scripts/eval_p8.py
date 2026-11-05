"""P8 接地度 / 校准 / 意图路由评估脚本（T1 起离线轨，T4 扩 --real 质量轨）。

默认离线：加载三份 P8 语料，跑确定性核验引擎与指标函数，落盘
``docs/verification/p8-regression.json``（结构 / 契约证据，**非质量结论**）。
``--real``：真模型质量轨（T4 实现），落盘 ``docs/verification/p8-real-<模型名>.json``。

离线证据≠质量证据：桩与确定性核验对「真实幻觉发生率」零区分度，离线全绿只承诺
证据契约、状态判定、权限矩阵、评分公式与路由决策表；质量结论仅来自 ``--real``。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from calliodesmo.eval.metrics_grounding import (
    citation_precision,
    claim_grounding,
    contradiction_rate,
    uncited_claim_rate,
    unsupported_rate,
)
from calliodesmo.verification.engine import verify_claims
from calliodesmo.verification.models import Claim, Verdict

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "verification" / "p8-regression.json"
QA_V2 = ROOT / "config" / "golden_qa_v2.yaml"
VERIFICATION = ROOT / "config" / "golden_verification.yaml"
CONTRADICTIONS = ROOT / "config" / "golden_contradictions.yaml"
DEMO_DIR = ROOT / "data" / "demo"

OFFLINE_DISCLAIMER = (
    "离线证据≠质量证据：确定性核验与桩对真实幻觉发生率零区分度；"
    "本文件只承诺语料结构、判定契约与指标公式，质量结论须由 --real 质量轨承担。"
)


def load_sources() -> dict[str, str]:
    """data/demo 三件语料 → chunk_id 映射（`<文件名>#0`）。"""
    return {f"{p.name}#0": p.read_text(encoding="utf-8") for p in sorted(DEMO_DIR.glob("*.md"))}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _claims_from(items: list[dict]) -> list[Claim]:
    return [
        Claim(
            text=item["claim"],
            chunk_id=item.get("chunk_id") or None,
            quote=item.get("quote") or None,
            topic=item.get("topic"),
        )
        for item in items
    ]


def run_offline() -> dict:
    """离线轨：语料统计 + 核验判定 + 结构指标。"""
    sources = load_sources()
    qa_cases = load_yaml(QA_V2)["cases"]
    verification_items = load_yaml(VERIFICATION)["claims"]
    contradiction_items = load_yaml(CONTRADICTIONS)["pairs"]

    results = verify_claims(_claims_from(verification_items), sources)
    verdict_counts = Counter(result.verdict.value for result in results)
    mismatches = [
        {
            "id": item["id"],
            "expected": item["expected_verdict"],
            "actual": result.verdict.value,
            "reason": result.reason,
        }
        for item, result in zip(verification_items, results, strict=True)
        if result.verdict.value != item["expected_verdict"]
    ]

    contradiction_claims = [
        Claim(
            text=item["claim"],
            chunk_id=item["chunk_id"],
            quote=item["source_quote"],
            topic=item.get("topic"),
        )
        for item in contradiction_items
    ]
    contradiction_results = verify_claims(contradiction_claims, sources)
    contradiction_hits = sum(
        1 for result in contradiction_results if result.verdict is Verdict.CONTRADICTED
    )

    total = len(results)
    supported = verdict_counts[Verdict.SUPPORTED.value]
    unsupported = verdict_counts[Verdict.UNSUPPORTED.value]
    contradicted = verdict_counts[Verdict.CONTRADICTED.value]
    uncited = sum(1 for item in verification_items if not item.get("quote"))
    cited = total - uncited
    supported_citations = sum(
        1
        for item, result in zip(verification_items, results, strict=True)
        if item.get("quote") and result.verdict is Verdict.SUPPORTED
    )

    qa_categories = Counter(case["category"] for case in qa_cases)
    return {
        "phase": "P8",
        "track": "offline",
        "disclaimer": OFFLINE_DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
        "corpora": {
            "golden_qa_v2": {
                "cases": len(qa_cases),
                "categories": dict(sorted(qa_categories.items())),
            },
            "golden_verification": {
                "claims": total,
                "injection_probes": sum(1 for item in verification_items if item.get("injection")),
                "verdicts": dict(
                    sorted(Counter(item["expected_verdict"] for item in verification_items).items())
                ),
            },
            "golden_contradictions": {
                "pairs": len(contradiction_items),
                "types": dict(
                    sorted(Counter(item["conflict_type"] for item in contradiction_items).items())
                ),
            },
        },
        "verification": {
            "total": total,
            "matched": total - len(mismatches),
            "match_rate": round((total - len(mismatches)) / total, 4) if total else 0.0,
            "mismatches": mismatches,
            "verdict_counts": dict(sorted(verdict_counts.items())),
            "contradiction_pairs_hit": contradiction_hits,
            "contradiction_pairs_total": len(contradiction_items),
        },
        "metrics": {
            "citation_precision": round(citation_precision(supported_citations, cited), 4),
            "claim_grounding": round(claim_grounding(supported, total), 4),
            "unsupported_rate": round(unsupported_rate(unsupported, total), 4),
            "contradiction_rate": round(contradiction_rate(contradicted, total), 4),
            "uncited_claim_rate": round(uncited_claim_rate(uncited, total), 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P8 接地度评估（离线 / --real 双轨）")
    parser.add_argument("--real", action="store_true", help="真模型质量轨（T4 实现）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    if args.real:
        print("--real 质量轨在 P8 Task 4 接入（当前仅离线结构轨）")
        return 1
    report = run_offline()
    out = Path(args.out)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"offline: claims={report['verification']['total']} "
        f"matched={report['verification']['matched']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
