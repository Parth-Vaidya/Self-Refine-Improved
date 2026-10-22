# Hosted Hugging Face integration validation

Date: 2026-10-22. Platform: Windows, Python 3.12.

## Groq fallback update

The current suite passes **26 tests** (7.886 seconds in the final run), including
the original 16 tests and 10 Groq tests. Dependency checks report no broken
requirements. Groq support adds no Python dependency; it shares the sanitized
HTTP transport with HF while keeping credentials and endpoints separate.

- Added `groq_api.py`, direct `groq:model-id` routing, configurable timeout/retries,
  optional HF HTTP 402/429 fallback, explicit fallback output and effective-model
  metadata. Estimates select rates for the actual provider/model used.
- HF 429 is retried before switching; HF 402 switches immediately. No switching
  for authentication/model/transport/server errors. If Groq also fails, a safe
  failure and the attempted fallback model are retained.
- Strict A/B do not switch. C can switch only refinement; original generation,
  feedback and measurement remain unchanged. Fallback is enabled explicitly in
  `experiments/C-groq-fallback.json`; strict C remains available. Direct Groq
  A/B configurations were also added.
- Default Groq model: `openai/gpt-oss-20b`, verified in Groq's current production
  model list and free-plan limits documentation. A live model-list request with
  `GROQ_API_KEY` returned HTTP 200 and listed that model for the configured account.
  No live generation request was made. Account billing/free quotas were not inferred.
- Tests cover payload preservation, isolated authorization headers, 402/429
  switches, no switch on other failures, missing keys, both providers failing,
  strict-stage protection, actual loop output, effective-model estimates, failure
  metadata, and explicit configuration validation.

See `docs/groq-fallback.md` for setup and commands and
`reports/groq-readiness.json` for the read-only account check. This update does
not establish Qwen/Groq quality equivalence or live benchmark performance.
Fallback runs must be analyzed separately from Qwen-only runs.

The sections below describe the original HF integration checks; the Groq update
above supersedes their original test count and provider-switching behavior.

## Outcome

The implementation uses Hugging Face Inference Providers with `HF_TOKEN` loaded
from the environment. No local LLM backend or model weights were added. The
selected hosted refinement model is `Qwen/Qwen3-4B-Instruct-2507`, with explicit
provider `nscale` by default. Model and provider are configurable.

**Hosted inference is not verified as free.** HF's current pricing documentation
requires free accounts to purchase Inference Providers credits:
https://huggingface.co/docs/inference-providers/pricing
Changing keys or choosing open weights does not remove the hosting charge.

The earlier authenticated smoke request returned **HTTP 402**. No successful live
completion has been observed. No new live inference was attempted after a token
was pasted into chat. That exposed token should be revoked and replaced only in
the local `.env`; the implementation neither embeds nor repeats it.

## Executed checks

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | **16 tests passed**, 11.190 seconds in the final expanded run |
| Actual acronym loop | A/B/C exercised with mocked API responses |
| Actual CommonGen loop and NLP evaluation | C exercised with mocked APIs, real spaCy/NLTK resources; early stop preserved |
| Actual dialogue, PIE, sentiment and readability loops | C exercised with mocked APIs; refinement-only HF routing checked |
| Actual GSM combined critique/rewrite loop | B exercised with mocked API; C rejected before any network request |
| HF adapter | Payload, stops, timeout configuration, missing token, invalid/empty completion, credential echo rejection, bounded retries and safe failures checked |
| Failure statuses | 401/403/404/429/500/503 covered; dedicated 402 test confirms one request, visible failure, null final output and no retry |
| Terminal and persistence | Original input → initial generation → refinement → final output; same final value saved at selected output path |
| File protection | Existing result file cannot be overwritten by experiment CLI |
| Routing telemetry | OpenAI calls through sentiment router counted once |
| Cost telemetry | Configured token rates produce explicitly labeled estimates; failures/missing usage remain unavailable |
| Full dependency installation | `pip install -r requirements.txt` completed in `.venv-research` |
| Dependency consistency | `pip check`: no broken requirements |
| Python syntax | 83 Python files parsed successfully |
| Credential-pattern scan | 93 source/configuration/document files scanned; no HF token-like literals found |
| Git credentials handling | `.env` is ignored and untracked; `.env.example` contains placeholders |
| Whitespace checks | Parent and nested `prompt-lib` checks passed after cleanup |

This suite uses synthetic response fixtures to test software behavior. Test
durations, fixture token counts and fixture scores are **not model performance
measurements**. See `offline-demo.md` and `offline-demo.jsonl` for a labeled example.
The old `prompt-lib/.../test_openai.py` makes a live call at import time and was
not executed with the exposed token.

## Changes

- `prompt-lib/prompt_lib/backends/huggingface_api.py`: hosted chat adapter,
  environment authentication, bounded retry/timeouts, allowlisted responses,
  sanitized errors, explicit HTTP 402 explanation, no automatic provider fallback.
- `prompt-lib/prompt_lib/experiment.py`: explicit stage selection, latency/token
  records, requested/effective settings, prompt hashes and optional cost estimates.
- Existing backend wrappers/router: route HF identifiers and avoid counting the
  same call twice. Gemini retains its existing model aliases and output-token floor;
  reported token usage is now retained.
- Task API call sites: stage tags; generation/feedback remain on original models
  in C. Existing successful prompt text and stopping/iteration rules are preserved.
- `src/experiment.py`, `experiments/A.json`, `B.json`, `C.json`: controlled runner,
  single-query or JSONL input, output persistence, source/prompt/configuration and
  package records, nonzero exit status when records fail.
- `src/output.py`: consistent transcript, credential redaction, explicit saved
  final result; acronym uses the existing CLI's best-score selection.
- Compatibility fixes: missing PIE template argument; missing dialogue usage
  fails explicitly; CommonGen malformed labels produce retryable parse failures;
  sentiment's unavailable probabilities are null rather than a fabricated 1.0;
  readability loop callable without altering its five rounds; multiprocessing
  initialization kept out of experiment imports; raw regex removes an escape warning.
- Setup/docs: placeholder `.env.example`, ignore rules, compatible dependency
  constraints, installed environment snapshot, README and experiment instructions.

Pre-existing local edits in acronym/CommonGen and `prompt-lib` were preserved.
`prompt-lib` is a nested Git repository; its files must be included there if the
user later commits. No commits or pushes were made.

## Commands executed

Commands below use `.venv-research/Scripts/python.exe` unless specified otherwise.
Credential values were never supplied in command arguments.

```powershell
python -m venv .venv-research
.\.venv-research\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-research\Scripts\python.exe -m spacy download en_core_web_sm
.\.venv-research\Scripts\python.exe -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
.\.venv-research\Scripts\python.exe -m nltk.downloader -d .cache/nltk_data punkt punkt_tab
$env:PYTHONPATH = '.;prompt-lib'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-research\Scripts\python.exe -m pip check
git check-ignore .env
git ls-files .env
git diff --check
git -C prompt-lib diff --check
```

Additional Python scripts performed syntax checks, credential-pattern checks,
the earlier small authenticated HF smoke request, package-version snapshot, and
the mocked output demonstration. A local-inference package installation started
before the hosted-only clarification; the two direct packages were subsequently
uninstalled. No local LLM model was downloaded or used. The standalone `venv` was
already broken and was not replaced; `.venv-research` is the working environment.

## Run after account access is ready

Keep a replacement token in `.env` only. Ensure the HF account has hosted-inference
access and credits, and the original generation/feedback credentials are usable.
Check `LLM_ENGINE`: its default Gemini alias is remapped by the existing adapter,
and access to that effective model has not been verified with a live call.

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/C.json --task acronym --query "Using language models for commonsense reasoning" --output C-results.jsonl --max-attempts 4
```

The terminal shows the original query, every returned generation/refinement,
then final output. `C-results.jsonl` stores the original input, task result,
`final_output`, call metrics and experiment manifest. Existing task-specific batch
commands retain their previous output destinations. Use a new result filename for
each experiment to avoid overwriting prior runs.

## Limits and remaining research work

There is no claim that all possible project bugs are fixed or that hosted output
will always match strict task parsers. Offline tests cover the paths described
above; they cannot establish live model availability, content quality or account
billing. Successful live API calls, paired dataset A/B/C runs, independent quality
evaluation, and measured efficiency comparisons remain outstanding.

GSM C is intentionally unsupported because its feedback call also rewrites the
answer. Readability has no initial generation and therefore no A configuration.
The existing GSM evaluator uses Unix-only mechanisms and executes generated code;
PIE runtime evaluation requires its separate external evaluation setup. Neither
evaluation was run on this Windows workspace. Billed cost is unavailable; supplied
price-rate calculations are estimates only.
