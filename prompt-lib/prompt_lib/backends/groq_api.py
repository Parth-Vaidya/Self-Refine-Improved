"""Groq hosted chat API, with credentials isolated from HF and OpenAI."""
from prompt_lib.backends.huggingface_api import HostedChatAPIWrapper


class GroqAPIWrapper(HostedChatAPIWrapper):
    label = "Groq"
    env_prefix = "GROQ"
    token_env = "GROQ_API_KEY"
    engine_prefix = "groq:"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
