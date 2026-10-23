"""Parse optional dialogue labels without discarding multiline responses."""
import re
from prompt_lib.backends.huggingface_api import InferenceError

def response_text(text):
    parts = re.split(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?Response:(?:\*\*)?\s*", text, maxsplit=1)
    value = parts[-1].split("###", 1)[0].strip()
    if not value:
        raise InferenceError("Dialogue model returned an empty response.")
    return value

def feedback_text(text):
    value = re.split(r"(?i)Scores:\s*", text, maxsplit=1)[-1].split("###", 1)[0].strip()
    # Accept Markdown emphasis around the score label and varying whitespace.
    value = value.replace("**", "")
    match = re.search(r"(?i)Total\s+score\s*:\s*(\d+)\s*/\s*(\d+)", value)
    if not match or not 0 <= int(match[1]) <= int(match[2]) or int(match[2]) == 0:
        raise InferenceError("Dialogue feedback did not provide a valid total score.")
    value = value[:match.start()] + f"Total score: {match[1]}/{match[2]}" + value[match.end():]
    return value
