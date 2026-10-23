# Offline HF configuration check

```text
Configuration: experiments/C.json
Variant: C

Generation: gemini-3.5-flash-lite
  Gemini credential: configured
Feedback: gemini-3.5-flash-lite
  Gemini credential: configured
Refinement: hf:Qwen/Qwen3-4B-Instruct-2507:nscale
  Endpoint: https://router.huggingface.co/v1/chat/completions
  HF_TOKEN: configured

HF to Groq fallback: disabled
Hosted request budget: 5/700 used (Groq/HF, including retries).

Local checks only. Account access, model availability and credits are NOT verified.
No API requests made.

Configuration: experiments/C-groq-fallback.json
Variant: C

Generation: gemini-3.5-flash-lite
  Gemini credential: configured
Feedback: gemini-3.5-flash-lite
  Gemini credential: configured
Refinement: hf:Qwen/Qwen3-4B-Instruct-2507:nscale
  Endpoint: https://router.huggingface.co/v1/chat/completions
  HF_TOKEN: configured

HF to Groq fallback: enabled
Fallback model: groq:openai/gpt-oss-20b
Hosted request budget: 5/700 used (Groq/HF, including retries).

Local checks only. Account access, model availability and credits are NOT verified.
No API requests made.
```

No live inference was attempted. Earlier saved HF runs failed with HTTP 402; credits/access remain unverified.
