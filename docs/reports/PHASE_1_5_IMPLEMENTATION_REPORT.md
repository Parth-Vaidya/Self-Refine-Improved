# Phase 1.5 Implementation Report: Standard vs Self-Refine Response Mode

## 1. Overview and Architecture

Phase 1.5 adds per-message response mode selection to the interactive chat application:
- **Standard Response:** Fast, cost-efficient, single-pass generation. Skips feedback and refinement entirely.
- **Self-Refine Response:** Multi-turn iterative self-refinement via `ChatResponsePipeline`, with graceful fallback to the initial answer if feedback or refinement fails.

The selection is requested dynamically after the user types each query:
```text
How would you like to generate your response?
1. Standard Response
2. Self-Refine Response
Select an option (1 or 2):
```
This choice applies only to the current turn. The prompt repeats for each subsequent message.

---

## 2. Files Modified and Created

| File | Status | Description |
|---|---|---|
| `src/chat_pipeline.py` | **Modified** | Updated `generate_chat_response(context, mode="self_refine")`. When `mode == "standard"`, only `generate_initial()` is called; feedback and refinement APIs are never invoked. |
| `src/conversation_manager.py` | **Modified** | Updated `save_message(..., mode=None)` and `_format_file` / `_parse_file` to support optional `[mode: standard]` or `[mode: self_refine]` headers on message turns. Older `.txt` files without mode tags remain fully readable. |
| `src/chat_app.py` | **Modified** | Added `_prompt_response_mode()` loop to prompt the user after each query. Passes selected mode to `save_message()` and to `response_fn()`. Displays mode in recent conversation history recap. |
| `tests/test_chat_pipeline.py` | **Modified** | Added tests verifying that Standard mode calls only initial generation and never invokes feedback or refinement, and that Self-Refine mode executes all stages. |
| `tests/test_conversation_manager.py` | **Modified** | Added tests verifying saving/loading mode metadata and backward compatibility with older `.txt` files lacking mode tags. |
| `tests/test_chat_app.py` | **Modified** | Updated interactive tests to verify mode selection input and per-message mode persistence across sessions. |

---

## 3. How Standard Mode Bypasses Refinement

In `ChatResponsePipeline.generate_chat_response(context: str, mode: str = "self_refine")`:
1. `generate_initial(context)` calls `_call_model(prompt, stage="generation", stop_token=None)` using the configured Qwen model (`groq:qwen/qwen3.8-27b`).
2. If `mode == "standard"`, the method **immediately returns `initial_response`**.
3. Neither `get_feedback()` nor `refine()` is called, saving tokens, API calls, latency, and request budget for ordinary or casual questions.

---

## 4. How Self-Refine Mode Works

When `mode == "self_refine"`:
1. `generate_initial(context)` generates the candidate response.
2. `get_feedback(context, current_best)` generates critique and numerical rating.
3. If feedback indicates the draft is already top-tier (`score >= 9` or `Critique Summary: None`), refinement terminates early.
4. Otherwise, `refine(context, current_best, feedback)` produces an improved candidate.
5. If feedback generation, parsing, or refinement encounters an issue (e.g. temporary rate limit), the pipeline gracefully preserves and returns `initial_response`.

---

## 5. How Response Modes Are Saved and Restored

In `chats/chat_NNN.txt`, user turns now record the selected mode in the message header:
```text
[2026-11-12 22:20:00] USER [mode: standard]:
What is the boiling point of water?

[2026-11-12 22:20:03] ASSISTANT:
The boiling point of water is 100°C (212°F) at standard atmospheric pressure.

[2026-11-12 22:21:00] USER [mode: self_refine]:
Can you explain the thermodynamic derivation of the Clausius-Clapeyron equation?

[2026-11-12 22:21:15] ASSISTANT:
...
```

- **Backward Compatibility:** `MESSAGE_HEADER_RE` uses `(?: \[mode: ([a-zA-Z0-9_-]+)\])?` so older `.txt` files without `[mode: ...]` continue to parse cleanly with `msg.get("mode") == None`.
- **Isolation:** Each conversation maintains its own independent history and modes; messages and modes are never mixed across different conversation files.

---

## 6. Constraints Preserved

- The three-option CLI menu (`1. Start a New Chat`, `2. Continue Previous Chat`, `3. Exit`) remains unchanged.
- No new providers or models were introduced (`groq:qwen/qwen3.8-27b` remains the sole model).
- A/B/C benchmark methodology, prompts, and task runners remain untouched.
- No SQLite, GUI, or premature preference extraction was added.

---

## 7. Verification Commands

Run locally in PowerShell:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'

# 1. Targeted Phase 1 & 1.5 tests
.\.venv-research\Scripts\python.exe -m unittest tests.test_chat_pipeline tests.test_chat_app tests.test_conversation_manager -v

# 2. Existing benchmark test suites
.\.venv-research\Scripts\python.exe -m unittest tests.test_partial_dialogue tests.test_resume_pipeline tests.test_inference -v

# 3. Full discovery test suite
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
```

