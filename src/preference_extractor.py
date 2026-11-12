"""Simple rule-based user preference extraction and profile storage."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Set

from src.conversation_manager import ConversationManager
from src.output import redact


DEFAULT_PROFILE_PATH = "user_profile.json"

# Simple keyword and regex pattern rules mapping to preference keys and descriptions
PREFERENCE_RULES: Dict[str, Dict[str, object]] = {
    "prefers_step_by_step": {
        "description": "Prefers step-by-step explanations",
        "patterns": [
            r"\bstep[\s-]by[\s-]step\b",
            r"\bbreak\s+it\s+down\b",
            r"\bwalk\s+me\s+through\b",
        ],
    },
    "prefers_concise_answers": {
        "description": "Prefers short, concise answers",
        "patterns": [
            r"\bkeep\s+it\s+short\b",
            r"\bbe\s+concise\b",
            r"\bbrief\b",
            r"\bshort\s+answer\b",
            r"\bto\s+the\s+point\b",
            r"\bin\s+a\s+nutshell\b",
        ],
    },
    "prefers_simple_code": {
        "description": "Prefers simple and clean code implementations",
        "patterns": [
            r"\bsimple\s+code\b",
            r"\beasy\s+code\b",
            r"\bclean\s+code\b",
            r"\bwithout\s+complex\s+libraries\b",
            r"\bbasic\s+code\b",
        ],
    },
    "prefers_examples": {
        "description": "Prefers practical examples and demonstrations",
        "patterns": [
            r"\b(?:give|show|provide)\s+(?:me\s+)?(?:an?\s+)?examples?\b",
            r"\bwith\s+an?\s+examples?\b",
            r"\bexamples?\s+please\b",
            r"\bpractical\s+examples?\b",
        ],
    },
}


def detect_preferences_in_text(text: str) -> Set[str]:
    """Detect preferences in a single user message using simple regex rules."""
    detected: Set[str] = set()
    cleaned = (text or "").lower()
    for pref_key, rule in PREFERENCE_RULES.items():
        patterns = rule.get("patterns", [])
        for pattern in patterns:
            if re.search(pattern, cleaned):
                detected.add(pref_key)
                break
    return detected


class UserProfileManager:
    """Extracts preferences from conversation files and maintains user_profile.json."""

    def __init__(
        self,
        chats_dir: str | Path = "chats",
        profile_path: str | Path = DEFAULT_PROFILE_PATH,
    ) -> None:
        self.conv_manager = ConversationManager(chats_dir=chats_dir)
        self.profile_path = Path(profile_path)

    def load_profile(self) -> Dict[str, object]:
        """Load the profile from disk or return a blank template if not present or corrupt."""
        if not self.profile_path.exists():
            return {
                "last_updated": None,
                "preferences": {},
            }
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Profile root must be an object.")
            data.setdefault("preferences", {})
            return data
        except Exception:
            # If the user edited and introduced invalid JSON, return template without crashing
            return {
                "last_updated": None,
                "preferences": {},
            }

    def save_profile(self, profile: Dict[str, object]) -> None:
        """Persist profile to JSON, ensuring credentials and tokens are redacted."""
        profile["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        serialized = json.dumps(profile, indent=2, ensure_ascii=False)
        safe_serialized = redact(serialized)
        self.profile_path.write_text(safe_serialized, encoding="utf-8")

    def extract_from_conversations(self) -> Dict[str, object]:
        """Scan all conversation TXT files, detect user preferences, and update profile."""
        profile = self.load_profile()
        current_preferences: Dict[str, object] = dict(profile.get("preferences", {}))

        conversations = self.conv_manager.list_conversations()
        for item in conversations:
            conv_id = item["id"]
            conv_data = self.conv_manager.load_conversation(conv_id)
            messages = conv_data.get("messages", [])

            for msg in messages:
                # Extract preferences strictly from user turns
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                detected = detect_preferences_in_text(content)

                for pref_key in detected:
                    rule = PREFERENCE_RULES.get(pref_key, {})
                    if pref_key not in current_preferences:
                        current_preferences[pref_key] = {
                            "description": rule.get("description", pref_key),
                            "enabled": True,
                        }

        profile["preferences"] = current_preferences
        self.save_profile(profile)
        return profile


def main() -> None:
    """CLI utility to scan conversations and update user_profile.json."""
    manager = UserProfileManager()
    profile = manager.extract_from_conversations()
    count = len(profile.get("preferences", {}))
    print(f"User profile updated successfully with {count} preference(s): {manager.profile_path}")
    for k, v in profile.get("preferences", {}).items():
        desc = v.get("description", "") if isinstance(v, dict) else ""
        print(f" - {k}: {desc}")


if __name__ == "__main__":
    main()

