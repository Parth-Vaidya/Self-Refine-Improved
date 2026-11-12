# Test Failure Investigation and Dependency Fix Report

## Executive Summary

The test failures across the test suite were traced to two specific dependency and import issues at runtime:
1. `pandarallel` incompatibility with pandas 2.x in `src/responsegen/run.py` and `src/sentiment_reversal/run.py` (which caused `ImportError` on module loading for tests involving these tasks).
2. Eager module-import loading of spaCy's `en_core_web_sm` model in `src/commongen/feedback.py`.

Smallest safe fixes were implemented for both issues without changing experimental methodology, prompts, test assertions, model routing, or the Conversation Manager.

---

## 1. Issue 1: `pandarallel` / `pandas` Incompatibility in `src/responsegen/run.py` and `src/sentiment_reversal/run.py`

### Symptoms & Root Cause
- **Affected Tests:**
  - `tests.test_partial_dialogue` (all 4 tests):
    - `test_rate_limit_after_refinement_preserves_both_answers`
    - `test_initial_feedback_failure_keeps_initial_answer`
    - `test_refinement_failure_keeps_scored_answer`
    - `test_initial_request_failure_is_not_partial`
  - `tests.test_resume_pipeline.ResumePipelineTests.test_two_refinements_continue_after_cooldown`
  - `tests.test_inference.RoutingTests.test_remaining_iterative_task_routes` (both `responsegen` and `sentiment_reversal` subcases)
- **Runtime Error:**
  ```text
  ImportError: cannot import name 'ExpandingGroupby' from 'pandas.core.window.expanding'
  ```
- **Analysis:**
  Both `src/responsegen/run.py` and `src/sentiment_reversal/run.py` imported `from pandarallel import pandarallel` at top level and had `if __name__ == "__main__": pandarallel.initialize(...)`. However, neither module actually called `parallel_apply` or utilized `pandarallel` anywhere in their execution logic. The import failed at module load time under modern `pandas` versions (where `ExpandingGroupby` has moved/changed), preventing `src.responsegen.run` and `src.sentiment_reversal.run` from being imported by `src.experiment.iterative()`. Consequently, `run_record()` failed with an uncaught `ImportError` before any mocked model call could take place.

### Fix
- Removed the unused `from pandarallel import pandarallel` import and its guarded initialization in `if __name__ == "__main__":` from both:
  - `src/responsegen/run.py`
  - `src/sentiment_reversal/run.py`
- Checked all remaining project source files (`src/pie/`, `src/commongen/`, `src/gsm/`, `src/readability/`, `src/acronym/`, and `prompt-lib/`). Verified that no other files import or use `pandarallel`.

---

## 2. Issue 2: Eager spaCy Model Loading in `src/commongen/feedback.py`

### Symptoms & Root Cause
- **Affected Test:**
  - `tests.test_inference.RoutingTests.test_commongen_with_existing_nlp_evaluation`
- **Runtime Error:**
  ```text
  OSError: [E050] Can't find model 'en_core_web_sm'.
  ```
- **Analysis:**
  `src/commongen/feedback.py` executed `nlp = spacy.load("en_core_web_sm")` directly at top-level module import. If `en_core_web_sm` is missing or fails to load, importing `src.commongen.feedback` (and by extension `src.commongen.run`) crashes before any function or test can run.

### Fix
- Replaced top-level eager `spacy.load("en_core_web_sm")` with lazy loading via a helper function `get_nlp()`:
  ```python
  _nlp = None

  def get_nlp():
      global _nlp
      if _nlp is None:
          _nlp = spacy.load("en_core_web_sm")
      return _nlp
  ```
- Updated `detect_concepts()` in `CommongenFeedback` to call `nlp = get_nlp()`.
- Documented `python -m spacy download en_core_web_sm` in `README.md` under setup instructions.
- Preserved existing CommonGen NLP evaluation logic, tokenization, lemmatization, and scoring rubric untouched.

---

## 3. Files Modified

| File | Change Description |
|---|---|
| `src/responsegen/run.py` | Removed unused `from pandarallel import pandarallel` and dead initialization block |
| `src/sentiment_reversal/run.py` | Removed unused `from pandarallel import pandarallel` and dead initialization block |
| `src/commongen/feedback.py` | Converted top-level eager `spacy.load` to lazy initialization `get_nlp()` |
| `src/experiment.py` | Added opt-in debug logging (`SR_DEBUG_TRACEBACK=true`) to assist diagnosis |
| `README.md` | Added spaCy model download step to workspace setup instructions |

---

## 4. Local Verification Commands

Because this agent's sandboxed environment cannot launch `powershell`, please execute the test commands locally in PowerShell:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'

# 1. Run the target test suites
.\.venv-research\Scripts\python.exe -m unittest tests.test_partial_dialogue -v
.\.venv-research\Scripts\python.exe -m unittest tests.test_resume_pipeline -v
.\.venv-research\Scripts\python.exe -m unittest tests.test_inference -v

# 2. Run the conversation manager test suites
.\.venv-research\Scripts\python.exe -m unittest tests.test_conversation_manager tests.test_chat_app -v

# 3. Run the full discovery suite
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
```
