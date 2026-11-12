# Interactive Chat Response Generation Report

## 1. Actual Root Causes of Observed Errors

### Error 1: `InferenceError: Dialogue feedback did not provide a valid total score.`
- **Location:** `src/responsegen/parsing.py:15-20`, called by `src/responsegen/feedback.py:81-83`.
- **Root Cause:**
  `src/responsegen/` is the benchmark-specific pipeline for the dialogue response dataset (fed_data). Its feedback prompt uses few-shot examples that force the model to output a strict rubric of 10 traits and a regex-matchable string `Total score: X/Y`. When used for general conversational chat, the model frequently replies with natural qualitative feedback (e.g. *"The response is polite and informative. Total score: 8 out of 10"* or without an exact integer fractional score).
  `feedback_text()` in `src/responsegen/parsing.py` immediately raises `InferenceError("Dialogue feedback did not provide a valid total score.")` whenever this rigid format is not matched, crashing the entire chat turn.
- **Why it was inappropriate for interactive chat:**
  Interactive conversations are open-ended and do not conform to fixed dialogue benchmark rubrics. Coupling interactive chat directly to `src/responsegen/run.py` was fragile because any divergence in model feedback format aborted generation instead of delivering a response to the user.

### Error 2: `InferenceError: Groq rate limit exceeded.`
- **Location:** `prompt_lib/backends/huggingface_api.py:47-48, 122-124`.
- **Root Cause:**
  In `HostedChatAPIWrapper.call()`:
  ```python
  if cls.label == "Groq":
      retries = 5 if os.getenv("GROQ_RESUME_ON_RATE_LIMIT", "false").lower() == "true" else 0
  ```
  `GROQ_RESUME_ON_RATE_LIMIT` was only set by `run-query.ps1` for batch queries, but was **unset** by default when launching `python -m src.chat_app` directly in Python. Consequently, `retries` defaulted to `0`. Any initial Groq HTTP 429 immediately raised `InferenceError("Groq rate limit exceeded.")` without using Groq's `Retry-After` header or waiting for the rate limit cooldown.

---

## 2. Architecture: Dedicated Interactive Chat Pipeline vs. Benchmark Pipeline

To cleanly resolve both issues without touching benchmark evaluation or prompts:
- **Dedicated Interactive Pipeline:** Created `src/chat_pipeline.py` (`ChatResponsePipeline`).
  - **Generation:** Generates initial responses directly from multi-turn conversation history using the configured Qwen model (`groq:qwen/qwen3.8-27b`).
  - **Iterative Refinement:** Generates feedback on relevance, clarity, and tone, then produces a refined version if needed.
  - **Fault-Tolerant Feedback Parsing (`parse_chat_feedback`):** Extracts numerical score when present, but gracefully falls back to qualitative feedback without failing the turn.
  - **Resilience:** If feedback generation or refinement fails (e.g. rate limit during refinement), the pipeline **preserves and returns the initial response** rather than failing.
- **Rate-Limit Resilience:** In `src/chat_app.py`, `GROQ_RESUME_ON_RATE_LIMIT` is set to `"true"` by default on app launch, activating Groq's automatic exponential pacing and `Retry-After` recovery. Furthermore, user-facing error handling translates any remaining rate-limit exceptions into clear, friendly messages (*"Groq rate limit reached. The service is temporarily busy; please wait a moment and try again."*) while preserving the user's input in the conversation file.
- **Benchmark Preservation:** The benchmark pipeline (`src/experiment.py`, `src/responsegen/run.py`, `src/responsegen/parsing.py`, `experiments/B-qwen-groq.json`) remains completely intact and unmodified.

---

## 3. Files Created and Modified

| File | Status | Description |
|---|---|---|
| `src/chat_pipeline.py` | **Created** | Implements `ChatResponsePipeline` and `parse_chat_feedback` with robust refinement and graceful fallback. |
| `src/chat_app.py` | **Modified** | Updated `default_generate_response()` to use `ChatResponsePipeline`, added user-friendly error notices for provider rate limits / credentials, enabled `GROQ_RESUME_ON_RATE_LIMIT="true"`. |
| `tests/test_chat_pipeline.py` | **Created** | Unit tests for normal messages, multi-turn context, malformed feedback fallback, refinement cycles, and rate limit during refinement. |
| `tests/test_chat_app.py` | **Modified** | Updated mock integration test and added rate-limit persistence test. |

---

## 4. Models and Providers Used

- **Model:** `groq:qwen/qwen3.8-27b`
- **Provider:** Groq hosted inference via existing `prompt_lib.backends.groq_api.GroqAPIWrapper`
- Consistent with the workspace's primary Qwen/Groq configuration; no other providers introduced.

---

## 5. Verification Commands

Run the test suites locally in PowerShell:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'

# 1. New chat pipeline tests
.\.venv-research\Scripts\python.exe -m unittest tests.test_chat_pipeline -v

# 2. Conversation manager & CLI app tests
.\.venv-research\Scripts\python.exe -m unittest tests.test_conversation_manager tests.test_chat_app -v

# 3. Existing benchmark suites (confirming zero regressions)
.\.venv-research\Scripts\python.exe -m unittest tests.test_partial_dialogue tests.test_resume_pipeline tests.test_inference -v

# 4. Full test discovery
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
```

