"""Hugging Face Inference Providers chat adapter (no global SDK credentials)."""
import os
import time
from collections import Counter

import requests

ENDPOINT = "https://router.huggingface.co/v1/chat/completions"


class InferenceError(RuntimeError):
    """Safe to display: never includes a request, response body or underlying exception."""

    def __init__(self, message, status_code=None, attempts=None, fallback=None):
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts
        self.fallback = fallback


class HostedChatAPIWrapper:
    """Shared transport; each provider has isolated credentials and settings."""
    label = "HF"
    env_prefix = "HF"
    token_env = "HF_TOKEN"
    engine_prefix = "hf:"
    endpoint = ENDPOINT

    @classmethod
    def before_attempt(cls):
        pass

    @classmethod
    def call(cls, prompt, max_tokens=300, engine=None, stop_token=None,
             temperature=0.7, num_completions=1, system_message=None,
             top_p=1.0, logprobs=None, **kwargs):
        token = os.getenv(cls.token_env)
        if not token:
            raise InferenceError(cls.token_env + " is not configured.")
        try:
            timeout = float(os.getenv(cls.env_prefix + "_TIMEOUT", "60"))
            retries = int(os.getenv(cls.env_prefix + "_MAX_RETRIES", "2"))
            if not 0 < timeout <= 600 or not 0 <= retries <= 5:
                raise ValueError()
        except (ValueError, TypeError):
            raise InferenceError("Invalid " + cls.label + " timeout or retry configuration.") from None
        if cls.label == "Groq":
            retries = 5 if os.getenv("GROQ_RESUME_ON_RATE_LIMIT", "false").lower() == "true" else 0
        if kwargs or num_completions != 1 or logprobs is not None:
            raise InferenceError(cls.label + " adapter requires one completion and no legacy logprobs or extra options.")
        model = (engine or "").removeprefix(cls.engine_prefix)
        if not model or not (engine or "").startswith(cls.engine_prefix) or (cls.label == "HF" and ":" not in model):
            raise InferenceError("Invalid " + cls.label + " engine identifier.")
        messages = ([{"role": "user", "content": prompt}] if isinstance(prompt, str)
                    else [dict(m) for m in prompt])
        if system_message:
            messages.insert(0, {"role": "system", "content": system_message})
        payload = dict(model=model, messages=messages, max_tokens=max_tokens,
                       temperature=temperature, top_p=top_p, stream=False)
        if stop_token:
            payload["stop"] = [stop_token] if isinstance(stop_token, str) else stop_token
        started = time.perf_counter()
        for attempt in range(retries + 1):
            retry_after = 0
            cls.before_attempt()
            from prompt_lib.backends.request_budget import reserve
            try:
                reserve()
            except Exception:
                raise InferenceError("Request budget unavailable or exhausted (hard limit: 700).") from None
            try:
                response = requests.post(cls.endpoint, headers={"Authorization": "Bearer " + token},
                                         json=payload, timeout=timeout, allow_redirects=False)
                status = response.status_code
                if status == 200:
                    try:
                        data = response.json()
                        content = data["choices"][0]["message"]["content"]
                        if not isinstance(content, str) or not content.strip() or token in content:
                            raise ValueError()
                        usage = data.get("usage") or {}
                        usage = {k: v for k, v in usage.items() if k in
                                 ("prompt_tokens", "completion_tokens", "total_tokens")
                                 and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
                        finish = data["choices"][0].get("finish_reason")
                        if finish not in ("stop", "length", "content_filter", None):
                            finish = None
                        # Return only allowed fields; never propagate arbitrary provider data.
                        return {"model": engine, "choices": [{"message": {"role": "assistant", "content": content},
                                "text": content, "finish_reason": finish}], "usage": usage,
                                "inference": {"provider": model.rsplit(":", 1)[1] if cls.label == "HF" else "groq",
                                    "attempts": attempt + 1, "latency_seconds": time.perf_counter() - started,
                                    "timeout": timeout, "max_retries": retries}}
                    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                        raise InferenceError(cls.label + " returned an invalid or empty completion.") from None
                    finally:
                        response.close()
                try:
                    if cls.label == "Groq" and status == 429 and attempt < retries:
                        from prompt_lib.backends.groq_pacing import retry_delay
                        retry_after = retry_delay(response.headers.get("Retry-After"), status)
                    elif cls.label != "Groq":
                        retry_after = min(60, max(0, float(response.headers.get("Retry-After", 0))))
                except InferenceError:
                    response.close()
                    raise
                except (ValueError, TypeError):
                    pass
                response.close()
                retryable = status in (408, 429, 500, 502, 503, 504)
                message = cls.label + {401: " authentication failed.", 402: " payment required; check account credits and provider billing.", 403: " access denied; check inference permission.",
                           404: " model or provider is unavailable.", 429: " rate limit exceeded."}.get(
                               status, " inference request failed (HTTP %d)." % status)
            except (requests.Timeout, requests.ConnectionError):
                status = None
                retryable, message = True, cls.label + " request timed out or could not connect."
            except requests.RequestException:
                status = None
                retryable, message = False, cls.label + " transport request failed."
            if cls.label == "Groq" and status != 429:
                retryable = False
            if not retryable or attempt == retries:
                raise InferenceError(message, status_code=status, attempts=attempt + 1) from None
            if cls.label == "Groq":
                from prompt_lib.backends.groq_pacing import wait
                wait(max(retry_after, 1))
            else:
                time.sleep(max(retry_after, min(2 ** attempt, 30)))

    @staticmethod
    def get_first_response(response):
        return response["choices"][0]["message"]["content"]

    @staticmethod
    def get_all_responses(response):
        return [{"generated_answer": c["message"]["content"], "logprobs": None}
                for c in response["choices"]]

    @staticmethod
    def get_majority_answer(response):
        return Counter(c["message"]["content"] for c in response["choices"]).most_common(1)[0][0]


class HuggingFaceAPIWrapper(HostedChatAPIWrapper):
    @classmethod
    def call(cls, *args, **kwargs):
        try:
            return super().call(*args, **kwargs)
        except InferenceError as primary:
            # Lazy imports avoid a cycle: experiment telemetry imports InferenceError.
            from prompt_lib.experiment import CURRENT, CALL_STAGE
            config = CURRENT.get() or {}
            enabled = config.get("hf_groq_fallback", os.getenv("HF_GROQ_FALLBACK", "false").lower() == "true")
            # A/B are strict baselines. In C only refinement may switch providers.
            if config and (config.get("variant") != "C" or CALL_STAGE.get() != "refinement"):
                enabled = False
            if not enabled or primary.status_code not in (402, 429):
                raise
            if not os.getenv("GROQ_API_KEY"):
                raise InferenceError(str(primary) + " Groq fallback unavailable: GROQ_API_KEY is not configured.",
                                     status_code=primary.status_code, attempts=primary.attempts) from None
            from prompt_lib.backends.groq_api import GroqAPIWrapper
            # Bind positional arguments as well as keywords before changing only the model.
            import inspect
            bound = inspect.signature(HostedChatAPIWrapper.call).bind(*args, **kwargs)
            options = dict(bound.arguments)
            options.update(options.pop("kwargs", {}))
            requested = options.get("engine")
            options["engine"] = config.get("groq_model") or "groq:" + os.getenv("GROQ_MODEL_ID", "openai/gpt-oss-20b").removeprefix("groq:")
            fallback = {"from_model": requested, "to_model": options["engine"],
                "reason_http_status": primary.status_code, "primary_attempts": primary.attempts,
                "primary_usage": None, "primary_cost_usd": None}
            try:
                result = GroqAPIWrapper.call(**options)
            except InferenceError as secondary:
                raise InferenceError("HF quota failure (HTTP %d); Groq fallback failed: %s" %
                                     (primary.status_code, str(secondary)), status_code=secondary.status_code,
                                     attempts=secondary.attempts, fallback=fallback) from None
            result["inference"]["fallback"] = fallback
            return result
