# Phase 2 Implementation Report: Simplified User Preference Extraction

## 1. Overview and Architecture

A simplified, rule-based user preference extraction system has been implemented as an independent utility module:
- **Module:** `src/preference_extractor.py` (`UserProfileManager` & `detect_preferences_in_text()`)
- **Profile Store:** `user_profile.json` at the workspace root
- **Test Suite:** `tests/test_preference_extractor.py`

The implementation adheres to all constraints:
- **Zero LLM dependency:** Uses simple regex keyword matching; 0 tokens consumed, 0 network API calls.
- **No Complex Overengineering:** No confidence scores, semantic clustering, complex conflict resolution, or evidence tracking.
- **Zero Impact on Chat / Benchmark Execution:** Does not modify the 3-option main menu, Standard vs Self-Refine selection, `src/chat_app.py`, `src/chat_pipeline.py`, or benchmark pipelines (`src/experiment.py`, `src/responsegen/run.py`).

---

## 2. Implemented Preference Rules

The rule set maps common user directives to explicit preference keys:

| Preference Key | Description | Example Trigger Phrases |
|---|---|---|
| `prefers_step_by_step` | Prefers step-by-step explanations | *"explain step by step"*, *"break it down"*, *"walk me through"* |
| `prefers_concise_answers` | Prefers short, concise answers | *"keep it short"*, *"be concise"*, *"brief"*, *"to the point"* |
| `prefers_simple_code` | Prefers simple and clean code implementations | *"use simple code"*, *"easy code"*, *"clean code"*, *"basic code"* |
| `prefers_examples` | Prefers practical examples and demonstrations | *"give examples"*, *"show me an example"*, *"with an example"* |

---

## 3. Storage and User Editing (`user_profile.json`)

The profile is stored in a clean, human-readable format:

```json
{
  "last_updated": "2026-11-12 22:35:00",
  "preferences": {
    "prefers_step_by_step": {
      "description": "Prefers step-by-step explanations",
      "enabled": true
    },
    "prefers_examples": {
      "description": "Prefers practical examples and demonstrations",
      "enabled": true
    }
  }
}
```

- **Deduplication:** Subsequent extraction runs scan `chats/*.txt` and add newly detected preferences without duplicating existing keys.
- **Manual User Edits:** If the user manually edits `user_profile.json` (e.g. toggling `"enabled": false`, modifying descriptions, or adding custom fields/notes), existing entries are preserved during re-scans.
- **Privacy & Security:** All profile writes pass through `src.output.redact()` to ensure tokens, keys, and secrets are never stored in the profile file.

---

## 4. Files Created and Modified

| File | Status | Description |
|---|---|---|
| `src/preference_extractor.py` | **Created** | Implements `detect_preferences_in_text()`, `UserProfileManager`, and CLI entry point (`python -m src.preference_extractor`). |
| `tests/test_preference_extractor.py` | **Created** | Unit tests for keyword detection, conversation scanning, profile deduplication, user-edit preservation, and credential redaction. |
| `PHASE_2_IMPLEMENTATION_REPORT.md` | **Created** | Implementation documentation. |

---

## 5. Verification Commands

Run locally in PowerShell:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'

# 1. Run the new preference extraction tests
.\.venv-research\Scripts\python.exe -m unittest tests.test_preference_extractor -v

# 2. Run the interactive chat & conversation manager suites
.\.venv-research\Scripts\python.exe -m unittest tests.test_chat_pipeline tests.test_chat_app tests.test_conversation_manager -v

# 3. Run the existing benchmark suites
.\.venv-research\Scripts\python.exe -m unittest tests.test_partial_dialogue tests.test_resume_pipeline tests.test_inference -v

# 4. Full test discovery
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v

# 5. Run the extractor tool on current chats
.\.venv-research\Scripts\python.exe -m src.preference_extractor
```

