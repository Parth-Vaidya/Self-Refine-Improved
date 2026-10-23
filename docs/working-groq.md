# Working Qwen3 / Groq dialogue runner

Run from PowerShell in the project root:

```powershell
.\run-query.ps1
.\run-query.ps1 -Query "Explain inertia." -Attempts 2
```

Uses `groq:qwen/qwen3.8-27b` for generation, feedback and refinement
(variant B). Two attempts mean one initial generation and one refinement,
each scored by a feedback call: four HTTP requests if no retries occur.
This is a Groq baseline, not the original HF 4B refinement-only experiment.
The live Newton example completed and is saved in
`newton-qwen-groq-verified.jsonl`. Model-scored quality is not independent evaluation.

Dialogue output budgets are now 2048 tokens per stage. Response labels are
optional and multiline content is retained. Feedback must contain a valid total
score; malformed feedback fails clearly. UTF-8 supports mathematical text on Windows.

## Persistent cap

Groq and HF hosted-chat HTTP attempts share a hard lifetime cap of 700, starting
with this change. Reservations commit before each network attempt, including
retries and fallbacks; a failed or interrupted request still consumes a slot.
SQLite transactions serialize concurrent reservations. The ledger is local at
`.cache/request-budget.sqlite3`; it does not reset daily or between runs.
Missing, corrupt or exhausted ledgers block calls. Do not delete, replace or reset it.
Offline tests use mocks or temporary databases and do not consume the live budget.
This counter cannot track calls made from other programs, other copies of the
project, or legacy Gemini/OpenAI backends. Use the Groq configurations above.
Existing calls before this change are not included.

Published Groq limits for this model are 30 requests/minute, 1000/day,
8000 tokens/minute and 200000/day. The local 700 cap is stricter on request
count; provider token/time quotas still apply and may produce HTTP 429.
The transport respects Retry-After with bounded retries. The local counter is
not an account-wide quota monitor or a claim of unlimited/free billing.

Run offline checks:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
```

## Readable results and offline checks

Each new experiment writes a readable `.md` report beside its `.jsonl` data.
Open the Markdown file to see the question, final answer, models actually used,
token totals, answer history and feedback. Full research metadata stays in JSONL.
Existing reports are never overwritten.

Convert an existing result without any model requests:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
.\.venv-research\Scripts\python.exe -m src.report newton-qwen-groq-verified.jsonl --output another-readable-result.md
```

Inspect model routing and credential presence without sending a request:

```powershell
.\.venv-research\Scripts\python.exe -m src.check_config --config experiments/C.json
```

The local check resolved strict C to Gemini generation/feedback and
`hf:Qwen/Qwen3-4B-Instruct-2507:nscale` refinement, with fallback disabled.
`C-groq-fallback.json` enables Groq only after eligible HF refinement failures.
The working `B-qwen-groq.json` routes every stage to Groq; its unused HF default
in the JSON manifest does not mean HF was called. Reports use actual call records.
Local configuration checks do not establish hosted availability, credits or access.
No HF request was made for this check; the earlier saved HF failure was HTTP 402.

## Groq timing and same-run recovery

`run-query.ps1` now enables `GROQ_RESUME_ON_RATE_LIMIT=true`. Successful calls
have no added delay. HTTP 429 pauses for Retry-After (65 seconds if unavailable)
and retries exactly the unfinished stage, retaining earlier answers and feedback.
Retries are limited to five additional attempts per stage; waits over one hour
stop rather than retry early. Other errors stop immediately. Every HTTP attempt
still consumes the persistent 700-request budget, and waiting consumes none.

Use three attempts for an initial answer and two refinements:

```powershell
.\run-query.ps1 -Query "Explain Newton's third law." -Attempts 3
```

Keep the terminal running during a cooldown. Each parsed/scored answer is saved
beside the output as `.jsonl.checkpoint.json`. This is a backup, not a command
for automatic restart after closing the process. Same-run recovery does not redo
completed stages. If bounded recovery fails, the readable report preserves the
latest answer with status `partial`. Six model calls are needed for three answers
with feedback; rate-limit rejections add HTTP attempts. Recovery cannot guarantee
provider quota availability or answer accuracy.

Direct adapter use still stops without cooldown recovery unless explicitly enabled.

## Interrupted dialogue experiments

Each parsed answer is checkpointed before feedback. If a later provider call
fails, the runner saves status `partial`, the latest completed answer, earlier
answers and available scores. Missing feedback/score values remain null. The
terminal and Markdown report explain the interruption; the partial answer is not
claimed to be the highest-scoring answer or a completed experiment.
An initial generation failure still has status `error` and no fabricated answer.
Complete experiments retain their existing best-score selection.
CLI exit codes: 0 complete, 1 failed, 2 partial. Groq cooldown recovery is opt-in, and enabled by the query script.
Groq quotas still apply; preserving work does not bypass provider rate limits.
