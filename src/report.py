"""Readable reports from saved records; no inference requests."""
import argparse
import json
from pathlib import Path
from src.output import redact


def text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_record(record, number=1):
    lines = [f"# Result {number}", "", f"Status: {record.get('status', 'unknown')}", "", "## Question", ""]
    source = record.get("input", {})
    lines += [text(source.get("context", source) if isinstance(source, dict) else source), "", "## Final answer", "",
              text(record.get("final_output") or record.get("error") or "No final answer saved."), ""]
    if record.get("status") == "partial":
        lines += ["## Completion note", "", "The experiment stopped early. The answer above is the latest completed answer; it may lack final feedback.",
                  "", text(record.get("error", "")), ""]
    calls = record.get("calls", [])
    if calls:
        lines += ["## Models used", ""]
        for call in calls:
            model = call.get("effective_model") or call.get("requested_model", "unknown")
            lines.append(f"- {call.get('stage', 'unknown')}: {model} ({call.get('status', 'unknown')})")
            if call.get("fallback"):
                lines.append("  Provider fallback occurred; this was not an HF-only result.")
        usage = [c.get("usage") or {} for c in calls]
        total = sum(u["total_tokens"] for u in usage) if all(isinstance(u.get("total_tokens"), int) for u in usage) else None
        lines += ["", f"Model calls: {len(calls)} (HTTP retries may increase requests).",
                  f"Reported total tokens: {total if total is not None else 'unavailable'}."]
    latency = record.get("latency_seconds")
    if isinstance(latency, (int, float)):
        lines += [f"Elapsed time: {latency:.2f} seconds."]
    lines += [""]
    candidates = record.get("result")
    if isinstance(candidates, dict) and candidates and all(isinstance(v, dict) and "scores" in v for v in candidates.values()):
        lines += ["## Answer history and feedback", "", "Scores below are model feedback, not independent evaluation.", ""]
        for answer, details in candidates.items():
            attempt = details.get("n_attempts", 0)
            label = "Initial answer" if attempt == 0 else f"Refinement {attempt}"
            lines += [f"### {label}", "", answer, "", "Feedback:", "", text(details.get("scores") or "Unavailable: feedback was not completed."), ""]
    return redact("\n".join(lines))


def write_report(source, destination=None):
    source = Path(source)
    destination = Path(destination) if destination else source.with_suffix(".md")
    if destination.resolve() == source.resolve():
        raise ValueError("Report must not overwrite its source.")
    records = [json.loads(line) for line in source.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    content = "\n---\n\n".join(render_record(record, i) for i, record in enumerate(records, 1))
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(content + "\n")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Existing JSONL results; no model calls are made")
    parser.add_argument("--output", help="New Markdown report path")
    args = parser.parse_args()
    print(f"Readable report: {write_report(args.input, args.output)}")

if __name__ == "__main__":
    main()
