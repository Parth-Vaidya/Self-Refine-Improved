# Controlled Qwen3 refinement experiments

The integration is opt-in through `python -m src.experiment`. Legacy task commands
retain their model selection, prompts, iteration limits and stopping rules.

This is a **hosted API integration**, with no local LLM backend. HF's current
pricing requires free accounts to purchase credits for Inference Providers.
Changing the API key or selecting open weights does not make hosted inference
free. Never paste credentials into chat; revoke any token that has been exposed.
An [optional Groq quota fallback](groq-fallback.md) is available in a separate C
configuration. Strict A/B/C remain available without provider switching.

## Inspection and model choice

Standard task runners use `LLM_ENGINE` (default `gemini-1.5-flash`) for all stages.
The existing Gemini adapter remaps that alias to `gemini-3.5-flash-lite` and uses
at least 2,048 output tokens. These pre-existing behaviors are preserved and recorded.
Other Gemini aliases may also be remapped; inspect `gemini_api.py`. Original-model
availability was not verified by a live call. The MCTS acronym script is separate,
hardcodes `gpt-3.5-turbo`, and is not an A/B/C experiment runner.

Most tasks use `OpenaiAPIWrapper`; sentiment uses `router`. Explicit stage tags
now connect both interfaces to the same opt-in selection and metrics code.
Few-shot prompts remain in Python and `data/prompt`; no dataset or evaluator was
changed. The PIE template's missing `instr` formatting argument was fixed so that
its already-written refinement prompt can run. Readability's unchanged loop was
extracted into a callable function. Gemini usage is now retained when reported;
dialogue refuses missing generation usage because its context reduction rule needs it.

On 2026-10-22 Hugging Face's connected repository metadata listed **nscale** and
**featherless-ai** as live providers for `Qwen/Qwen3-4B-Instruct-2507` and
`Qwen/Qwen3-8B`. The 4B instruction model is selected for the smaller-model
experiment. Listed support is not a guarantee of account access or future uptime.

- Model: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- Supported API: https://huggingface.co/docs/inference-providers/tasks/chat-completion
- Endpoint: `https://router.huggingface.co/v1/chat/completions`

The adapter sends the existing prompt as a user message, preserves explicit system
messages, and adds no new instruction. Chat formatting and provider tokenization
differ from the original backend and remain experimental confounds. Provider
selection is explicit; failures never silently select another model or provider.

## Setup (PowerShell, repository root)

The old `venv` points to a missing Python 3.13 executable on this machine. A separate
`.venv-research` was created using available Python 3.12. To set up from scratch:

```powershell
python -m venv .venv-research
.\.venv-research\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = '.;prompt-lib'
```

The local `prompt-lib` checkout is required. Its dependency pins now permit the
legacy OpenAI 0.x API alongside the root requirements; no OpenAI 1.x migration was
made. The existing root `requirements.txt` had been ignored by `*.txt`; it is now
explicitly included. The tested API/task dependency set is recorded separately in
`requirements-research-lock.txt`; full NLP/evaluation dependencies are additional.

Keep your existing `.env`. `.env.example` contains placeholders only. Environment
variables take precedence over `.env`. Never put tokens in JSON configurations.

| Variable | Meaning |
| --- | --- |
| `HF_TOKEN` | HF token with Inference Providers permission; only sent as an authorization header |
| `HF_MODEL_ID` | Default `Qwen/Qwen3-4B-Instruct-2507` |
| `HF_PROVIDER` | Default `nscale`; alternative listed provider `featherless-ai` |
| `HF_TIMEOUT` | Per-attempt request timeout in seconds, default 60, maximum 600 |
| `HF_MAX_RETRIES` | Additional attempts, default 2, range 0–5 |
| `LLM_ENGINE` | Original model, default existing Gemini alias |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Original Gemini credential |
| `OPENAI_API_KEY`, `OPENAI_ORG` | Existing OpenAI settings if selected |
| `SR_GENERATION_MODEL`, `SR_FEEDBACK_MODEL`, `SR_MEASUREMENT_MODEL` | Optional original-stage overrides for A/C; B rejects differences |

Timeouts, connection failures, HTTP 408/429 and selected 5xx responses have bounded
backoff. Numeric `Retry-After` is honored up to 60 seconds. Authentication, payment,
unavailable-model and other permanent errors fail immediately. No response bodies,
headers or underlying exception strings are logged. HTTP redirects are disabled.
The adapter supports one completion per request, no legacy completion logprobs,
and no silent parameter fallback. Sentiment omits legacy logprobs for HF;
unavailable log probabilities and probabilities are saved as null.

## Experiments

| Configuration | Generation | Feedback / measurement | Refinement |
| --- | --- | --- | --- |
| A | Original, once | None | None |
| B | Original | Same original model | Same original model |
| C | Configured original | Configured original | Qwen3 through HF |

JSON configurations may explicitly specify `original_model`, `generation_model`,
`feedback_model`, `measurement_model`, `refinement_model` (for example
`hf:Qwen/Qwen3-4B-Instruct-2507:nscale`) and `prices`. Supplied JSON values override
environment defaults. Keep A/B/C inputs and settings matched. B intentionally
rejects unequal stage overrides. A permits exactly one generation stage; no
feedback-based candidate selection is performed.

Input is JSONL with the original task fields:

| Task | Fields | Supported variants |
| --- | --- | --- |
| acronym | `title` | A/B/C |
| commongen | `concepts` (list) | A/B/C |
| responsegen | `context` (already-prepared string) | A/B/C |
| pie | `input` (code) | A/B/C |
| sentiment_reversal | `review`, `sentiment`, `target_sentiment` | A/B/C |
| gsm | `input` (question) | A/B only |
| readability | `input` (code) | B/C only |

GSM combines critique and rewriting in one response. C is rejected before any
network call; splitting it requires a separately designed methodology/prompt change.
Readability has no initial generator: supplied code is its unrefined baseline,
so A is rejected. Its existing five rounds remain fixed. Other tasks retain their
original interpretation of `max_attempts`: sentiment uses an inclusive loop, while
acronym/CommonGen/dialogue/PIE count the initial generation as attempt zero.

```powershell
$env:PYTHONPATH = '.;prompt-lib'
# Use an existing JSONL dataset; do not replace it with synthetic data for reported research.
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/A.json --task acronym --input titles.jsonl --output A-results.jsonl --max-attempts 4
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/B.json --task acronym --input titles.jsonl --output B-results.jsonl --max-attempts 4
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/C.json --task acronym --input titles.jsonl --output C-results.jsonl --max-attempts 4
```

Output files must be new (exclusive creation prevents overwriting runs). Raw task
results are stored under `result`; existing task evaluator input formats are not
silently replaced. Each row includes configuration, dataset/source/prompt hashes,
package versions, limits, task settings, stage calls, and overall wall time. This
does not promise deterministic server inference or immutable hosted model revisions.
The new runner processes supplied records as-is: apply the legacy dialogue context
preparation and sentiment dataset filtering before comparing to old batch outputs.

For a single input, use `--query` instead of creating a JSONL file:

```powershell
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/C.json --task acronym --query "Using language models for commonsense reasoning" --output C-results.jsonl --max-attempts 4
```

The terminal shows the original user input first, then each successful generation
and refinement response, followed by the selected final output. The same final
value is saved as `final_output` alongside the original task `result` in the
specified output file. Existing batch commands retain their original destination
paths. The experiment runner suppresses legacy prompt-debug prints in favor of
this transcript. Failed records are saved with an error and a null final output;
the CLI returns exit code 1 if any record failed. Parsing retries can display
additional model responses; they remain visible in call telemetry.

## Metrics and evaluation

Latency is measured client wall time, including retries; API token counts are
reported values, not tokenizer estimates. Missing usage is null, never zero.
Successful call records show requested and effective models, token budgets, prompt
hashes and HF attempt/timeout information. Failed request usage and cost are unknown;
a provider may bill a timed-out request. Pipeline parsing retries remain unchanged
and their extra API calls are recorded. Gemini retains its original retry policy.

Costs default to unavailable. To calculate **estimates**, supply dated provider/model
rates under `prices`, keyed by the exact engine, with `input_per_million` and
`output_per_million`. Rates must be USD per million tokens. These calculations do
not establish billed charges, account discounts or reasoning-token billing rules.
Never sum partial known costs and label the result a complete experiment cost.

Existing acronym/dialogue scores, CommonGen feedback success and sentiment
measurement are retained as quality observations. They are model-based proxies,
not independently validated quality. Acronym's pre-existing fallback score of 15
also remains; interpret malformed-feedback cases carefully. A has no feedback
score. Evaluate its saved output with the same independent evaluator used for B/C,
and report evaluation latency/tokens/cost separately from generation. Do not add
feedback to A's generation cost or use missing quality as zero.

CommonGen needs spaCy `en_core_web_sm` and NLTK tokenizer resources (`punkt` /
`punkt_tab`, depending on version). Its existing evaluator consumes `sent_to_fb`.

```powershell
.\.venv-research\Scripts\python.exe -m spacy download en_core_web_sm
.\.venv-research\Scripts\python.exe -m nltk.downloader -d .cache/nltk_data punkt punkt_tab
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
```

GSM's evaluator executes generated code and uses Unix-only `SIGALRM`/shell commands;
it was not run on Windows. PIE runtime evaluation requires the external PIE
evaluation setup described in `docs/pie_eval.md`. Readability uses the existing
comment/function/name evaluators. None of these quality evaluations was claimed
as completed during integration.

To support an efficiency conclusion, compare matched datasets over repeated runs,
retain failures in the denominator, use the same quality evaluator, and separate
per-stage from total pipeline cost. Different providers, tokenizers, context
formatting and Gemini's token floor prevent interpreting parameter count alone as
proof of latency or cost improvement.

## Validation

```powershell
$env:PYTHONPATH = '.;prompt-lib'
$env:NLTK_DATA = Join-Path $PWD '.cache/nltk_data'
.\.venv-research\Scripts\python.exe -m unittest discover -s tests -v
```

Tests mock external inference and exercise payloads, stage routing, the real acronym
loop, safe failures, retries and telemetry. The old `test_openai.py` is a top-level
live call to a legacy model rather than an offline test suite; it is not included.
The authenticated HF smoke call was executed and returned HTTP 402. Check HF
billing/credits and provider access before rerunning a live experiment. No successful
live completion, full benchmark, or quality/efficiency improvement is claimed.

`prompt-lib` is a nested Git repository. Its new adapter, experiment module and
existing Gemini changes must be included in that repository when you later commit;
committing only the parent repository will not capture those files. No commits or
pushes were performed.
