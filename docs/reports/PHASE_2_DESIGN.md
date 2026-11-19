# Phase 2 Design: User Preference Extraction

## 1. Current Architecture Inspection

### 1.1 Existing Storage & Conversation Management
- **Directory:** `chats/` contains individual human-readable conversation files: `chat_001.txt`, `chat_002.txt`, etc.
- **Data Structure (`ConversationManager` in `src/conversation_manager.py`):**
  - **Headers:** `Conversation ID`, `Title`, `Created`, `Last Updated`.
  - **Message Entries:** `[YYYY-MM-DD HH:MM:SS] USER [mode: standard|self_refine]:` and `[YYYY-MM-DD HH:MM:SS] ASSISTANT:`.
  - **API Capabilities:** `list_conversations()` returns metadata dicts; `load_conversation(conv_id)` parses and returns ordered messages with role, content, timestamp, and mode tags.
- **Chat App (`src/chat_app.py`):**
  - Strict 3-option main menu: `1. Start a New Chat`, `2. Continue Previous Chat`, `3. Exit`.
  - Per-turn interactive prompt asking `1. Standard Response` vs `2. Self-Refine Response`.
- **Generation & Refinement (`src/chat_pipeline.py`):**
  - Dedicated interactive `ChatResponsePipeline` using `groq:qwen/qwen3.8-27b`.
  - Clean separation from legacy benchmark datasets (`src/experiment.py`, `src/responsegen/run.py`).

### 1.2 Identified Opportunities for Phase 2
- The conversation files already record timestamped queries, user follow-up questions, explicit corrections (e.g., *"give more examples"*, *"keep it brief"*, *"show the code first"*), and the user-selected generation modes (`standard` vs `self_refine`).
- Because `chats/*.txt` files are standardized and parsed via `ConversationManager._parse_file()`, an offline preference extraction module can ingest these conversations cleanly without modifying existing generation or terminal loops.

---

## 2. Proposed Architecture

Phase 2 introduces a dedicated, modular extractor system decoupled from runtime chat execution:

```
+-----------------------------------------------------------------------------------+
|                                 Data Sources                                      |
|  chats/chat_001.txt, chats/chat_002.txt, ... + User-Supplied External .txt Chats  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                         src/preference_extractor/                                 |
|                                                                                   |
|  1. ChatReader & Ingestion:                                                       |
|     - Reads conversations via ConversationManager & imported TXT files.           |
|     - Tracks processed message timestamps / hashes to avoid redundant work.       |
|                                                                                   |
|  2. Hybrid Extraction Engine:                                                     |
|     - Deterministic Rule-Based Analyzer (Regex & Keyword Matcher):                |
|       Detects explicit imperatives ("shorter", "step-by-step", "in Python", etc.) |
|     - Model-Assisted Pattern Synthesizer (Opt-in via existing Qwen model):        |
|       Clusters recurring preferences across multiple sessions.                   |
|                                                                                   |
|  3. Conflict & Confidence Resolver:                                               |
|     - Computes confidence scores based on frequency, consistency, and recency.    |
|     - Detects situational/topic-dependent conflicts (e.g., math vs casual text).  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        Storage: user_profile.json                                 |
|  Human-readable and editable JSON schema with categories, evidence, and scores.   |
+-----------------------------------------------------------------------------------+
```

### Key Principles
1. **Zero Runtime Impact on Chat:** Chat conversation loops remain fast and unchanged.
2. **Offline / Background Execution:** Extraction can be triggered as a utility CLI (`python -m src.preference_extractor`) or run periodically on exit/update without blocking conversation turns.
3. **No External Network Dependencies:** Uses only local regex or the existing configured Groq/Qwen adapter (`groq:qwen/qwen3.8-27b`). No external APIs or accounts are queried.

---

## 3. Data Flow

```
[ Conversation Files (chats/*.txt) ]
                 |
                 v
       [ Message Filtering ] 
       - Extracts only USER turns and subsequent follow-ups/corrections
       - Ignores model hallucinations
                 |
                 v
       [ Signal Detection ]
       - Explicit signals (Direct user commands: "Be brief", "Explain like I'm 5")
       - Behavioral signals (User asks for clarification: "Can you elaborate?", "Show code")
       - Mode signals (Frequency of selecting Standard vs Self-Refine)
                 |
                 v
       [ Pattern Aggregation & Deduplication ]
       - Groups signals across distinct conversation IDs
       - Verifies recurrence (threshold >= 2 independent conversations)
                 |
                 v
       [ Conflict Detection & Confidence Scoring ]
       - Assigns confidence [0.0 - 1.0]
       - Tags context-specific caveats (e.g., "code vs theory")
                 |
                 v
       [ Persist to user_profile.json ]
```

---

## 4. Preference Extraction Methodology

### 4.1 Taxonomy of Categories
1. **Explanation Complexity:** e.g., elementary/introductory vs advanced graduate-level.
2. **Answer Length & Detail:** e.g., concise/terse summary vs exhaustive deep-dive.
3. **Response Structure:** e.g., bulleted lists, structured sections with bold headers vs flowing narrative.
4. **Examples & Practical Demonstrations:** e.g., demands real-world analogies, edge cases, dry runs.
5. **Step-by-Step Guidance:** e.g., sequential problem-solving walkthroughs.
6. **Technical Depth:** e.g., rigorous formal proofs, mathematical formulations vs high-level conceptual overviews.
7. **Tone & Communication Style:** e.g., strictly academic, informal, direct, no pleasantries.
8. **Code Explanation Preferences:** e.g., comments inside code vs explanation outside code, theory before code vs code-first.

### 4.2 Deterministic (Rule-Based) vs Model-Assisted Extraction

| Dimension | Deterministic (Regex / Rules) | Model-Assisted (LLM Extraction) | Proposed Hybrid Strategy |
|---|---|---|---|
| **Speed & Token Cost** | 0 tokens, sub-second execution | Consumes API tokens and quota | Fast deterministic pass first; LLM pass optional |
| **Precision** | High for explicit commands ("keep it short") | Handles subtle nuances and implied styles | Deterministic for explicit; LLM for semantic synthesis |
| **Privacy** | 100% offline, zero network requests | Sends message snippets to model | Deterministic runs locally; LLM requires user consent |
| **Contradiction Detection** | Rule-based pair comparison | Contextual reasoning | Rule-based flag with LLM contextual reasoning |

**Proposed Hybrid Approach:**
- **Tier 1 (Deterministic Core):** Scans user messages with curated linguistic patterns (e.g., regex matching imperative phrases: `"more detail"`, `"too long"`, `"step-by-step"`, `"show me an example"`).
- **Tier 2 (Opt-in Synthesis):** If enabled by the user, runs a batch prompt using the existing `GroqAPIWrapper` to cluster the extracted signals into structured profiles.

---

## 5. JSON Schema with Realistic Examples

The profile is stored in a clean, human-editable JSON file: `user_profile.json` at the project root.

```json
{
  "version": "1.0.0",
  "created": "2026-11-12 22:30:00",
  "last_updated": "2026-11-12 22:35:10",
  "metadata": {
    "total_conversations_analyzed": 5,
    "total_turns_analyzed": 28,
    "last_analyzed_conversation_id": "chat_005"
  },
  "preferences": [
    {
      "id": "pref_structure_step_by_step",
      "category": "step_by_step_guidance",
      "description": "Prefers step-by-step sequential breakdown when solving complex technical problems.",
      "type": "explicit",
      "confidence": 0.85,
      "status": "active",
      "evidence": [
        {
          "conversation_id": "chat_001",
          "timestamp": "2026-11-12 20:31:00",
          "user_query": "Explain Newton's third law step by step.",
          "signal_type": "explicit_request"
        },
        {
          "conversation_id": "chat_003",
          "timestamp": "2026-11-12 21:15:20",
          "user_query": "Can you break this down into clear steps rather than a big paragraph?",
          "signal_type": "correction_follow_up"
        }
      ],
      "conflicts": []
    },
    {
      "id": "pref_detail_concise_vs_deep",
      "category": "answer_length_and_detail",
      "description": "Prefers concise, direct answers for definitions, but requests detailed examples when discussing code.",
      "type": "inferred",
      "confidence": 0.65,
      "status": "context_dependent",
      "evidence": [
        {
          "conversation_id": "chat_002",
          "timestamp": "2026-11-12 20:45:10",
          "user_query": "Keep it short, just give me the formula.",
          "signal_type": "explicit_request"
        },
        {
          "conversation_id": "chat_004",
          "timestamp": "2026-11-12 21:50:00",
          "user_query": "Please elaborate and provide comprehensive code examples.",
          "signal_type": "explicit_request"
        }
      ],
      "conflicts": [
        {
          "context_a": "Physics / Theory",
          "preference_a": "concise",
          "context_b": "Programming / Code",
          "preference_b": "detailed"
        }
      ]
    }
  ]
}
```

---

## 6. Confidence Assignment Methodology

Confidence is represented as a float in `[0.0, 1.0]` calculated mathematically:

$$\text{Confidence} = \min\left(1.0, \; \text{Base} + (\text{Frequency Bonus}) + (\text{Consistency Bonus}) - (\text{Decay/Conflict Penalty})\right)$$

1. **Base Value by Origin:**
   - **Explicit User Instruction:** Base = `0.50` (e.g., *"Always show examples"*).
   - **User Correction / Follow-up:** Base = `0.40` (e.g., *"Too long, make it shorter"*).
   - **Inferred Behavioral Pattern:** Base = `0.20` (e.g., repeatedly selecting Self-Refine on math topics).
2. **Frequency & Recurrence (Anti-One-Off Rule):**
   - Single occurrence in 1 chat: Capped at maximum confidence `0.40` (flagged as `tentative`).
   - Observed in $\ge 2$ independent conversations: $+0.20$.
   - Observed in $\ge 4$ independent conversations: $+0.35$.
3. **Consistency vs. Conflict:**
   - If conflicting signals exist without clear context separation: $-0.25$ penalty.
   - If user explicitly confirms or edits the preference in `user_profile.json`: Locked to `1.00`.

---

## 7. Handling Contradictory & Context-Dependent Preferences

Users often prefer different styles depending on the domain:
- **Case 1: Topic-Dependent Contradiction:**
  - In Chat A: *"Give me a 1-sentence answer"* (General trivia).
  - In Chat B: *"Provide a full derivation with all intermediate steps"* (Physics problem).
  - *Resolution:* The extractor tags the preference as `context_dependent` rather than overwriting or averaging. It records `domain_context` (e.g., `stem_math` vs `general_qa`).
- **Case 2: Temporal Evolution (Preference Shift):**
  - If a user asked for beginner explanations in Chat 1 but consistently asks for advanced rigor in Chats 8, 9, and 10, the recency weighting gives higher influence to recent turns and flags the older preference as `superseded`.
- **Case 3: Unresolvable Direct Conflict:**
  - Confidence is reduced below the active threshold ($< 0.50$), preventing premature application in Phase 3.

---

## 8. Privacy and Data Handling

1. **Local-Only Storage:** `user_profile.json` resides strictly on the user's local disk inside the workspace.
2. **No Secret Leaks:** Any text processed through the extractor is sanitized using `src.output.redact()` to ensure tokens, keys, and credentials are never stored in profile evidence.
3. **Consent for LLM-Based Analysis:**
   - Deterministic extraction is 100% offline (0 network calls).
   - If model-assisted extraction is used, it uses only the existing user-configured Groq key with explicit user confirmation (`--enable-llm-synthesis` CLI flag).
4. **Editable & Auditable:** The user can open `user_profile.json` in any text editor, modify descriptions, delete unwanted preferences, or adjust confidence scores.

---

## 9. Files Likely to Be Created or Modified in Phase 2

### New Files to Create:
- `src/preference_extractor/__init__.py`
- `src/preference_extractor/schema.py`: Pydantic/dataclass models defining the `user_profile.json` structure.
- `src/preference_extractor/rules.py`: Deterministic linguistic pattern matcher for explicit and behavioral cues.
- `src/preference_extractor/analyzer.py`: Main engine coordinating conversation loading, pattern aggregation, and conflict resolution.
- `src/preference_extractor/profile_store.py`: Reader and writer for `user_profile.json` with schema validation and atomic writes.
- `tests/test_preference_extractor.py`: Unit tests for rule matching, confidence calculation, conflict detection, and JSON serialization.

### Files to Modify:
- None of the chat or benchmark runtime files (`src/chat_app.py`, `src/chat_pipeline.py`, `src/experiment.py`, `src/responsegen/*`) need modification. Phase 2 functions as an independent tool.

---

## 10. Testing Strategy

1. **Rule Matching Tests:**
   - Test detection of concise vs detailed phrasing.
   - Test detection of code vs theory preferences.
   - Test edge cases (negations like *"do not give me code"*).
2. **Confidence & Anti-One-Off Tests:**
   - Verify that a single request in 1 conversation never produces confidence $\ge 0.50$.
   - Verify that recurring instructions across $\ge 2$ conversations reach higher confidence.
3. **Conflict Resolution Tests:**
   - Verify that contradictory requests on identical topics lower confidence and flag conflicts.
4. **Persistence & Migration Tests:**
   - Test incremental updates: re-running the extractor on new chats updates the profile without duplicating evidence.
   - Test manual edits: user edits to `user_profile.json` are preserved on subsequent runs.
5. **No API Leakage:**
   - Tests run completely offline with mocked inputs, costing 0 tokens.

---

## 11. Risks and Limitations

1. **Over-Generalization:** Inferring a permanent rule from temporary frustration (e.g. user in a rush saying *"just give me the answer"*).
   - *Mitigation:* Strict multi-session recurrence requirement (minimum 2 independent conversation files).
2. **Context Blindness:** A user wanting brevity in shell commands but depth in mathematical theory.
   - *Mitigation:* Domain tagging on extracted preferences.
3. **Token Usage during Analysis:** Sending entire chat histories to Groq could trigger rate limits.
   - *Mitigation:* Primary extraction is deterministic/rule-based. Model calls are used only if explicitly requested, and only on filtered user snippets rather than entire chats.

---

## 12. Recommended Implementation Sequence

1. **Step 1:** Define profile data structures and JSON serialization (`schema.py`, `profile_store.py`).
2. **Step 2:** Implement deterministic rule engine (`rules.py`) with unit tests covering key categories.
3. **Step 3:** Implement cross-conversation aggregation, deduplication, and confidence scoring (`analyzer.py`).
4. **Step 4:** Implement conflict detection and recency decay.
5. **Step 5:** Provide a standalone CLI tool (`python -m src.preference_extractor`) allowing the user to inspect and generate their profile on demand.
6. **Step 6:** Full unit test suite verification.

