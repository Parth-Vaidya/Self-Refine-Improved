"""Execution summary generation, preference provenance resolution, and formatting."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.preference_extractor import PREFERENCE_RULES, detect_preferences_in_text


PREFERENCE_DISPLAY_NAMES: Dict[str, str] = {
    "prefers_step_by_step": "Step-by-step explanations",
    "prefers_concise_answers": "Concise answers",
    "prefers_simple_code": "Simple code",
    "prefers_examples": "Practical examples",
}

# Common description / phrase mapping to clean human-readable names
DESCRIPTION_CLEANING_MAP: Dict[str, str] = {
    "prefers step-by-step explanations": "Step-by-step explanations",
    "step-by-step explanations": "Step-by-step explanations",
    "step by step explanations": "Step-by-step explanations",
    "prefers short, concise answers": "Concise answers",
    "short, concise answers": "Concise answers",
    "concise answers": "Concise answers",
    "prefers simple and clean code implementations": "Simple code",
    "simple and clean code implementations": "Simple code",
    "simple code": "Simple code",
    "prefers practical examples and demonstrations": "Practical examples",
    "practical examples and demonstrations": "Practical examples",
    "practical examples": "Practical examples",
    "simple language": "Simple language",
}


def clean_preference_name(name_or_key: str) -> str:
    """Map internal preference keys or raw descriptions to clean, standard display names."""
    if not name_or_key:
        return ""
    raw = str(name_or_key).strip()

    # Exact key match
    if raw in PREFERENCE_DISPLAY_NAMES:
        return PREFERENCE_DISPLAY_NAMES[raw]

    lowered = raw.lower()
    if lowered in DESCRIPTION_CLEANING_MAP:
        return DESCRIPTION_CLEANING_MAP[lowered]

    # Strip leading "Prefers " or "prefers_"
    if lowered.startswith("prefers_"):
        raw = raw[8:]
    elif lowered.startswith("prefers "):
        raw = raw[8:]

    # Clean punctuation and underscores
    cleaned = raw.replace("_", " ").strip()
    # Normalize common phrases
    cleaned_lower = cleaned.lower()
    if "step" in cleaned_lower and "step" in cleaned_lower:
        return "Step-by-step explanations"
    if "concise" in cleaned_lower or "short" in cleaned_lower:
        return "Concise answers"
    if "code" in cleaned_lower and ("simple" in cleaned_lower or "clean" in cleaned_lower):
        return "Simple code"
    if "example" in cleaned_lower:
        return "Practical examples"

    # Capitalize first letter
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def scan_chats_for_preferences(chats_dir: str | Path = "chats") -> Set[str]:
    """Scan conversation history in chats_dir to find preferences originally extracted from chats."""
    chats_path = Path(chats_dir)
    found_keys: Set[str] = set()
    if not chats_path.is_dir():
        return found_keys

    for file_path in chats_path.glob("*.txt"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        # Check user lines
        for line in content.splitlines():
            line_str = line.strip()
            # Match user messages format: e.g. [2026-...] User: ... or User: ...
            if "user:" in line_str.lower():
                user_text = re.sub(r"(?i)^.*user:\s*", "", line_str)
                detected = detect_preferences_in_text(user_text)
                found_keys.update(detected)
    return found_keys


def resolve_preference_sources(
    applied_preferences: Optional[List[str] | Set[str]],
    query_text: Optional[str] = None,
    chats_dir: str | Path = "chats",
    profile_path: str | Path = "user_profile.json",
    profile_data: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str]]:
    """Determine preference provenance and format cleaned preference names.

    Distinguishes the original source of each preference:
    - 'Current Query': explicit preference instruction in the query text.
    - 'Previous Chats': preferences extracted from historical chats in chats_dir.
    - 'User Profile': preferences configured directly in profile without chat provenance.

    Returns:
        (sources_list, cleaned_preferences_list)
    """
    if not applied_preferences:
        return [], []

    applied_list = list(applied_preferences)
    # Standardize applied preferences into keys and clean names
    applied_keys: Set[str] = set()
    cleaned_names: List[str] = []

    for item in applied_list:
        clean = clean_preference_name(item)
        if clean and clean not in cleaned_names:
            cleaned_names.append(clean)

        # Match back to preference rule key
        matched_key = None
        for k, v in PREFERENCE_RULES.items():
            if k == item or v.get("description") == item or PREFERENCE_DISPLAY_NAMES.get(k) == clean:
                matched_key = k
                break
        if matched_key:
            applied_keys.add(matched_key)
        else:
            applied_keys.add(item)

    # 1. Query preferences
    query_prefs = detect_preferences_in_text(query_text or "")

    # 2. Previous chats preferences
    chats_prefs = scan_chats_for_preferences(chats_dir)

    # 3. Profile preferences
    if profile_data is None:
        p_path = Path(profile_path)
        if p_path.is_file():
            try:
                profile_data = json.loads(p_path.read_text(encoding="utf-8"))
            except Exception:
                profile_data = None

    profile_prefs: Set[str] = set()
    if isinstance(profile_data, dict):
        p_dict = profile_data.get("preferences", {})
        if isinstance(p_dict, dict):
            for k, v in p_dict.items():
                if isinstance(v, dict) and v.get("enabled") is True:
                    profile_prefs.add(k)
                elif v is True:
                    profile_prefs.add(k)

    sources_found: Set[str] = set()

    for k in applied_keys:
        in_query = k in query_prefs
        in_chats = k in chats_prefs
        in_profile = k in profile_prefs or not (in_query or in_chats)

        if in_query:
            sources_found.add("Current Query")
        if in_chats:
            sources_found.add("Previous Chats")
        elif in_profile and not in_query:
            # Stored in profile and not derived from chats or current query
            sources_found.add("User Profile")

    # Combine sources in consistent order
    ordered_sources: List[str] = []
    for s in ("Current Query", "User Profile", "Previous Chats"):
        if s in sources_found:
            ordered_sources.append(s)

    # When both Current Query and Previous Chats exist, put Current Query first
    # When User Profile and Previous Chats exist, User Profile first
    return ordered_sources, cleaned_names


def format_quality_score(
    score: Optional[Union[int, float]],
    max_score: Optional[Union[int, float]],
) -> str:
    """Format quality score and percentage or 'Quality: N/A' if invalid/unavailable."""
    if score is None or max_score is None:
        return "Quality: N/A"
    try:
        s = float(score)
        m = float(max_score)
        if m <= 0 or s < 0:
            return "Quality: N/A"
        pct = int(round((s / m) * 100))
        s_str = str(int(s)) if s.is_integer() else f"{s:.1f}"
        m_str = str(int(m)) if m.is_integer() else f"{m:.1f}"
        return f"Quality: {s_str}/{m_str} ({pct}%)"
    except (ValueError, TypeError, ZeroDivisionError):
        return "Quality: N/A"


def format_execution_summary(
    score: Optional[Union[int, float]] = None,
    max_score: Optional[Union[int, float]] = None,
    loops: int = 0,
    preference_sources: Optional[Union[str, List[str]]] = None,
    applied_preferences: Optional[List[str]] = None,
    applied: bool = False,
) -> str:
    """Generate the standardized compact, one-line execution summary string.

    Format:
    [SELF-REFINE SUMMARY] Quality: <score>/<max> (<pct>%) | Loops: <loops> | Preference Source: <sources> | Preferences: <preferences> | Applied: <Yes/No>
    """
    quality_str = format_quality_score(score, max_score)

    loops_str = f"Loops: {max(0, int(loops))}"

    if applied and preference_sources:
        if isinstance(preference_sources, list):
            source_val = " + ".join(preference_sources) if preference_sources else "None"
        else:
            source_val = str(preference_sources).strip() or "None"
    else:
        source_val = "None"
    source_str = f"Preference Source: {source_val}"

    if applied and applied_preferences:
        cleaned = []
        for p in applied_preferences:
            cn = clean_preference_name(p)
            if cn and cn not in cleaned:
                cleaned.append(cn)
        prefs_val = ", ".join(cleaned) if cleaned else "None"
    else:
        prefs_val = "None"
    prefs_str = f"Preferences: {prefs_val}"

    applied_str = f"Applied: {'Yes' if applied else 'No'}"

    return f"[SELF-REFINE SUMMARY] {quality_str} | {loops_str} | {source_str} | {prefs_str} | {applied_str}"


def get_summary_metadata(
    score: Optional[Union[int, float]] = None,
    max_score: Optional[Union[int, float]] = None,
    loops: int = 0,
    preference_sources: Optional[Union[str, List[str]]] = None,
    applied_preferences: Optional[List[str]] = None,
    applied: bool = False,
) -> Dict[str, Any]:
    """Return dictionary with structured summary fields and formatted text."""
    summary_line = format_execution_summary(
        score=score,
        max_score=max_score,
        loops=loops,
        preference_sources=preference_sources,
        applied_preferences=applied_preferences,
        applied=applied,
    )

    quality_text = format_quality_score(score, max_score)
    quality_pct = None
    if score is not None and max_score is not None and max_score > 0:
        try:
            quality_pct = int(round((float(score) / float(max_score)) * 100))
        except Exception:
            quality_pct = None

    if applied and preference_sources:
        if isinstance(preference_sources, list):
            source_val = " + ".join(preference_sources) if preference_sources else "None"
        else:
            source_val = str(preference_sources).strip() or "None"
    else:
        source_val = "None"

    cleaned = []
    if applied and applied_preferences:
        for p in applied_preferences:
            cn = clean_preference_name(p)
            if cn and cn not in cleaned:
                cleaned.append(cn)

    return {
        "quality_score": score,
        "max_quality_score": max_score,
        "quality_percentage": quality_pct,
        "quality_display": quality_text,
        "loops": max(0, int(loops)),
        "preference_source": source_val,
        "preferences": cleaned,
        "preferences_display": ", ".join(cleaned) if cleaned else "None",
        "applied": applied,
        "summary_line": summary_line,
    }
