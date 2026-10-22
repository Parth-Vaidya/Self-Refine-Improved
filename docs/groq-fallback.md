# Groq hosted fallback

Groq is an optional backup for Hugging Face refinement calls. Both providers run
remotely. Credentials remain separate: `HF_TOKEN` is sent only to the HF router;
`GROQ_API_KEY` is sent only to `https://api.groq.com/openai/v1/chat/completions`.
The implementation reuses `requests`; it does not change the legacy OpenAI SDK
or require the Groq SDK. Never paste keys into chat or JSON experiment files.

## Model and access

Default model: **`openai/gpt-oss-20b`**, represented inside this project as
`groq:openai/gpt-oss-20b`. Groq's current official documentation lists it as a
production model and includes it in the free-plan limits table. Account limits
and billing depend on your Groq plan; a valid key is not a guarantee of unlimited
free usage. The free-plan table currently lists 30 RPM, 1,000 RPD, 8,000 TPM and
200,000 TPD for this model. Check your account's limits before dataset runs.

Sources, checked 2026-10-22:

- https://console.groq.com/docs/models
- https://console.groq.com/docs/rate-limits
- https://console.groq.com/docs/openai

The live read-only `/openai/v1/models` check returned HTTP 200 and confirmed that
this model is listed for the configured account. See `reports/groq-readiness.json`.
No live generation request was made for this addition.

## Configuration

Add settings to your existing local `.env`. Keep the actual Groq key in that file
only; `.env.example` has placeholders. No existing secret was edited.

```dotenv
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL_ID=openai/gpt-oss-20b
GROQ_TIMEOUT=60
GROQ_MAX_RETRIES=2
HF_GROQ_FALLBACK=false
```

`GROQ_TIMEOUT` is a per-attempt timeout (0–600 seconds, exclusive of zero).
`GROQ_MAX_RETRIES` is the number of additional attempts, between 0 and 5.
Groq transient errors have bounded retries and numeric `Retry-After` handling.
One completion is supported per request; legacy completion logprobs are rejected.
Missing or malformed responses fail with credential-free errors.

Choose `experiments/C-groq-fallback.json` to explicitly enable the backup, even
when the environment default is false. Alternatively set `HF_GROQ_FALLBACK=true`
for C runs, or specify `"hf_groq_fallback": true` in a C configuration.
An explicit JSON setting takes precedence over the environment default.
`"groq_model": "groq:openai/gpt-oss-20b"` optionally pins the fallback model in JSON;
otherwise `GROQ_MODEL_ID` supplies it. The resolved model and enabled flag are
recorded in the experiment manifest. Model IDs are configurable, not auto-selected.

## Behavior

1. Generation and feedback retain their original configured models.
2. Refinement uses the configured HF Qwen3 model first.
3. HF HTTP 429 triggers backup only after the configured HF retries are exhausted.
   HF HTTP 402 (credits/payment restriction) triggers backup immediately.
4. The same prompt, explicit system message, stops, temperature and output-token
   limit are sent to Groq. No new instruction or dataset change is introduced.
5. The terminal displays `HF TO GROQ FALLBACK`, then the refinement and final result.
   The JSONL contains the same final output plus requested/effective models,
   fallback reason, attempt counts, latency and available token usage.

Authentication errors, missing HF credentials, model errors, timeouts and server
errors do not switch providers. Missing Groq credentials fail clearly. If Groq is
also unavailable or rate-limited, the run fails after bounded retries and saves
its error; no third provider is selected. Both failed and successful fallback
attempts are recorded. The adapter never passes HF credentials to Groq.

A/B configurations keep fixed models and cannot enable fallback. In C, fallback
is limited to the separate refinement stage; it does not change generation,
feedback or measurement. Non-experiment direct HF adapter calls may use the
environment opt-in without stage restrictions.

## Run the Newton query

From the project root in PowerShell:

```powershell
$env:PYTHONPATH = '.;prompt-lib'
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/C-groq-fallback.json --task responsegen --query "User: Explain Newton's second law." --output newton-fallback-results.jsonl --max-attempts 3
```

This preserves the original generation and feedback models. Their keys and quotas
must also work. HF backup does not resolve a Gemini/OpenAI failure earlier in the
pipeline. Choose a new output filename on each run.

To explicitly use Groq for every stage instead of attempting HF:

```powershell
.\.venv-research\Scripts\python.exe -m src.experiment --config experiments/B-groq.json --task responsegen --query "User: Explain Newton's second law." --output newton-groq-results.jsonl --max-attempts 3
```

`experiments/A-groq.json` is the one-pass version. These are distinct Groq
baselines; they do not represent a Qwen3 refinement experiment.

## Research interpretation and costs

A successful fallback is a **Groq/GPT-OSS result**, not a Qwen3 result. Analyze
fallback runs separately from strict C runs. `requested_model` remains HF;
`effective_model` and `inference.provider` identify Groq. Output extraction routes
through the actual returned model identifier. The primary failed HF usage/cost
is unknown, while Groq's response supplies its own usage. Total wall latency
includes both providers and backoff. Configured price estimates use the actual
Groq model's rates rather than HF rates. Costs remain unavailable unless supplied;
free-tier access and billed charges are not inferred from token counts.

The shared adapter refactor was tested alongside the earlier pipeline suite.
All provider responses in those tests are mocked. See the updated validation report.
