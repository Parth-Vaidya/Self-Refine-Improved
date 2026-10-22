"""Opt-in stage selection and credential-free experiment telemetry."""
import hashlib
import json
import os
import time
from contextvars import ContextVar

from prompt_lib.backends.huggingface_api import InferenceError

CURRENT = ContextVar("self_refine_experiment", default=None)
CALL_STAGE = ContextVar("self_refine_call_stage", default=None)


def select_model(stage, original):
    config = CURRENT.get()
    if config is None or stage is None:
        return original
    variant = config["variant"]
    if stage == "feedback_refinement" and variant == "C":
        raise InferenceError("GSM combines feedback and refinement; configuration C is unsupported.")
    if variant == "A" and stage != "generation":
        raise InferenceError("One-pass configuration cannot invoke feedback or refinement.")
    if variant == "B":
        return config["original_model"]
    if stage == "refinement" and variant == "C":
        return config["refinement_model"]
    return config.get(stage + "_model", config["original_model"])


def observed_call(call, stage, engine, **kwargs):
    config = CURRENT.get()
    if config is None:
        return call(engine=engine, **kwargs)
    started = time.perf_counter()
    record = {"stage": stage, "requested_model": engine,
              "prompt_sha256": hashlib.sha256(json.dumps(kwargs.get("prompt"), sort_keys=True).encode()).hexdigest(),
              "settings": {k: kwargs[k] for k in ("max_tokens", "temperature", "top_p", "stop_token", "num_completions") if k in kwargs},
              "usage": None, "cost_usd": None, "cost_kind": "unavailable", "status": "error"}
    if "gemini" in engine.lower():
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        record["effective_model"] = GeminiAPIWrapper._normalize_engine_name(engine)
        record["effective_max_tokens"] = max(kwargs.get("max_tokens") or 2048, 2048)
    else:
        record["effective_model"] = engine
        record["effective_max_tokens"] = kwargs.get("max_tokens")
    stage_marker = CALL_STAGE.set(stage)
    try:
        result = call(engine=engine, **kwargs)
        record["status"] = "success"
        usage = result.get("usage") or {}
        record["usage"] = {k: v for k, v in usage.items() if k in
                           ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, int) and v >= 0} or None
        record["inference"] = result.get("inference")
        actual_model = result.get("model", engine)
        if (record["inference"] or {}).get("fallback"):
            record["effective_model"] = actual_model
            record["fallback"] = record["inference"]["fallback"]
            if config.get("on_fallback"):
                config["on_fallback"](record["fallback"])
        rate = config.get("prices", {}).get(actual_model)
        if rate and all(k in usage for k in ("prompt_tokens", "completion_tokens")):
            record["cost_usd"] = (usage["prompt_tokens"] * rate["input_per_million"] +
                                  usage["completion_tokens"] * rate["output_per_million"]) / 1e6
            record["cost_kind"] = "estimate"
            record["price_basis"] = rate
        if config.get("on_output") and stage in ("generation", "refinement", "feedback_refinement"):
            choice = result.get("choices", [{}])[0]
            content = choice.get("text") or (choice.get("message") or {}).get("content", "")
            config["on_output"](stage, content)
        return result
    except InferenceError as exc:
        record["status"] = "error"
        record["error"] = str(exc)
        if exc.fallback:
            record["fallback"] = exc.fallback
            record["effective_model"] = exc.fallback["to_model"]
            if config.get("on_fallback"):
                config["on_fallback"](exc.fallback)
        raise
    except Exception:
        # Existing runners print exceptions. Do not let provider exceptions escape experiments.
        raise InferenceError("Model request failed; consult the credential-free call record.") from None
    finally:
        CALL_STAGE.reset(stage_marker)
        record["latency_seconds"] = time.perf_counter() - started
        config["calls"].append(record)
