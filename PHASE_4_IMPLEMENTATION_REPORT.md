# Phase 4 Implementation & Evaluation Guide

## 1. Overview of Phase 4 Implementation

Phase 4 implements a standalone, reproducible evaluation framework comparing four experimental conditions across 12 standardized questions:

- **Condition A:** Standard generation without personalization
- **Condition B:** Self-Refine generation without personalization
- **Condition C:** Standard generation with personalization
- **Condition D:** Self-Refine generation with personalization

The implementation is completely decoupled from existing benchmark datasets, production chat files, and Phase 2 preference extraction.

---

## 2. Files Created and Modified

| File | Status | Description |
|---|---|---|
| `evaluations/eval_prompts.json` | **Created** | 12 standardized evaluation prompts across Programming (4), Theoretical Concepts (4), and Reasoning (4). |
| `evaluations/test_profile.json` | **Created** | Standardized evaluation profile with enabled style preferences (`prefers_step_by_step`, `prefers_simple_code`, `prefers_examples`). |
| `src/evaluator.py` | **Created** | Standalone evaluation runner that wraps calls in `prompt_lib.experiment.observed_call()` to record call counts, latency, and input/output tokens, saving records to JSONL. |
| `src/eval_report.py` | **Created** | Generates a Markdown summary comparing latencies, token overheads, API call counts, and response samples across conditions. |
| `tests/test_evaluator.py` | **Created** | Unit test suite testing telemetry capture, JSONL output persistence, and report generation using mocked model calls (0 tokens). |

---

## 3. Telemetry and Quality Evaluation Design

### Telemetry Recorded
- `prompt_id` and `category`
- `condition_key` (`A`, `B`, `C`, `D`) and `condition_name`
- `query` and full `response`
- `status` (`success` / `error`) and `error` details if any
- `telemetry`:
  - `latency_seconds`: Wall-clock elapsed time
  - `prompt_tokens`: Input tokens
  - `completion_tokens`: Output tokens
  - `total_tokens`: Total tokens
  - `api_call_count`: Total API roundtrips
  - `calls`: Detailed per-stage call logs

### Quality Evaluation Dimensions
Rather than fabricating automated scores, placeholders are saved with clear criteria:
1. **Correctness:** Factual and syntactic accuracy of algorithms, equations, and logic.
2. **Completeness:** Addressing all constraints and edge cases.
3. **Clarity:** Readability, structure, and coherence.
4. **Preference Adherence:** Verification that Conditions C and D adhered to active profile directives.

---

## 4. Execution Instructions

### Step 1: Run the Unit Tests (Mocked, 0 API Calls)
```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'

.\.venv-research\Scripts\python.exe -m unittest tests.test_evaluator -v
```

### Step 2: Run a Small Smoke Test (1 Prompt, All 4 Conditions = 4 Total Calls)
Before launching all 12 prompts, execute a smoke test on a single prompt to verify live API connectivity and telemetry logging:
```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:GROQ_RESUME_ON_RATE_LIMIT = 'true'

.\.venv-research\Scripts\python.exe -m src.evaluator --limit 1 --output evaluations/smoke_test_results.jsonl
.\.venv-research\Scripts\python.exe -m src.eval_report --results evaluations/smoke_test_results.jsonl --output evaluations/SMOKE_TEST_REPORT.md
```

### Step 3: Run the Complete Evaluation (12 Prompts x 4 Conditions = 48 Executions)
Once the smoke test completes cleanly:
```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:GROQ_RESUME_ON_RATE_LIMIT = 'true'

.\.venv-research\Scripts\python.exe -m src.evaluator --output evaluations/phase_4_results.jsonl
.\.venv-research\Scripts\python.exe -m src.eval_report --results evaluations/phase_4_results.jsonl --output evaluations/PHASE_4_EVALUATION_REPORT.md
```

