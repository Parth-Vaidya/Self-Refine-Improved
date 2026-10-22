import os
import time
import random
from typing import Dict, Any, List, Optional, Union
from prompt_lib.backends.wrapper import BaseAPIWrapper

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import google.generativeai as genai


from google.api_core import exceptions as google_exceptions

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def retry_with_exponential_backoff(
    func,
    initial_delay: float = 3,
    exponential_base: float = 1.5,
    jitter: bool = True,
    max_retries: int = 15,
    errors: tuple = (
        google_exceptions.ResourceExhausted,
        google_exceptions.ServiceUnavailable,
        google_exceptions.TooManyRequests,
    ),
):
    """Retry a function with exponential backoff."""

    def wrapper(*args, **kwargs):
        num_retries = 0
        delay = initial_delay

        while True:
            try:
                return func(*args, **kwargs)
            except errors as e:
                num_retries += 1
                if num_retries > max_retries:
                    raise Exception(f"Maximum number of retries ({max_retries}) exceeded: {e}")

                delay = max(delay * exponential_base * (1 + jitter * random.random()), 5.0)
                print(f"\n[Gemini API Free-Tier Rate Limit] Waiting {delay:.1f}s before retry...")
                time.sleep(delay)
            except Exception as e:
                raise e

    return wrapper



class GeminiAPIWrapper(BaseAPIWrapper):
    @staticmethod
    def _normalize_engine_name(engine: str) -> str:
        if not engine:
            return "gemini-3.5-flash-lite"
        engine_clean = engine.strip().lower()
        if engine_clean in ["gemini", "gemini-flash", "gemini-1.5", "gemini-1.5-flash", "gemini-2.0", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-lite", "gemini-flash-lite"]:
            return "gemini-3.5-flash-lite"
        if engine_clean in ["gemini-pro", "gemini-1.5-pro", "gemini-2.5-pro", "gemini-3-pro"]:
            return "gemini-3.7-flash"
        return engine


    @staticmethod
    @retry_with_exponential_backoff
    def _call_single(
        prompt: Union[str, List[Dict[str, str]]],
        max_tokens: int,
        engine: str,
        stop_token: Optional[Union[str, List[str]]],
        temperature: float,
        system_message: Optional[str] = None,
    ) -> str:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please add GEMINI_API_KEY=your_key to your .env file or environment."
            )
        genai.configure(api_key=api_key)

        model_name = GeminiAPIWrapper._normalize_engine_name(engine)

        stop_sequences = []
        if stop_token:
            if isinstance(stop_token, str):
                stop_sequences = [stop_token]
            elif isinstance(stop_token, list):
                stop_sequences = stop_token

        # Ensure generous token budget so thinking and generation are not truncated
        out_tokens = max(max_tokens if max_tokens and max_tokens > 0 else 2048, 2048)
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=out_tokens,
            temperature=temperature if temperature is not None else 0.7,
            stop_sequences=stop_sequences if stop_sequences else None,
        )

        # Permissive safety settings for research/evaluation tasks
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_message if system_message else None,
            safety_settings=safety_settings,
        )

        if isinstance(prompt, list):
            # Convert openai message list to string/contents
            prompt_str = ""
            for msg in prompt:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                prompt_str += f"{role.upper()}: {content}\n"
            content_input = prompt_str
        else:
            content_input = str(prompt)

        response = model.generate_content(
            content_input,
            generation_config=generation_config,
        )

        metadata = getattr(response, "usage_metadata", None)
        usage = {}
        for source, target in (("prompt_token_count", "prompt_tokens"), ("candidates_token_count", "completion_tokens"), ("total_token_count", "total_tokens")):
            value = getattr(metadata, source, None)
            if isinstance(value, int):
                usage[target] = value
        try:
            if response.text:
                return response.text, usage
        except Exception:
            pass

        try:
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                text_parts = []
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                if text_parts:
                    return "".join(text_parts), usage
        except Exception:
            pass

        return "", usage


    @staticmethod
    def call(
        prompt: Union[str, List[Dict[str, str]]],
        max_tokens: int = 1000,
        engine: str = "gemini-1.5-flash",
        stop_token: Optional[Union[str, List[str]]] = None,
        temperature: float = 0.7,
        num_completions: int = 1,
        system_message: Optional[str] = None,
        **kwargs,
    ) -> dict:
        choices = []
        combined_usage = {}
        for _ in range(max(1, num_completions)):
            text, usage = GeminiAPIWrapper._call_single(
                prompt=prompt,
                max_tokens=max_tokens,
                engine=engine,
                stop_token=stop_token,
                temperature=temperature,
                system_message=system_message,
            )
            for key, value in usage.items():
                combined_usage[key] = combined_usage.get(key, 0) + value
            choices.append({
                "text": text,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            })

        return {
            "model": engine,
            "choices": choices,
            "usage": combined_usage,
        }

    @staticmethod
    def get_first_response(response: dict) -> str:
        """Returns the first response text."""
        if not response or "choices" not in response or not response["choices"]:
            return ""
        choice = response["choices"][0]
        if "text" in choice and choice["text"]:
            return choice["text"]
        if "message" in choice and isinstance(choice["message"], dict):
            return choice["message"].get("content", "")
        return ""

    @staticmethod
    def get_majority_answer(response: dict) -> str:
        return GeminiAPIWrapper.get_first_response(response)

    @staticmethod
    def get_all_responses(response: dict) -> List[Dict[str, Any]]:
        return [
            {"generated_answer": c.get("text", c.get("message", {}).get("content", "")), "logprobs": None}
            for c in response.get("choices", [])
        ]
