"""Simple TXT-based conversation management for Self-Refine AI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Dict, List, Optional


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HEADER_DIVIDER = "=" * 40
MESSAGE_HEADER_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (USER|ASSISTANT):$"
)
CONV_ID_RE = re.compile(r"^chat_(\d+)\.txt$")

DEFAULT_MAX_CONTEXT_CHARS = 8000
TRUNCATION_NOTICE = (
    "[Earlier messages omitted to fit the model context window; "
    "full conversation is preserved on disk.]"
)


def _now_str() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def generate_title_from_query(query: str, max_length: int = 50) -> str:
    """Create a concise, single-line conversation title from a user query."""
    cleaned = " ".join((query or "").split()).strip()
    if not cleaned:
        return f"Chat {datetime.now().strftime('%Y-%m-%d')}"
    if len(cleaned) <= max_length:
        return cleaned
    truncated = cleaned[: max_length - 3].rsplit(" ", 1)[0].strip()
    if not truncated:
        truncated = cleaned[: max_length - 3].strip()
    return f"{truncated}..."


class ConversationManager:
    """Manages persistent terminal chat sessions stored as individual TXT files."""

    def __init__(self, chats_dir: str | Path = "chats") -> None:
        self.chats_dir = Path(chats_dir)
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def _conversation_path(self, conv_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", conv_id):
            raise ValueError(f"Invalid conversation ID: {conv_id!r}")
        return self.chats_dir / f"{conv_id}.txt"

    def _next_conversation_id(self) -> str:
        highest = 0
        for path in self.chats_dir.iterdir():
            if not path.is_file():
                continue
            match = CONV_ID_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"chat_{highest + 1:03d}"

    @staticmethod
    def _format_file(
        conv_id: str,
        title: str,
        created: str,
        updated: str,
        messages: List[Dict[str, str]],
    ) -> str:
        safe_title = " ".join((title or "").splitlines()).strip() or f"Chat {created[:10]}"
        lines = [
            HEADER_DIVIDER,
            f"Conversation ID: {conv_id}",
            f"Title: {safe_title}",
            f"Created: {created}",
            f"Last Updated: {updated}",
            HEADER_DIVIDER,
            "",
        ]
        for msg in messages:
            role = msg["role"].upper()
            timestamp = msg.get("timestamp") or updated
            content = msg["content"].rstrip("\n")
            lines.append(f"[{timestamp}] {role}:")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_file(path: Path) -> Dict[str, object]:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()

        conv_id = path.stem
        title = path.stem
        created = ""
        updated = ""

        # Parse header block between the two divider lines.
        idx = 0
        if idx < len(lines) and lines[idx].strip() == HEADER_DIVIDER:
            idx += 1
            while idx < len(lines) and lines[idx].strip() != HEADER_DIVIDER:
                line = lines[idx]
                if line.startswith("Conversation ID:"):
                    conv_id = line.split(":", 1)[1].strip()
                elif line.startswith("Title:"):
                    title = line.split(":", 1)[1].strip()
                elif line.startswith("Created:"):
                    created = line.split(":", 1)[1].strip()
                elif line.startswith("Last Updated:"):
                    updated = line.split(":", 1)[1].strip()
                idx += 1
            if idx < len(lines) and lines[idx].strip() == HEADER_DIVIDER:
                idx += 1

        messages: List[Dict[str, str]] = []
        current_role: Optional[str] = None
        current_ts: Optional[str] = None
        current_lines: List[str] = []

        def flush_current() -> None:
            if current_role is None:
                return
            # Trim single trailing blank separator line added between entries.
            body = list(current_lines)
            while body and body[-1] == "":
                body.pop()
            messages.append(
                {
                    "role": current_role.lower(),
                    "content": "\n".join(body),
                    "timestamp": current_ts or "",
                }
            )

        for line in lines[idx:]:
            match = MESSAGE_HEADER_RE.match(line)
            if match:
                flush_current()
                current_ts = match.group(1)
                current_role = match.group(2)
                current_lines = []
            elif current_role is not None:
                current_lines.append(line)

        flush_current()

        return {
            "id": conv_id,
            "title": title,
            "created": created,
            "updated": updated,
            "path": str(path),
            "messages": messages,
        }

    def create_conversation(self, title: Optional[str] = None) -> str:
        """Create a new conversation TXT file and return its unique ID."""
        conv_id = self._next_conversation_id()
        now = _now_str()
        resolved_title = (title or "").strip() or f"Chat {now[:10]}"
        path = self._conversation_path(conv_id)
        path.write_text(
            self._format_file(conv_id, resolved_title, now, now, []),
            encoding="utf-8",
        )
        return conv_id

    def update_title(self, conv_id: str, title: str) -> None:
        """Update the conversation title in its TXT file without altering history."""
        data = self.load_conversation(conv_id)
        updated = _now_str()
        path = self._conversation_path(conv_id)
        path.write_text(
            self._format_file(
                conv_id=str(data["id"]),
                title=title,
                created=str(data["created"]),
                updated=updated,
                messages=list(data["messages"]),  # type: ignore[arg-type]
            ),
            encoding="utf-8",
        )

    def list_conversations(self) -> List[Dict[str, str]]:
        """Return metadata for all saved conversations, newest updated first."""
        conversations: List[Dict[str, str]] = []
        for path in sorted(self.chats_dir.glob("*.txt")):
            if not path.is_file():
                continue
            parsed = self._parse_file(path)
            conversations.append(
                {
                    "id": str(parsed["id"]),
                    "title": str(parsed["title"]),
                    "created": str(parsed["created"]),
                    "updated": str(parsed["updated"]),
                    "path": str(parsed["path"]),
                }
            )
        conversations.sort(key=lambda item: (item["updated"], item["id"]), reverse=True)
        return conversations

    def load_conversation(self, conv_id: str) -> Dict[str, object]:
        """Load a conversation's metadata and full message history from disk."""
        path = self._conversation_path(conv_id)
        if not path.exists():
            raise FileNotFoundError(f"Conversation '{conv_id}' does not exist.")
        return self._parse_file(path)

    def save_message(self, conv_id: str, role: str, content: str) -> None:
        """Append a user or assistant message and update the Last Updated timestamp."""
        normalized_role = role.strip().lower()
        if normalized_role not in ("user", "assistant"):
            raise ValueError(f"Unsupported role: {role!r}. Expected 'user' or 'assistant'.")

        data = self.load_conversation(conv_id)
        now = _now_str()
        messages: List[Dict[str, str]] = list(data["messages"])  # type: ignore[arg-type]
        messages.append(
            {
                "role": normalized_role,
                "content": content,
                "timestamp": now,
            }
        )
        path = self._conversation_path(conv_id)
        path.write_text(
            self._format_file(
                conv_id=str(data["id"]),
                title=str(data["title"]),
                created=str(data["created"]),
                updated=now,
                messages=messages,
            ),
            encoding="utf-8",
        )

    def get_context_for_llm(
        self,
        conv_id: str,
        max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> str:
        """Build a context string for the LLM, truncating oldest turns if needed.

        The underlying TXT file is never modified when context is truncated.
        """
        if max_chars <= 0:
            raise ValueError("max_chars must be positive.")

        data = self.load_conversation(conv_id)
        messages: List[Dict[str, str]] = list(data["messages"])  # type: ignore[arg-type]
        if not messages:
            return ""

        formatted_turns = [
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        ]
        full_context = "\n".join(formatted_turns)
        if len(full_context) <= max_chars:
            return full_context

        # Keep the newest turns that fit within max_chars (preserving order).
        notice_prefix = f"{TRUNCATION_NOTICE}\n"
        budget = max(1, max_chars - len(notice_prefix))

        selected: List[str] = []
        used = 0
        for turn in reversed(formatted_turns):
            needed = len(turn) + (1 if selected else 0)
            if used + needed <= budget:
                selected.append(turn)
                used += needed
            else:
                break

        if not selected:
            # Even the single latest turn exceeds budget; keep its trailing tail.
            latest_tail = formatted_turns[-1][-budget:]
            return f"{notice_prefix}{latest_tail}" if max_chars > len(notice_prefix) else formatted_turns[-1][-max_chars:]

        selected.reverse()
        return f"{notice_prefix}" + "\n".join(selected)
