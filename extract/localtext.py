"""
Step 3: the LOCAL text layer: a second, independent reader of every page.

Why it exists
-------------
A vision LLM can hallucinate a well-formed value that is not on the page. The
label-checker project learned this the hard way ("a wrong fact is worse than a
missing one"). So we never trust the model alone: wherever possible we ask a
local reader (PDF text layer, else Tesseract) "is this quote really on this
page?". That single check drives three things:

  * grounding   : does the model's quote appear on the page?  (confidence)
  * evidence    : where on the page is it?  (bbox, best-effort)
  * absent check: the model says "not stated" but the label word is on the
                  page, so something is off  (downgrade to needs-review)

Word boxes also let redact.py black out Aadhaar numbers BEFORE the image is
sent to any external API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import cv2

from .config import Config
from .ingest import Page, Word
from .textutil import norm, partial_score, ratio


def configure_tesseract() -> None:
    """
    Point pytesseract at the Tesseract binary when it is not on PATH (the
    Windows installer often does not add it). Order: TESSERACT_CMD env var,
    then the default install folders. No system settings are changed.
    """
    import os
    import shutil
    from pathlib import Path

    try:
        import pytesseract
    except Exception:
        return
    if shutil.which("tesseract"):
        return
    candidates = [os.getenv("TESSERACT_CMD", ""),
                  r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
    for c in candidates:
        if c and Path(c).exists():
            pytesseract.pytesseract.tesseract_cmd = c
            return


configure_tesseract()


@lru_cache(maxsize=1)
def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _tesseract_words(image, langs: str) -> list[Word]:
    import pytesseract

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Languages degrade gracefully: a missing Hindi pack must not kill English.
    candidates = [langs, "eng"] if langs != "eng" else ["eng"]
    last_err: Optional[Exception] = None
    for lang in candidates:
        try:
            d = pytesseract.image_to_data(gray, lang=lang, config="--oem 3 --psm 6",
                                          output_type=pytesseract.Output.DICT)
            words = []
            for i, t in enumerate(d["text"]):
                t = (t or "").strip()
                try:
                    conf = float(d["conf"][i])
                except (ValueError, TypeError):
                    conf = -1.0
                if t and conf >= 0:
                    words.append(Word(t, d["left"][i], d["top"][i], d["width"][i], d["height"][i], conf))
            return words
        except Exception as e:  # pragma: no cover - depends on installed packs
            last_err = e
    raise RuntimeError(f"Tesseract failed: {last_err}")


@dataclass
class PageText:
    index: int
    words: list[Word]
    text: str            # normalised, for matching
    source: str          # "text_layer" | "tesseract" | "none"
    reliable: bool       # enough, confident text to judge disagreement


@dataclass
class DocText:
    pages: dict[int, PageText] = field(default_factory=dict)
    source: str = "none"

    @property
    def full_text(self) -> str:
        return " ".join(p.text for p in self.pages.values())

    @property
    def available(self) -> bool:
        return any(p.reliable for p in self.pages.values())


def build_doctext(pages: list[Page], cfg: Config) -> DocText:
    """Fill page.words (running Tesseract on raster pages) and build DocText."""
    doc = DocText()
    sources = set()
    for p in pages:
        if p.has_text_layer:
            src = "text_layer"
        elif tesseract_available():
            try:
                p.words = _tesseract_words(p.image, cfg.ocr_langs)
                src = "tesseract"
            except Exception:
                p.words, src = [], "none"
        else:
            p.words, src = [], "none"

        text = norm(" ".join(w.text for w in p.words))
        if src == "text_layer":
            reliable = len(p.words) >= 20
        elif src == "tesseract":
            mean_conf = sum(w.conf for w in p.words) / len(p.words) if p.words else 0.0
            reliable = len(p.words) >= 20 and mean_conf >= 60.0
        else:
            reliable = False
        doc.pages[p.index] = PageText(p.index, p.words, text, src, reliable)
        if src != "none":
            sources.add(src)
    doc.source = "text_layer" if sources == {"text_layer"} else ("tesseract" if "tesseract" in sources else (
        "mixed" if sources else "none"))
    return doc


# ---------------------------------------------------------------------
# Grounding + location
# ---------------------------------------------------------------------
def grounding_score(quote: str, doc: DocText, page: Optional[int]) -> Optional[float]:
    """
    0-100 similarity of `quote` to the page text, or None when no reliable local
    text exists (unknown is NOT the same as disagree).
    """
    q = norm(quote)
    if not q:
        return None
    pts = [doc.pages[page]] if page in doc.pages else list(doc.pages.values())
    pts = [pt for pt in pts if pt.reliable]
    if not pts:
        return None
    return max(partial_score(q, pt.text) for pt in pts)


def locate_quote(quote: str, doc: DocText, page: Optional[int]) -> tuple[Optional[int], Optional[list[float]], float]:
    """
    Best-effort evidence box: slide a window of words over the page and keep the
    best fuzzy match. Returns (page, [x, y, w, h], score). Candidate window
    starts are limited to words that equal a quote word, which keeps this fast.
    """
    qtokens = norm(quote).split()
    if not qtokens:
        return page, None, 0.0
    qset = {t: k for k, t in reversed(list(enumerate(qtokens)))}   # token -> first offset
    qjoined = " ".join(qtokens)
    n = len(qtokens)

    best: tuple[float, Optional[int], Optional[list[float]]] = (0.0, page, None)
    page_ids = [page] if page in doc.pages else list(doc.pages.keys())
    for pid in page_ids:
        words = doc.pages[pid].words
        wn = [norm(w.text) for w in words]
        starts = set()
        for i, t in enumerate(wn):
            if t in qset:
                starts.add(max(0, i - qset[t]))
        for s in starts:
            for width in {n, n + 1, max(1, n - 1)}:
                chunk = words[s:s + width]
                if not chunk:
                    continue
                score = ratio(qjoined, " ".join(wn[s:s + width]))
                if score > best[0]:
                    x0 = min(w.x for w in chunk)
                    y0 = min(w.y for w in chunk)
                    x1 = max(w.x + w.w for w in chunk)
                    y1 = max(w.y + w.h for w in chunk)
                    best = (score, pid, [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)])
    score, pid, bbox = best
    return pid, (bbox if score >= 70 else None), score


# ---------------------------------------------------------------------
# Label keywords: "does a VALUE follow this field's label on the page?"
# Used to catch the model saying "not stated" when the page plainly shows a
# value next to the label. A label with nothing after it ("Stamp duty: ____")
# is a legitimately ABSENT field and must NOT trigger this, otherwise Class A
# rules (A1/A5/A6) could never fire. So we require a digit shortly after the
# label. Only numeric-valued fields are checked; names, boundaries and the POA
# number are left to the model (their labels appear in boilerplate).
# ---------------------------------------------------------------------
ANCHORS: dict[str, tuple[str, ...]] = {
    "property.ulpin": ("ulpin", "bhu aadhaar", "भू आधार"),
    "property.survey_no": ("survey no", "survey number", "khasra", "khata", "plot no", "सर्वे", "खसरा", "खाता"),
    "consideration": ("consideration", "sale price", "प्रतिफल", "विक्रय मूल्य"),
    "stamp_duty": ("stamp duty", "e stamp", "estamp", "स्टाम्प"),
    "registration_no": ("registration no", "registration number", "document no", "पंजीयन"),
    "property.area_value": ("area", "sq ft", "sq ft", "bigha", "katha", "क्षेत्रफल"),
}
_LOOKAHEAD = 14
# Amount fields must show a currency marker right before the digits. Without
# this, "Stamp Duty under Article 31 of the Stamp Act, 1899 works out to Rs ....."
# (a blank amount) looked like a stated value because of "31" and "1899".
_AMOUNT_KEYS = {"consideration", "stamp_duty"}
_CURRENCY_THEN_DIGIT = re.compile(r"\b(?:rs|inr|rupees)\b\s*\d|रु\s*\d|₹\s*\d")


def value_follows_label(key: str, doc: DocText) -> bool:
    anchors = [norm(a) for a in ANCHORS.get(key, ()) if norm(a)]
    if not anchors:
        return False
    for pt in doc.pages.values():
        if not pt.reliable:
            continue
        for a in anchors:
            start = 0
            while True:
                i = pt.text.find(a, start)
                if i < 0:
                    break
                tail = pt.text[i + len(a): i + len(a) + _LOOKAHEAD]
                if key in _AMOUNT_KEYS:
                    if _CURRENCY_THEN_DIGIT.search(tail):
                        return True
                elif any(ch.isdigit() for ch in tail):
                    return True
                start = i + len(a)
    return False
