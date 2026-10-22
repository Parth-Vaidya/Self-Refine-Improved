"""Consistent, credential-safe terminal output and final-result selection."""
import json
import os
import re


def redact(value):
    text = str(value)
    for name, secret in os.environ.items():
        if secret and ("TOKEN" in name or "API_KEY" in name):
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r"hf_[A-Za-z0-9]{20,}", "[REDACTED]", text)


def show(label, value, stream):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    print(f"\n{label}\n{redact(value)}", file=stream, flush=True)


def final_output(task, result, variant):
    if variant == "A":
        return result
    if not result:
        return None
    if task in ("acronym", "responsegen"):
        # Match the existing acronym CLI's best-score selection (first wins ties).
        return max(result, key=lambda candidate: result[candidate]["total_score"])
    if task == "commongen":
        return result[-1]["sentence"]
    if task == "pie":
        return result[-1]["fast_code"]
    if task == "gsm":
        return result[-1]["solution_fixed"]
    if task == "sentiment_reversal":
        return result[-1]["transferred_review"]
    if task == "readability":
        updates = result["updates"]
        return updates[-1]["updated_code"] if updates else result["original_code"]
    raise ValueError("Unsupported output task")
