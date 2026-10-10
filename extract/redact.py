"""
Step 4: privacy. Remove Aadhaar / PAN numbers BEFORE any image leaves the machine.

How it works
------------
We need word boxes to know where a number sits on the page. They come from the
PDF text layer or Tesseract (localtext.py). A 12-digit number is treated as an
Aadhaar number only if its Verhoeff check digit validates (the real Aadhaar
checksum), which keeps random 12-digit numbers (registration IDs etc.) from
being blacked out. 16-digit VIDs and PAN patterns are also removed.

Fail-safe: if a page has no word boxes at all, redaction is "unverified". The
pipeline then refuses to call an external model unless the operator explicitly
allows it (synthetic data only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .ingest import Word
from .textutil import normalize_digits

_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(number: str) -> str:
    """Check digit to append to `number` (used by tests to build valid IDs)."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def is_aadhaar(digits: str) -> bool:
    return len(digits) == 12 and digits[0] in "23456789" and verhoeff_valid(digits)


_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR_TEXT = re.compile(r"(?<!\d)(\d{4})[\s\-]?(\d{4})[\s\-]?(\d{4})(?!\d)")


def redact_text(s):
    """Defence in depth for any string we output (quotes, values)."""
    if not isinstance(s, str):
        return s

    def _sub(m):
        d = "".join(m.groups())
        return "[AADHAAR REDACTED]" if is_aadhaar(d) else m.group(0)

    s = _AADHAAR_TEXT.sub(_sub, normalize_digits(s))
    return _PAN.sub("[PAN REDACTED]", s)


@dataclass
class RedactionReport:
    aadhaar: int = 0
    vid: int = 0
    pan: int = 0
    pages_unverified: list[int] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return not self.pages_unverified

    def as_dict(self) -> dict:
        return {"status": "verified" if self.verified else "unverified", "aadhaar": self.aadhaar,
                "vid": self.vid, "pan": self.pan, "pages_unverified": self.pages_unverified}


def _digits_only(t: str) -> str:
    # Strip punctuation glued to the token: "0124." at the end of a sentence,
    # "(2345", "6789," etc. Without this a number followed by a full stop
    # slipped through unredacted.
    d = normalize_digits(t).strip(".,;:()[]{}'\"-")
    return d if d.isdigit() else ""


def find_sensitive_boxes(words: list[Word]) -> tuple[list[Word], dict]:
    """Return the words to black out and counts by type."""
    hit: list[Word] = []
    counts = {"aadhaar": 0, "vid": 0, "pan": 0}
    n = len(words)
    consumed = [False] * n

    # Digit groups: 1x12, 3x4 (Aadhaar) and 4x4 / 1x16 (VID)
    for i in range(n):
        if consumed[i]:
            continue
        for span, lens, kind in ((4, (4, 4, 4, 4), "vid"), (3, (4, 4, 4), "aadhaar"), (1, (16,), "vid"), (1, (12,), "aadhaar")):
            grp = words[i:i + span]
            if len(grp) < span or any(consumed[i:i + span]):
                continue
            ds = [_digits_only(w.text) for w in grp]
            if not all(ds) or tuple(len(d) for d in ds) != lens:
                continue
            joined = "".join(ds)
            if kind == "aadhaar" and not is_aadhaar(joined):
                continue
            hit.extend(grp)
            counts[kind] += 1
            for k in range(i, i + span):
                consumed[k] = True
            break

    for i, w in enumerate(words):
        if not consumed[i] and _PAN.fullmatch(w.text.strip().upper()):
            hit.append(w)
            counts["pan"] += 1
    return hit, counts


def redact_page(image: np.ndarray, words: list[Word], digital: bool = False) -> tuple[np.ndarray, dict, bool]:
    """
    Black out sensitive words. Returns (image, counts, verified).
    A digital (text-layer) page with no words is genuinely blank: nothing to
    redact, and that is verified. A raster page with no words is unverified.
    """
    if not words:
        return image, {"aadhaar": 0, "vid": 0, "pan": 0}, digital
    boxes, counts = find_sensitive_boxes(words)
    out = image.copy()
    for w in boxes:
        pad = max(2, int(w.h * 0.15))
        cv2.rectangle(out, (int(w.x) - pad, int(w.y) - pad),
                      (int(w.x + w.w) + pad, int(w.y + w.h) + pad), (0, 0, 0), thickness=-1)
    return out, counts, True


def redact_pages(pages) -> tuple[list[np.ndarray], RedactionReport]:
    """Returns redacted images (same order as pages) and a report."""
    rep = RedactionReport()
    images = []
    for p in pages:
        img, counts, ok = redact_page(p.image, p.words, digital=p.has_text_layer)
        images.append(img)
        rep.aadhaar += counts["aadhaar"]
        rep.vid += counts["vid"]
        rep.pan += counts["pan"]
        if not ok:
            rep.pages_unverified.append(p.index)
    return images, rep
