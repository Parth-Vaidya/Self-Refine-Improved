from prompt_lib.experiment import select_model, observed_call
from prompt_lib.backends.huggingface_api import HuggingFaceAPIWrapper
from prompt_lib.backends.groq_api import GroqAPIWrapper
# routes a query to the correct backend
import os

from prompt_lib.backends.openai_api import OpenaiAPIWrapper

from prompt_lib.backends.alpa_api import AlpaWrapper
from prompt_lib.backends.self_hosted import OpenSourceAPIWrapper
from prompt_lib.backends.gemini_api import GeminiAPIWrapper

# TODO: all of this should be in a config file
backend_map = {
    "openai": OpenaiAPIWrapper,

    "alpa": AlpaWrapper,
    "self_hosted": OpenSourceAPIWrapper,
    "gemini": GeminiAPIWrapper,
}

openai_engines = [
    "text-curie-001",
    "text-davinci-001",
    "text-davinci-002",
    "text-davinci-003",
    "code-davinci-002",
    "code-cushman-001",
    "gpt-3.5-turbo",
    "gpt-4",
    "vicuna-33b-v1.3",
    "meta-llama/Llama-2-70b-hf"
]
gemini_engines = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-flash",
    "gemini-pro"
]
shadowfire_engines = ["shadowfire"]

self_hosted_engines = [
    "self-vulcan-13b"
]

engine_to_backend = {e: "openai" for e in openai_engines}
engine_to_backend.update({e: "gemini" for e in gemini_engines})
engine_to_backend.update({e: "shadowfire" for e in shadowfire_engines})
engine_to_backend.update({e: "self_hosted" for e in self_hosted_engines})



def get_backend(engine):
    if engine.startswith("hf:"):
        return HuggingFaceAPIWrapper
    if engine.startswith("groq:"):
        return GroqAPIWrapper
    if engine == "shadowfire":
        from prompt_lib.backends.shadowfire_api import ShadowFireWrapper
        return ShadowFireWrapper
    if "gemini" in engine.lower():
        return GeminiAPIWrapper
    return backend_map[engine_to_backend[engine]]


def few_shot_query(prompt: str, engine: str, return_entire_response: bool = False, **kwargs):
    stage = kwargs.pop("stage", None)
    engine = select_model(stage, engine)
    backend = get_backend(engine)
    # OpenaiAPIWrapper already performs observation; do not count calls twice.
    if backend is OpenaiAPIWrapper:
        output = backend.call(stage=stage, prompt=prompt, engine=engine, **kwargs)
    else:
        output = observed_call(backend.call, stage=stage, prompt=prompt, engine=engine, **kwargs)
    top_response = backend.get_first_response(output)
    if return_entire_response:
        return output
    else:
        return top_response


def get_first_response(output, engine):
    return get_backend(output.get("model", engine)).get_first_response(output)

def call(prompt: str, engine: str, return_entire_response: bool = False, **kwargs):
    return few_shot_query(
        prompt=prompt, engine=engine, return_entire_response=return_entire_response, **kwargs
    )


def test():
    prompt = """Question: Who wrote Katie Queen Of Tennessee?
Answer: The Apache Relay
###
Question: Who wrote Never Going Back Again?"""

    for engine_name in ["text-curie-001", "shadowfire", "self-vulcan-13b"]:

        print(f"Testing {engine_name}\n")
        output = few_shot_query(
            prompt=prompt,
            engine=engine_name,
            max_tokens=100,
            stop_token="###",
            temperature=0.7,
        )
        print(output)


if __name__ == "__main__":
    test()
