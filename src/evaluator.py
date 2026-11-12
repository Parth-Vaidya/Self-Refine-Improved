"""Standalone evaluation runner for Phase 4: Performance, Telemetry, and Personalization Analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Dict, List, Optional

from prompt_lib.experiment import CURRENT
from src.chat_pipeline import ChatResponsePipeline
from src.output import redact


CONDITIONS = {
    "A": {
        "name": "Standard without personalization",
        "mode": "standard",
        "use_personalization": False,
    },
    "B": {
        "name": "Self-Refine without personalization",
        "mode": "self_refine",
        "use_personalization": False,
    },
    "C": {
        "name": "Standard with personalization",
        "mode": "standard",
        "use_personalization": True,
    },
    "D": {
        "name": "Self-Refine with personalization",
        "mode": "self_refine",
        "use_personalization": True,
    },
}

DEFAULT_PROMPTS_PATH = "evaluations/eval_prompts.json"
DEFAULT_PROFILE_PATH = "evaluations/test_profile.json"
DEFAULT_OUTPUT_PATH = "evaluations/phase_4_results.jsonl"


def run_single_evaluation(
    prompt_item: Dict[str, str],
    condition_key: str,
    pipeline: ChatResponsePipeline,
) -> Dict[str, object]:
    """Execute a single query under a specific condition and record full telemetry."""
    cond_meta = CONDITIONS[condition_key]
    mode = cond_meta["mode"]
    use_personalization = cond_meta["use_personalization"]
    query = prompt_item["query"]
    prompt_id = prompt_item["id"]
    category = prompt_item.get("category", "General")

    # Set up telemetry recording via prompt_lib CURRENT ContextVar
    calls_telemetry: List[Dict[str, object]] = []
    experiment_state = {
        "variant": "B",
        "original_model": pipeline.engine,
        "calls": calls_telemetry,
    }
    marker = CURRENT.set(experiment_state)

    start_time = time.perf_counter()
    status = "success"
    error_msg: Optional[str] = None
    response_text = ""

    try:
        # Context formatted as single user query turn
        context = f"User: {query}"
        response_text = pipeline.generate_chat_response(context, mode=mode)
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
    finally:
        elapsed = time.perf_counter() - start_time
        CURRENT.reset(marker)

    # Aggregate token counts across all calls made in this turn
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    for call in calls_telemetry:
        usage = call.get("usage") or {}
        prompt_tokens += usage.get("prompt_tokens", 0)
        completion_tokens += usage.get("completion_tokens", 0)
        total_tokens += usage.get("total_tokens", 0)

    # If telemetry didn't record usage (e.g. mock calls), fall back gracefully
    record = {
        "prompt_id": prompt_id,
        "category": category,
        "condition_key": condition_key,
        "condition_name": cond_meta["name"],
        "mode": mode,
        "personalization_enabled": use_personalization,
        "query": query,
        "response": response_text,
        "status": status,
        "error": error_msg,
        "telemetry": {
            "api_call_count": len(calls_telemetry),
            "latency_seconds": round(elapsed, 4),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "calls": calls_telemetry,
        },
        "evaluation_placeholders": {
            "correctness": None,
            "completeness": None,
            "clarity": None,
            "preference_adherence": None,
            "notes": "To be scored manually or via validation rubric.",
        },
    }
    return record


def run_evaluations(
    prompts_path: str | Path = DEFAULT_PROMPTS_PATH,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    conditions: Optional[List[str]] = None,
    limit_prompts: Optional[int] = None,
    engine: str = "groq:qwen/qwen3.8-27b",
    resume: bool = True,
) -> List[Dict[str, object]]:
    """Run comparative evaluation suite across specified conditions and prompts."""
    prompts_data = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    if limit_prompts:
        prompts_data = prompts_data[:limit_prompts]

    selected_conditions = conditions or ["A", "B", "C", "D"]
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, object]] = []
    completed_pairs: set[tuple[str, str]] = set()

    # Load existing valid completed records when resuming
    if resume and output_file.exists():
        try:
            content = output_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                    p_id = entry.get("prompt_id")
                    c_key = entry.get("condition_key")
                    if p_id and c_key and entry.get("status") == "success":
                        completed_pairs.add((str(p_id), str(c_key)))
                    results.append(entry)
                except Exception:
                    pass
        except Exception:
            pass

    if completed_pairs:
        print(f"Resuming evaluation: found {len(completed_pairs)} already completed prompt/condition pairs in {output_path}.")

    # Two pipelines: one with personalization profile, one with a dummy non-existent profile
    pipeline_personalized = ChatResponsePipeline(
        engine=engine,
        max_attempts=2,
        profile_path=profile_path,
    )
    pipeline_unpersonalized = ChatResponsePipeline(
        engine=engine,
        max_attempts=2,
        profile_path=Path("non_existent_profile.json"),
    )

    open_mode = "a" if resume else "w"
    with output_file.open(open_mode, encoding="utf-8") as out_stream:
        # If appending to existing content lacking trailing newline, ensure separator
        if resume and output_file.exists() and output_file.stat().st_size > 0:
            existing = output_file.read_text(encoding="utf-8")
            if existing and not existing.endswith("\n"):
                out_stream.write("\n")

        for prompt_item in prompts_data:
            p_id = prompt_item["id"]
            for cond_key in selected_conditions:
                if (str(p_id), str(cond_key)) in completed_pairs:
                    print(f"Skipping already completed [{p_id}] Condition [{cond_key}]")
                    continue

                print(f"Evaluating Prompt [{p_id}] Condition [{cond_key}]: {prompt_item['query'][:50]}...")
                cond = CONDITIONS[cond_key]
                pipeline = pipeline_personalized if cond["use_personalization"] else pipeline_unpersonalized
                record = run_single_evaluation(prompt_item, cond_key, pipeline)
                results.append(record)
                completed_pairs.add((str(p_id), str(cond_key)))
                safe_json = redact(json.dumps(record, ensure_ascii=False))
                out_stream.write(safe_json + "\n")
                out_stream.flush()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", default=DEFAULT_PROMPTS_PATH, help="Path to prompts JSON")
    parser.add_argument("--profile", default=DEFAULT_PROFILE_PATH, help="Path to test user profile JSON")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Path to output JSONL")
    parser.add_argument("--conditions", nargs="+", choices=["A", "B", "C", "D"], help="Conditions to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of prompts (e.g. 1 for smoke test)")
    parser.add_argument("--engine", default="groq:qwen/qwen3.8-27b", help="Model engine identifier")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output instead of resuming")
    args = parser.parse_args()

    results = run_evaluations(
        prompts_path=args.prompts,
        profile_path=args.profile,
        output_path=args.output,
        conditions=args.conditions,
        limit_prompts=args.limit,
        engine=args.engine,
        resume=not args.overwrite,
    )
    print(f"\nEvaluations completed: {len(results)} total execution records in {args.output}")


if __name__ == "__main__":
    main()

