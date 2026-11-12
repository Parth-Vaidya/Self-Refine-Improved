"""Dedicated interactive chat response generation and refinement pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from prompt_lib.backends import openai_api
from prompt_lib.backends.huggingface_api import InferenceError


DEFAULT_PROFILE_PATH = "user_profile.json"


def load_personalization_instruction(profile_path: str | Path = DEFAULT_PROFILE_PATH) -> Optional[str]:
    """Load enabled preferences from user_profile.json and build a concise instruction."""
    path = Path(profile_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        preferences = data.get("preferences", {})
        if not isinstance(preferences, dict):
            return None

        enabled_descs: List[str] = []
        for pref_key, pref_val in preferences.items():
            if isinstance(pref_val, dict) and pref_val.get("enabled") is True:
                desc = pref_val.get("description") or pref_key
                enabled_descs.append(str(desc).strip())

        if not enabled_descs:
            return None

        # Build concise instruction for the LLM
        formatted = "; ".join(enabled_descs)
        return f"User preferences: Please adhere to the following style preferences where applicable: {formatted}."
    except Exception:
        # Gracefully handle missing, empty, or corrupt profile files
        return None


CHAT_INSTRUCTION = (
    "You are a helpful, coherent, and knowledgeable AI assistant engaged in an interactive conversation. "
    "Respond directly and constructively to the user based on the conversation history."
)

FEEDBACK_PROMPT_TEMPLATE = """You are evaluating an assistant's draft response to a user in a conversation.
{personalization_section}
Conversation History:
{context}

Draft Response:
{response}

Critique the draft response on:
1. Relevance and helpfulness
2. Accuracy and clarity
3. Tone and coherence{personalization_criteria}

Conclude your critique with a single line formatted exactly as:
Critique Summary: <one sentence summary of improvements needed, or 'None' if the response is excellent>
Total score: <score between 0 and 10>/10
"""

REFINE_PROMPT_TEMPLATE = """You are refining an assistant's response in an ongoing conversation based on feedback.
{personalization_section}
Conversation History:
{context}

Previous Draft:
{response}

Feedback:
{feedback}

Please provide an improved response addressing the feedback. Begin your response directly without meta-commentary.
"""


def parse_chat_feedback(feedback_text: str) -> Tuple[str, int]:
    """Extract feedback critique and an optional score (0-10). Defaults to 5/10 if score unparseable."""
    match = re.search(r"(?i)Total\s+score\s*:\s*(\d+)\s*/\s*(\d+)", feedback_text)
    if match:
        score = int(match.group(1))
        scale = int(match.group(2))
        normalized = int(round((score / scale) * 10)) if scale > 0 else 5
    else:
        # Graceful fallback: do not fail chat when model provides free-form feedback
        normalized = 7

    critique = feedback_text.strip()
    return critique, normalized


class ChatResponsePipeline:
    """Handles generation, feedback, and refinement for interactive chat."""

    def __init__(
        self,
        engine: str = "groq:qwen/qwen3.8-27b",
        max_attempts: int = 2,
        profile_path: str | Path = DEFAULT_PROFILE_PATH,
    ) -> None:
        self.engine = engine
        self.max_attempts = max_attempts
        self.profile_path = profile_path

    def _call_model(self, prompt: str, stage: str, max_tokens: int = 2048, stop_token: Optional[str] = None) -> str:
        output = openai_api.OpenaiAPIWrapper.call(
            stage=stage,
            prompt=prompt,
            engine=self.engine,
            max_tokens=max_tokens,
            stop_token=stop_token,
            temperature=0.7,
        )
        first_resp = openai_api.OpenaiAPIWrapper.get_first_response(output)
        if isinstance(first_resp, dict):
            content = first_resp.get("content", "")
        else:
            content = str(first_resp)
        return content.strip()

    def generate_initial(self, context: str, personalization: Optional[str] = None) -> str:
        instruction = CHAT_INSTRUCTION
        if personalization:
            instruction = f"{instruction} {personalization}"
        prompt = f"{instruction}\n\nConversation history:\n{context}\n\nAssistant:"
        return self._call_model(prompt, stage="generation")

    def get_feedback(self, context: str, response: str, personalization: Optional[str] = None) -> Tuple[str, int]:
        p_section = f"\n{personalization}\n" if personalization else ""
        p_criteria = "\n4. Adherence to user preferences" if personalization else ""
        prompt = FEEDBACK_PROMPT_TEMPLATE.format(
            personalization_section=p_section,
            personalization_criteria=p_criteria,
            context=context,
            response=response,
        )
        raw_feedback = self._call_model(prompt, stage="feedback", max_tokens=512)
        return parse_chat_feedback(raw_feedback)

    def refine(self, context: str, response: str, feedback: str, personalization: Optional[str] = None) -> str:
        p_section = f"\n{personalization}\n" if personalization else ""
        prompt = REFINE_PROMPT_TEMPLATE.format(
            personalization_section=p_section,
            context=context,
            response=response,
            feedback=feedback,
        )
        return self._call_model(prompt, stage="refinement")

    def generate_chat_response(self, context: str, mode: str = "self_refine") -> str:
        """Generate response in either 'standard' (single-pass) or 'self_refine' mode with personalization."""
        # Load user personalization instruction once per response generation
        personalization = load_personalization_instruction(self.profile_path)

        # 1. Initial generation (applies personalization instruction to both modes)
        initial_response = self.generate_initial(context, personalization=personalization)
        if not initial_response:
            raise InferenceError("Model returned an empty initial response.")

        # If Standard mode was chosen or max_attempts <= 1, do not perform feedback or refinement
        if mode == "standard" or self.max_attempts <= 1:
            return initial_response

        # 2. Refinement loop with graceful fallback to best response so far
        current_best = initial_response
        for _ in range(self.max_attempts - 1):
            try:
                feedback, score = self.get_feedback(context, current_best, personalization=personalization)
                # If already highly rated or critique says None, keep current best
                if "Critique Summary: None" in feedback or score >= 9:
                    break
                refined = self.refine(context, current_best, feedback, personalization=personalization)
                if refined and len(refined) > 5:
                    current_best = refined
            except Exception:
                # If feedback or refinement fails (e.g. rate limit, formatting),
                # preserve the already-generated initial/current best answer.
                break

        return current_best

