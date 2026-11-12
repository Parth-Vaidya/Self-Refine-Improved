"""Conservative pacing shared by local Groq processes; no quota reset."""
import math
import os
import sqlite3
import sys
import time
from contextlib import closing
from email.utils import parsedate_to_datetime
from prompt_lib.backends.huggingface_api import InferenceError


DEFAULT_RETRY_DELAY = 5.0


def wait(seconds, reason=None, attempt=None, max_retries=None):
    if seconds <= 0:
        return
    if attempt is not None and max_retries is not None:
        why = reason or "Rate limit exceeded"
        print(
            f"[Groq] {why}. Attempt {attempt}/{max_retries}. "
            f"Waiting {seconds:.1f} seconds before retrying...",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(f"[Groq] Waiting {seconds:.1f} seconds before the next request...", file=sys.stderr, flush=True)
    # Small sleeps keep long provider cooldowns interruptible.
    while seconds > 0:
        chunk = min(seconds, 30)
        time.sleep(chunk)
        seconds -= chunk


def pace():
    try:
        interval = float(os.getenv("GROQ_MIN_INTERVAL_SECONDS", "0"))
        if not math.isfinite(interval) or not 0 <= interval <= 3600:
            raise ValueError()
    except ValueError:
        raise InferenceError("GROQ_MIN_INTERVAL_SECONDS must be between 0 and 3600.") from None
    if interval == 0:
        return
    from prompt_lib.backends.request_budget import LEDGER
    try:
        if not LEDGER.is_file():
            raise ValueError()
        with closing(sqlite3.connect(str(LEDGER), timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS groq_pacing (id INTEGER PRIMARY KEY, next_at REAL NOT NULL)")
            row = db.execute("SELECT next_at FROM groq_pacing WHERE id=1").fetchone()
            now = time.time()
            slot = max(now, row[0] if row else now)
            db.execute("INSERT OR REPLACE INTO groq_pacing VALUES (1, ?)", (slot + interval,))
    except (sqlite3.Error, ValueError):
        raise InferenceError("Groq pacing ledger unavailable; request blocked.") from None
    wait(max(0, slot - time.time()))


def retry_delay(header, status, default_delay=None):
    if default_delay is None:
        try:
            default_delay = float(os.getenv("GROQ_DEFAULT_RETRY_DELAY", "5.0"))
            if not math.isfinite(default_delay) or default_delay < 0:
                default_delay = DEFAULT_RETRY_DELAY
        except (ValueError, TypeError):
            default_delay = DEFAULT_RETRY_DELAY

    fallback = default_delay if status == 429 else 0.0
    if not header:
        return fallback
    try:
        delay = float(header)
    except (ValueError, TypeError):
        try:
            delay = parsedate_to_datetime(header).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return fallback
    if not math.isfinite(delay):
        return fallback
    if delay > 3600:
        raise InferenceError("Groq requested a cooldown longer than one hour; run stopped to avoid further requests.")
    return max(0.0, delay)
