"""Offline configuration preflight. Never calls a provider."""
import argparse
import os
import sqlite3
from contextlib import closing
from prompt_lib.experiment import CURRENT, select_model
from src.experiment import configuration
from prompt_lib.backends.request_budget import LEDGER, LIMIT


def describe(path):
    config = configuration(path)
    lines = [f"Configuration: {path}", f"Variant: {config['variant']}", ""]
    marker = CURRENT.set(config)
    try:
        stages = ["generation"] if config["variant"] == "A" else ["generation", "feedback", "refinement"]
        for stage in stages:
            model = select_model(stage, config["original_model"])
            lines.append(f"{stage.capitalize()}: {model}")
            if model.startswith("hf:"):
                from prompt_lib.backends.huggingface_api import HuggingFaceAPIWrapper
                lines.append(f"  Endpoint: {HuggingFaceAPIWrapper.endpoint}")
                lines.append("  HF_TOKEN: " + ("configured" if os.getenv("HF_TOKEN") else "MISSING"))
            elif model.startswith("groq:"):
                lines.append("  GROQ_API_KEY: " + ("configured" if os.getenv("GROQ_API_KEY") else "MISSING"))
            elif "gemini" in model.lower():
                lines.append("  Gemini credential: " + ("configured" if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") else "MISSING"))
    finally:
        CURRENT.reset(marker)
    lines += ["", "HF to Groq fallback: " + ("enabled" if config["hf_groq_fallback"] else "disabled")]
    if config["hf_groq_fallback"]:
        lines.append(f"Fallback model: {config['groq_model']}")
    try:
        with closing(sqlite3.connect(f"file:{LEDGER.as_posix()}?mode=ro", uri=True)) as db:
            used = db.execute("SELECT used FROM budget WHERE id=1").fetchone()[0]
        lines.append(f"Hosted request budget: {used}/{LIMIT} used (Groq/HF, including retries).")
    except (sqlite3.Error, TypeError):
        lines.append("Hosted request budget unavailable; adapter calls will be blocked.")
    lines += ["", "Local checks only. Account access, model availability and credits are NOT verified.",
              "No API requests made."]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print(describe(args.config))

if __name__ == "__main__":
    main()
