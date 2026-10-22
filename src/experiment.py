"""Run controlled experiments without changing the legacy iterative algorithms."""
import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import io
import math
import os
import platform
import sys
from pathlib import Path
import time
import uuid

from src import utils  # Load .env without overriding existing environment variables.
from prompt_lib.experiment import CURRENT
from prompt_lib.backends.huggingface_api import InferenceError
from src.output import final_output, redact, show

TASKS = {
    "readability": (None, "refine_code"),
    "acronym": ("AcronymGenTaskInit", "iterative_acronym"),
    "commongen": ("CommongenTaskInit", "autofb_commongen"),
    "pie": ("PieInit", "iterative_pie"),
    "responsegen": ("ResponseGenTaskInit", "iterative_response"),
    "gsm": ("GSMInit", "iterative_gsm"),
    "sentiment_reversal": ("SentimentTransferTaskInit", "iterative_prompting"),
}


def configuration(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {"variant", "original_model", "generation_model", "feedback_model", "measurement_model",
               "refinement_model", "prices", "hf_groq_fallback", "groq_model"}
    if set(config) - allowed or config.get("variant") not in ("A", "B", "C"):
        raise InferenceError("Invalid experiment configuration keys or variant.")
    config.setdefault("original_model", os.getenv("LLM_ENGINE", "gemini-1.5-flash"))
    for stage in ("generation", "feedback", "measurement"):
        config.setdefault(stage + "_model", os.getenv("SR_" + stage.upper() + "_MODEL") or config["original_model"])
    config.setdefault("refinement_model", "hf:" + os.getenv("HF_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507") +
                      ":" + os.getenv("HF_PROVIDER", "nscale"))
    config.setdefault("hf_groq_fallback", config["variant"] == "C" and os.getenv("HF_GROQ_FALLBACK", "false").lower() == "true")
    config.setdefault("groq_model", "groq:" + os.getenv("GROQ_MODEL_ID", "openai/gpt-oss-20b").removeprefix("groq:"))
    if not isinstance(config["hf_groq_fallback"], bool):
        raise InferenceError("hf_groq_fallback must be a JSON boolean.")
    if config["hf_groq_fallback"] and config["variant"] != "C":
        raise InferenceError("Fallback is only supported in variant C; keep A/B baselines fixed.")
    if not isinstance(config["groq_model"], str) or not config["groq_model"].startswith("groq:") or not config["groq_model"][5:]:
        raise InferenceError("groq_model must specify groq:model-id.")
    for key in ("original_model", "generation_model", "feedback_model", "measurement_model", "refinement_model"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise InferenceError("Model identifiers must be non-empty strings.")
    prices = config.get("prices", {})
    if not isinstance(prices, dict):
        raise InferenceError("Prices must map model identifiers to token rates.")
    for rate in prices.values():
        if not isinstance(rate, dict) or set(rate) != {"input_per_million", "output_per_million"} or any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or not math.isfinite(v)
                for v in rate.values()):
            raise InferenceError("Price rates must be finite non-negative numbers.")
    if config["variant"] == "B" and any(config[k] != config["original_model"] for k in
                                            ("generation_model", "feedback_model", "measurement_model")):
        raise InferenceError("Configuration B requires the same original model for every stage.")
    # Configuration files and output are public research artifacts, never secret stores.
    secrets = [v for k, v in os.environ.items() if v and ("TOKEN" in k or "API_KEY" in k)]
    encoded = json.dumps(config)
    if any(secret in encoded for secret in secrets):
        raise InferenceError("A credential was found in experiment configuration.")
    return config


def one_pass(task, row, config, temperature):
    cls = getattr(importlib.import_module("src." + task + ".task_init"), TASKS[task][0])
    kwargs = {"engine": config["original_model"]}
    if task != "sentiment_reversal":
        suffix = "txt" if task in ("pie", "gsm") else "jsonl"
        kwargs["prompt_examples"] = f"data/prompt/{task}/init.{suffix}"
    if task in ("pie", "gsm"):
        kwargs["temperature"] = temperature
    initial = cls(**kwargs)
    if task == "acronym":
        return initial(title=row["title"])
    if task == "commongen":
        return initial(concepts=row["concepts"])
    if task == "pie":
        return initial(slow_code=row["input"])
    if task == "gsm":
        return initial(solution=row["input"])
    if task == "responsegen":
        return initial(context=row["context"])[1]
    return initial(review=row["review"], sentiment=row["sentiment"], target_sentiment=row["target_sentiment"])[0]


def iterative(task, row, attempts, temperature, feedback_type):
    if task == "readability":
        from src.readability.readability import refine_code
        return refine_code(row["input"])
    fn = getattr(importlib.import_module("src." + task + ".run"), TASKS[task][1])
    kwargs = {"max_attempts": attempts}
    if task == "acronym":
        kwargs["title"] = row["title"]
    elif task == "commongen":
        kwargs["concepts"] = row["concepts"]
    elif task == "responsegen":
        kwargs["context"] = row["context"]
    elif task in ("pie", "gsm"):
        kwargs.update({"slow_code" if task == "pie" else "question": row["input"],
                       "temperature": temperature, "feedback_type": feedback_type})
    else:
        kwargs.update({k: row[k] for k in ("review", "sentiment", "target_sentiment")})
        kwargs.update(record_id=row.get("record_id", 0), feedback_type=feedback_type)
    return fn(**kwargs)


def run_record(task, row, config, attempts=4, temperature=0.0, feedback_type="rich"):
    if attempts < 1:
        raise InferenceError("max_attempts must be positive.")
    if task == "readability" and config["variant"] == "A":
        raise InferenceError("Readability starts with supplied code and has no one-pass generator.")
    if task == "gsm" and config["variant"] == "C":
        raise InferenceError("GSM has no separate refinement stage; C would change its methodology.")
    terminal = sys.stdout
    show("ORIGINAL USER INPUT", row, terminal)
    iteration = [0]

    def on_output(stage, text):
        if stage == "generation":
            show("INITIAL GENERATION", text, terminal)
        elif stage in ("refinement", "feedback_refinement"):
            iteration[0] += 1
            show(f"REFINEMENT {iteration[0]}" + (" (combined feedback and rewrite)" if stage == "feedback_refinement" else ""), text, terminal)

    state = dict(config, calls=[], on_output=on_output,
                 on_fallback=lambda info: show("HF TO GROQ FALLBACK", info, terminal))
    marker = CURRENT.set(state)
    started = time.perf_counter()
    record = {"input": json.loads(redact(json.dumps(row))), "status": "error", "result": None, "final_output": None, "quality": None,
              "quality_status": "use existing task evaluator; no score fabricated"}
    try:
        # Legacy functions print prompts and partial summaries. Display a consistent
        # transcript through the callback instead, without modifying their logic.
        with contextlib.redirect_stdout(io.StringIO()):
            result = (one_pass(task, row, state, temperature) if config["variant"] == "A" else
                      iterative(task, row, attempts, temperature, feedback_type))
        if result is None:
            raise InferenceError("Pipeline exhausted its parsing retries.")
        result = json.loads(redact(json.dumps(result)))
        record.update(result=result, status="success", final_output=final_output(task, result, config["variant"]))
        if config["variant"] != "A":
            if task in ("acronym", "responsegen"):
                record["quality"] = [{"candidate": candidate, "score": details["total_score"],
                                      "feedback": details["scores"]} for candidate, details in result.items()]
            elif task == "commongen":
                record["quality"] = [{"concept_success": item["concept_feedback"][0].lower() == "none",
                                      "commonsense_success": item["commonsense_feedback"].lower() == "none"}
                                     for item in result]
            elif task == "sentiment_reversal":
                record["quality"] = [item["transferred_review_sentiment"] for item in result]
            if record["quality"] is not None:
                record["quality_status"] = "existing model-based feedback metric, not independent ground truth"
        show("FINAL OUTPUT", record["final_output"], terminal)
    except Exception as exc:
        record["status"] = "error"
        record["error"] = (redact(str(exc)) if isinstance(exc, InferenceError) else
                           "Experiment failed; inspect call statuses, task input format and required dependencies.")
        show("EXPERIMENT FAILED", record["error"], terminal)
    finally:
        record["latency_seconds"] = time.perf_counter() - started
        record["calls"] = state["calls"]
        CURRENT.reset(marker)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--task", choices=TASKS, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", help="Existing task inputs as JSONL")
    inputs.add_argument("--query", help="Single query; CommonGen uses space-separated concepts")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--feedback-type", default="rich")
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("max-attempts must be positive")
    config = configuration(args.config)
    if args.task == "gsm" and config["variant"] == "C":
        parser.error("GSM combines feedback and refinement; C is unsupported")
    if args.task == "readability" and config["variant"] == "A":
        parser.error("Readability starts with supplied code; one-pass generation is unsupported")
    if args.query is not None:
        if args.task == "sentiment_reversal":
            parser.error("Sentiment needs review/sentiment/target_sentiment fields; use --input JSONL")
        field = {"acronym": "title", "commongen": "concepts", "responsegen": "context"}.get(args.task, "input")
        row = {field: args.query.split() if args.task == "commongen" else args.query}
        data = (json.dumps(row) + "\n").encode("utf-8")
    else:
        data = Path(args.input).read_bytes()
    # Hash source and prompts, including local modifications and ignored prompt files.
    paths = list(Path("src").rglob("*.py")) + list(Path("prompt-lib/prompt_lib").rglob("*.py"))
    paths += [p for p in Path("data/prompt").rglob("*") if p.is_file()]
    manifest = {"run_id": str(uuid.uuid4()), "task": args.task, "configuration": config,
                "python": platform.python_version(), "input_sha256": hashlib.sha256(data).hexdigest(),
                "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
                "max_attempts": args.max_attempts, "temperature": args.temperature,
                "feedback_type": args.feedback_type,
                "file_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    with open(args.output, "x", encoding="utf-8") as out:
        failures = 0
        for line in data.decode("utf-8-sig").splitlines():
            if line.strip():
                result = run_record(args.task, json.loads(line), config, args.max_attempts,
                                    args.temperature, args.feedback_type)
                out.write(json.dumps(dict(result, experiment=manifest)) + "\n")
                out.flush()
                failures += result["status"] != "success"
    print(f"Saved results to {args.output}. Failed records: {failures}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
