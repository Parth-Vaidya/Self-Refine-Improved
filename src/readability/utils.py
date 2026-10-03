import os
from prompt_lib.backends.openai_api import OpenaiAPIWrapper

def call_gpt(prompt, model=None, stop=None, temperature=0., top_p=1.0,
        max_tokens=1024, majority_at=None, **kwargs):
    if model is None:
        model = os.getenv("LLM_ENGINE", "gemini-1.5-flash")
    num_completions = majority_at if majority_at is not None else 1
    
    response = OpenaiAPIWrapper.call(
        prompt=prompt,
        max_tokens=max_tokens,
        engine=model,
        stop_token=stop,
        temperature=temperature,
        top_p=top_p,
        num_completions=num_completions,
        **kwargs,
    )
    if num_completions == 1:
        return [OpenaiAPIWrapper.get_first_response(response)]
    else:
        return [r["generated_answer"] for r in OpenaiAPIWrapper.get_all_responses(response)]