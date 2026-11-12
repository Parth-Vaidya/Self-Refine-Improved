# Phase 4 Evaluation Framework (`evaluations/`)

This directory contains the benchmarking dataset, test profile configuration, raw execution outputs, and reporting infrastructure for **Phase 4: Evaluation and Performance Analysis**.

> [!IMPORTANT]
> **Performance evaluation and comparative analysis are pending completion of the full experimental run.**
> The evaluation framework, prompt sets, telemetry recording, and reporting scripts are fully implemented and verified. Final empirical performance conclusions, latency multiplier tables, and token overhead analyses will be generated once the full 48-combination live evaluation run finishes.

---

## 1. Experimental Design & Configurations

The evaluation compares four controlled configurations:

| Configuration | Description | Mode | Personalization Profile | Purpose |
|:---:|---|---|---|---|
| **A** | Standard without personalization | `standard` (1-pass) | Disabled / None | Baseline performance and standard one-pass resource footprint. |
| **B** | Self-Refine without personalization | `self_refine` (iterative) | Disabled / None | Standard Self-Refine token and latency baseline. |
| **C** | Standard with personalization | `standard` (1-pass) | Enabled (`test_profile.json`) | Measures token and prompt overhead introduced by style instructions alone. |
| **D** | Self-Refine with personalization | `self_refine` (iterative) | Enabled (`test_profile.json`) | Evaluates whether iterative refinement adheres to personalized constraints and measures joint overhead. |

---

## 2. Benchmark Prompt Dataset

The evaluation suite uses 12 standardized prompts defined in [`eval_prompts.json`](eval_prompts.json) across three distinct cognitive domains:

### A. Programming (4 Prompts)
- `prog_01`: Palindrome verification ignoring punctuation and case.
- `prog_02`: Internal mechanics of Python dictionary hash collisions.
- `prog_03`: Kadane's algorithm for maximum subarray sum.
- `prog_04`: Deep copy vs. shallow copy mechanics and memory illustrations.

### B. Theoretical Concepts (4 Prompts)
- `theo_01`: Newton's third law and why action/reaction pairs do not cancel.
- `theo_02`: Transport layer trade-offs between TCP and UDP (handshakes, reliability).
- `theo_03`: Thermodynamic vs. information-theoretic entropy comparisons.
- `theo_04`: CAP theorem trade-offs in distributed systems architecture.

### C. Reasoning (4 Prompts)
- `reas_01`: Cognitive Reflection Test (bat and ball algebraic word problem).
- `reas_02`: Syllogistic logic analysis ("some roses fade quickly").
- `reas_03`: Water jug riddle (3-gallon and 5-gallon jugs to measure 4 gallons).
- `reas_04`: Monty Hall problem conditional probability breakdown.

---

## 3. Evaluation Files & Artifacts

- **[`eval_prompts.json`](eval_prompts.json)**: The 12 canonical test prompts.
- **[`test_profile.json`](test_profile.json)**: The standardized user profile activating `prefers_step_by_step`, `prefers_simple_code`, and `prefers_examples` for Conditions C and D.
- **`smoke_test_results.jsonl`**: Single-prompt smoke test archive verifying end-to-end telemetry and JSONL serialization.
- **`phase_4_results.jsonl`**: Destination file storing raw evaluation records across all 48 combinations ($12 \text{ prompts} \times 4 \text{ conditions}$).
- **`PHASE_4_EVALUATION_REPORT.md`**: Generated comparative Markdown summary report produced from `phase_4_results.jsonl`.

---

## 4. Execution & Resume Mechanism

### Running the Full Evaluation
To run all 12 prompts across all 4 conditions (48 total executions):

```powershell
$env:PYTHONPATH = ".;prompt-lib"
.venv-research\Scripts\python.exe -m src.evaluator --output evaluations/phase_4_results.jsonl
```

### Resume Capability
Because live LLM APIs (e.g. Groq free tier) may experience rate limits (HTTP 429), the evaluator incorporates an automated **resume mechanism**:
- When launched, `src/evaluator.py` inspects `evaluations/phase_4_results.jsonl`.
- It identifies and skips all `(prompt_id, condition_key)` combinations that already completed successfully.
- It opens the output file in append mode (`"a"`), guaranteeing previously completed runs are **never overwritten or duplicated**.
- If a run is interrupted by `KeyboardInterrupt` or a network timeout, re-running the same command seamlessly continues only the missing evaluations.

To force a clean run from scratch, pass `--overwrite`:
```powershell
.venv-research\Scripts\python.exe -m src.evaluator --output evaluations/phase_4_results.jsonl --overwrite
```

### Generating the Report
Once records are written to `phase_4_results.jsonl`, generate the comparative report:

```powershell
.venv-research\Scripts\python.exe -m src.eval_report --results evaluations/phase_4_results.jsonl --output evaluations/PHASE_4_EVALUATION_REPORT.md
```

---

## 5. Response Quality Rubric

Responses are judged qualitatively using four standardized criteria:
1. **Correctness**: Accuracy of facts, algorithmic logic, mathematics, and code syntax.
2. **Completeness**: Thorough addressing of all query requirements and edge cases.
3. **Clarity & Structure**: Formatting, readability, and structural coherence.
4. **Preference Adherence**: In conditions C and D, whether the output properly adopted the requested style (step-by-step breakdowns, clean code, practical examples).

