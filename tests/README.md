# Test Suite (`tests/`)

This directory contains the unit, integration, and offline regression tests for the project.

---

## Test Philosophy

1. **Hermetic & Isolated**: Tests run offline without requiring live LLM API keys or making outbound network calls. External network interactions are mocked via `unittest.mock`.
2. **Telemetry Validation**: Tests verify that call telemetry (`prompt_tokens`, `completion_tokens`, `latency_seconds`, and stage sequences) are tracked authentically through `prompt_lib.experiment.observed_call`.
3. **No Credential Leakage**: Tests assert that secret keys (`HF_TOKEN`, `GROQ_API_KEY`, etc.) are never leaked in exception traces or output records.

---

## Test Module Descriptions

| Test File | Target Module | Scope & Key Behaviors Verified |
|---|---|---|
| `test_conversation_manager.py` | `src/conversation_manager.py` | Creation of unique sequential IDs (`chat_001.txt`, `chat_002.txt`), saving/loading multi-turn histories, mode tagging (`[mode: standard]`, `[mode: self_refine]`), title generation, and context truncation limits. |
| `test_chat_app.py` | `src/chat_app.py` | CLI navigation, main menu actions (new chat, continue chat, exit), mode prompt selection (1 for Standard, 2 for Self-Refine), auto-titling, and graceful handling of EOF/KeyboardInterrupt. |
| `test_chat_pipeline.py` | `src/chat_pipeline.py` | `ChatResponsePipeline` generation, single-pass Standard execution, multi-turn Self-Refine loops, score parsing, convergence early stopping ($\ge 9/10$), stop token propagation, failure fallbacks, and profile personalization instruction formatting. |
| `test_preference_extractor.py` | `src/preference_extractor.py` | Regex/keyword rule matching for style preferences, extraction across chat logs in `chats/`, profile updating without duplicates, and preservation of manual user edits. |
| `test_evaluator.py` | `src/evaluator.py`, `src/eval_report.py` | Phase 4 evaluation pipeline, authentic telemetry recording via `GroqAPIWrapper.call` mock, resume logic (skipping completed combinations), JSONL serialization, and comparative Markdown report generation. |
| `test_groq_fallback.py` | `prompt_lib/backends/` | Provider switching from Hugging Face to Groq upon HTTP 402/429, retry delays, rate-limit isolation, and safe termination upon provider exhaustion. |
| `test_inference.py` | `src/experiment.py`, `prompt_lib/` | Legacy benchmark task routing (acronym, commongen, gsm, pie, readability, responsegen, sentiment_reversal), Gemini/HF adapter calls, and CommonGen spaCy/NLTK concept detection. |

---

## Running the Tests

Ensure your virtual environment is activated and `PYTHONPATH` includes both the project root and `prompt-lib`:

### Windows (PowerShell)

```powershell
$env:PYTHONPATH = ".;prompt-lib"

# Run the complete test suite
.venv-research\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# Run an individual test module
.venv-research\Scripts\python.exe -m unittest tests.test_evaluator -v
.venv-research\Scripts\python.exe -m unittest tests.test_chat_pipeline -v
.venv-research\Scripts\python.exe -m unittest tests.test_preference_extractor -v
.venv-research\Scripts\python.exe -m unittest tests.test_conversation_manager -v
.venv-research\Scripts\python.exe -m unittest tests.test_chat_app -v
.venv-research\Scripts\python.exe -m unittest tests.test_groq_fallback -v
.venv-research\Scripts\python.exe -m unittest tests.test_inference -v
```

### Linux / macOS (Bash)

```bash
export PYTHONPATH=".:prompt-lib"
python -m unittest discover -s tests -p "test_*.py" -v
```

