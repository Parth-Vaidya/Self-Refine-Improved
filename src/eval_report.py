"""Summarize and format Phase 4 evaluation results from JSONL into Markdown."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Dict, List


def generate_evaluation_report(
    results_jsonl: str | Path,
    output_md: str | Path = "evaluations/PHASE_4_EVALUATION_REPORT.md",
) -> str:
    """Generate Markdown comparison report from evaluation results JSONL."""
    source_path = Path(results_jsonl)
    if not source_path.exists():
        raise FileNotFoundError(f"Results file not found: {source_path}")

    records: List[Dict[str, object]] = []
    for line in source_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

    # Aggregate metrics by condition
    by_condition: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for r in records:
        by_condition[str(r["condition_key"])].append(r)

    lines: List[str] = [
        "# Phase 4: Comparative Evaluation and Telemetry Analysis Report",
        "",
        "## 1. Experimental Conditions Overview",
        "",
        "| Condition | Description | Mode | Personalization Profile |",
        "|---|---|---|---|",
        "| **A** | Standard without personalization | `standard` (1-pass) | Disabled / None |",
        "| **B** | Self-Refine without personalization | `self_refine` (iterative) | Disabled / None |",
        "| **C** | Standard with personalization | `standard` (1-pass) | Enabled (`evaluations/test_profile.json`) |",
        "| **D** | Self-Refine with personalization | `self_refine` (iterative) | Enabled (`evaluations/test_profile.json`) |",
        "",
        "## 2. Telemetry and Performance Comparison",
        "",
        "| Condition | Runs | Success Rate | Avg Latency (s) | Avg Prompt Tokens | Avg Completion Tokens | Avg Total Tokens | Avg API Calls |",
        "|---|---|---|---|---|---|---|---|",
    ]

    summary_stats = {}
    for cond_key in ["A", "B", "C", "D"]:
        recs = by_condition.get(cond_key, [])
        if not recs:
            continue
        total_runs = len(recs)
        successes = sum(1 for r in recs if r.get("status") == "success")
        success_rate = (successes / total_runs) * 100 if total_runs else 0

        avg_lat = sum(float(r["telemetry"]["latency_seconds"]) for r in recs) / total_runs
        avg_pt = sum(int(r["telemetry"]["prompt_tokens"]) for r in recs) / total_runs
        avg_ct = sum(int(r["telemetry"]["completion_tokens"]) for r in recs) / total_runs
        avg_tt = sum(int(r["telemetry"]["total_tokens"]) for r in recs) / total_runs
        avg_calls = sum(int(r["telemetry"]["api_call_count"]) for r in recs) / total_runs

        summary_stats[cond_key] = {
            "avg_lat": avg_lat,
            "avg_tt": avg_tt,
            "avg_calls": avg_calls,
        }

        lines.append(
            f"| **{cond_key}** | {total_runs} | {success_rate:.1f}% | {avg_lat:.2f}s | "
            f"{avg_pt:.1f} | {avg_ct:.1f} | {avg_tt:.1f} | {avg_calls:.1f} |"
        )

    lines.extend([
        "",
        "## 3. Trade-Off and Multiplier Analysis",
        "",
    ])

    if "A" in summary_stats and "B" in summary_stats:
        lat_ratio = summary_stats["B"]["avg_lat"] / max(0.001, summary_stats["A"]["avg_lat"])
        tok_ratio = summary_stats["B"]["avg_tt"] / max(1, summary_stats["A"]["avg_tt"])
        lines.append(f"- **Self-Refine vs. Standard Latency Multiplier (B / A):** {lat_ratio:.2f}x")
        lines.append(f"- **Self-Refine vs. Standard Token Overhead (B / A):** {tok_ratio:.2f}x")

    if "A" in summary_stats and "C" in summary_stats:
        lines.append(f"- **Personalization Token Delta in Standard Mode (C - A):** {summary_stats['C']['avg_tt'] - summary_stats['A']['avg_tt']:.1f} tokens")

    lines.extend([
        "",
        "## 4. Response Quality Evaluation Criteria",
        "",
        "Response quality is evaluated against four distinct dimensions rather than inferred solely from latency or token volume:",
        "",
        "1. **Correctness:** Are the facts, derivations, mathematical solutions, and code syntax accurate?",
        "2. **Completeness:** Did the model address all constraints of the query (e.g. Kadane's algorithm, edge cases)?",
        "3. **Clarity & Structure:** Is the response legible, coherent, and appropriately formatted?",
        "4. **Preference Adherence:** In conditions C and D, did the model follow the active profile directives (step-by-step breakdown, simple code, and practical examples)?",
        "",
        "> **Methodological Note:** Quality scores are not fabricated or derived from token volume. In accordance with benchmark methodology, responses are archived in `evaluations/phase_4_results.jsonl` for qualitative inspection.",
        "",
        "## 5. Sample Query Outputs (Excerpt)",
        "",
    ])

    # Show sample output from each condition for the first prompt
    first_recs = records[:4]
    for r in first_recs:
        lines.append(f"### Condition {r['condition_key']} - Prompt: `{r['prompt_id']}`")
        lines.append(f"**Query:** {r['query']}")
        lines.append(f"**Status:** {r['status']} | **Latency:** {r['telemetry']['latency_seconds']}s | **Calls:** {r['telemetry']['api_call_count']}")
        preview = str(r['response'])[:300].replace("\n", " ") + ("..." if len(str(r['response'])) > 300 else "")
        lines.append(f"**Response Preview:** {preview}")
        lines.append("")

    report_content = "\n".join(lines) + "\n"
    out_path = Path(output_md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_content, encoding="utf-8")
    return report_content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="evaluations/phase_4_results.jsonl", help="Path to results JSONL")
    parser.add_argument("--output", default="evaluations/PHASE_4_EVALUATION_REPORT.md", help="Path to markdown report")
    args = parser.parse_args()

    generate_evaluation_report(args.results, args.output)
    print(f"Report generated: {args.output}")


if __name__ == "__main__":
    main()

