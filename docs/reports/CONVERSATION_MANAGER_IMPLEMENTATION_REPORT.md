# Conversation Manager Implementation Report

## 1. Files Created and Modified

### Created
- `src/conversation_manager.py`: Implements `ConversationManager`, `generate_title_from_query()`, and TXT file serialization/parsing for persistent conversations under `chats/`.
- `src/chat_app.py`: Implements `ChatApp`, `print_main_menu()`, `default_generate_response()`, and `main()` (`python -m src.chat_app`) providing the 3-option terminal menu and interactive chat loop.
- `tests/test_conversation_manager.py`: Unit tests for `ConversationManager` (file creation, auto-incrementing IDs, message persistence, listing, isolation, restart persistence, context truncation without disk mutation, and title generation).
- `tests/test_chat_app.py`: Unit tests for `ChatApp` using `unittest.mock` (menu exit, empty chat list handling, starting a new chat with auto-generated title, returning to main menu, continuing a chat after restart with restored context, and verifying `default_generate_response` calls `src.experiment.configuration` and `src.experiment.run_record`).

### Modified / Unchanged
- No existing source files (`src/experiment.py`, `src/responsegen/*.py`, `src/utils.py`, `src/output.py`, `src/check_config.py`, `src/report.py`), experiment configs (`experiments/*.json`), or existing tests (`tests/test_inference.py`) were modified.

---

## 2. Conversation Storage Design

Conversations are stored as individual UTF-8 `.txt` files in `chats/` at the project root (e.g., `chats/chat_001.txt`, `chats/chat_002.txt`).

Each file uses a structured, human-readable layout:

```text
========================================
Conversation ID: chat_001
Title: Newton's Laws Discussion
Created: 2026-11-12 20:30:00
Last Updated: 2026-11-12 20:35:22
========================================

[2026-11-12 20:30:00] USER:
Explain Newton's third law.

[2026-11-12 20:30:05] ASSISTANT:
For every action, there is an equal and opposite reaction.
```

- **Auto-incrementing IDs:** `ConversationManager._next_conversation_id()` scans `chats/chat_*.txt` and assigns `chat_{highest + 1:03d}`.
- **Automatic saving:** Every user message and assistant response is immediately persisted via `save_message()`, which also updates the `Last Updated` header timestamp.
- **Auto-generated titles:** When starting a new chat, if the user presses Enter without typing a title, `generate_title_from_query()` derives a concise title from the first user query (falling back to `Chat YYYY-MM-DD` if no query is sent).

---

## 3. How Chat Continuation Works

When the user selects **2. Continue Previous Chat**:
1. `ConversationManager.list_conversations()` scans `chats/*.txt`, parses each header, and sorts conversations by `updated` timestamp (newest first).
2. If no conversations exist, `ChatApp.continue_previous_chat()` prints `No previous conversations found.` and returns to the main menu.
3. Otherwise, it displays a numbered list showing each conversation's ID, title, and `Last updated` timestamp.
4. Once the user selects a conversation, `ConversationManager.load_conversation(conv_id)` loads the metadata and full message list from disk, prints up to the last 6 messages as a brief recap, and enters `_chat_loop(conv_id)`.
5. New user and assistant messages are appended to the same `.txt` file without mixing histories across conversations.

---

## 4. How LLM Context Is Restored and Managed

1. Before each generation call, `ChatApp._chat_loop()` calls `ConversationManager.get_context_for_llm(conv_id, max_chars=8000)`.
2. Messages are formatted in chronological order as:
   ```text
   User: <message>
   Assistant: <response>
   ```
3. **Context window protection:** If the formatted history exceeds `max_chars` (default `8000` characters, leaving headroom for the few-shot examples in `data/prompt/responsegen/init.jsonl` and `feedback.jsonl` and the 2048-token output budget), `get_context_for_llm()` drops the oldest turns first, keeps the newest turns that fit, and prepends:
   `[Earlier messages omitted to fit the model context window; full conversation is preserved on disk.]`
   The underlying `.txt` file on disk is never truncated or modified.
4. **Pipeline integration:** `default_generate_response()` loads `experiments/B-qwen-groq.json` via `src.experiment.configuration()` and calls `src.experiment.run_record(task="responsegen", row={"context": context}, config=config, attempts=2)`.
   - Note on `variant="B"` and `attempts`: In `src/experiment.py` and `src/responsegen/run.py`, `variant="B"` executes `iterative_response()` rather than `one_pass()`. Even `attempts=1` runs initial generation + feedback (2 calls), while `attempts=2` runs initial generation, feedback, refinement 1, and feedback (4 calls) and selects the highest-scored candidate via `src.output.final_output()`.

---

## 5. Test Results

- **Execution status in this environment:** Automated command execution via `run_command` failed in this workspace with:
  `exec: "c:\\Users\\ASUS\\OneDrive\\Desktop\\CLASSES\\5th Sem\\AI CS307\\Project\\self-refine\\powershell": executable file not found in %PATH%`
  As a result, the test suites could not be executed from the agent terminal tool and **have not yet been run**.
- **Tests added (mocked, no real API calls):**
  - `tests/test_conversation_manager.py` (8 test methods)
  - `tests/test_chat_app.py` (5 test methods)
- **Commands to run locally to verify both new and existing suites:**
  ```powershell
  $env:PYTHONPATH = '.;prompt-lib'
  $env:PYTHONIOENCODING = 'utf-8'
  $env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
  .\.venv-research\Scripts\python.exe -m unittest tests.test_conversation_manager tests.test_chat_app -v
  .\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
  ```

---

## 6. Known Limitations

- **Unverified runtime execution in this session:** Because `powershell` could not be launched by the tool runner, the new tests and `python -m src.chat_app` have not been executed here yet.
- **ResponseGen `Response:` / `User:` stripping:** `ResponseGenTaskInit.make_query()` and `ResponseGenTaskIterate._make_input()` strip literal `"User: "` and `"System: "` substrings from `context`. Multi-turn `Assistant: ` labels remain intact, while `User: ` labels are stripped per existing `responsegen` prompt logic.
- **Temporary `responses_iterate_*.txt` files:** Existing `ResponseGenTaskIterate.__call__()` writes `responses_iterate_<count>.txt` to the working directory during refinement runs; this existing behavior was preserved without modifying `src/responsegen/task_iterate.py`.
- **Single-line message header assumption:** If a user or assistant message contains a line matching `^[YYYY-MM-DD HH:MM:SS] (USER|ASSISTANT):$`, the TXT parser treats it as a new message boundary.

---

## 7. Preparation for Future Preference Extraction

- Every conversation is persisted with structured headers (`Conversation ID`, `Title`, `Created`, `Last Updated`) and per-message ISO-style timestamps and explicit roles (`USER` / `ASSISTANT`).
- `ConversationManager.list_conversations()` and `ConversationManager.load_conversation(conv_id)` provide a clean programmatic interface returning structured dictionaries (`id`, `title`, `created`, `updated`, `messages`), allowing future phases to scan `chats/*.txt` to detect recurring user corrections, extract response preferences, maintain a user preference profile, and adapt dynamic stopping conditions without altering the storage format.

