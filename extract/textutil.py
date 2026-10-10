"""
Small text helpers shared by validation, grounding and redaction.

Borrowed ideas from the label-checker project's fields.py / fuzzy.py:
 * normalise Indic digits before any numeric pattern runs,
 * fuzzy "is this text really there" matching that survives OCR damage,
 * rapidfuzz when installed, difflib otherwise.
"""

from __future__ import annotations

import difflib
import re

try:  # pragma: no cover - depends on environment
    from rapidfuzz import fuzz as _rf
except Exception:  # pragma: no cover
    _rf = None

# Devanagari (Hindi/Marathi) and Bengali-Assamese digits -> ASCII.
_INDIC_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯", "01234567890123456789")


def normalize_digits(text: str) -> str:
    return (text or "").translate(_INDIC_DIGITS)


def norm(text: str) -> str:
    """Lowercase, Indic digits -> ASCII, punctuation -> space, collapse spaces.
    Keeps letters from every script (so Devanagari/Bengali words survive)."""
    t = normalize_digits(text or "").lower()
    t = re.sub(r"[^\w\s]|_", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def partial_score(needle: str, hay: str) -> float:
    """Best match (0-100) of `needle` anywhere inside `hay`, both pre-normalised."""
    if not needle or not hay:
        return 0.0
    if _rf is not None:
        return float(_rf.partial_ratio(needle, hay))
    n = len(needle)
    if n >= len(hay):
        return difflib.SequenceMatcher(None, needle, hay).ratio() * 100
    best = 0.0
    step = max(1, n // 8)
    for width in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(hay) - width + 1), step):
            r = difflib.SequenceMatcher(None, needle, hay[i:i + width]).ratio()
            if r > best:
                best = r
                if best > 0.98:
                    return best * 100
    return best * 100


def ratio(a: str, b: str) -> float:
    """Whole-string similarity 0-100."""
    if not a or not b:
        return 0.0
    if _rf is not None:
        return float(_rf.ratio(a, b))
    return difflib.SequenceMatcher(None, a, b).ratio() * 100
