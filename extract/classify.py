"""
Step 6: turn the model's raw answer into contract fields: status + confidence.

This is the heart of "say needs-review instead of guessing".

Confidence is NOT the model's self-reported number. That number is poorly
calibrated, so it gets only 40% of the vote:

    confidence = 0.4 * model_confidence
               + 0.3 * format_valid        (validate.py)
               + 0.3 * grounded            (is the quote really on the page?)

grounded is 1.0 if the local reader sees the quote, 0.0 if it reads the page
reliably and does NOT see it, and 0.5 when no local text exists (unknown is
not the same as disagree). A read value with no quote at all is capped below
the threshold: evidence is mandatory. Then:

    >= extract_threshold            -> EXTRACTED
    otherwise                       -> UNREADABLE (value withheld, kept as candidate)

"not_stated" claims are checked too, because a wrong ABSENT creates a false
Class A flag: it is only trusted if the model is confident, the page quality is
acceptable, and no value is printed after the field's label (localtext.py).
"""

from __future__ import annotations

from typing import Any

from .config import Config
from .localtext import DocText, grounding_score, locate_quote, value_follows_label  # DocText() = no local text
from .redact import redact_text
from .schema import FIELD_SPECS, LANGUAGES, Evidence, Field, FieldStatus, FieldSpec
from .textutil import norm, partial_score
from .validate import check_value


def _clamp(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _page(x: Any):
    try:
        p = int(x)
        return p if p >= 1 else None
    except (TypeError, ValueError):
        return None


def _unreadable(note: str, candidate=None, conf: float = 0.0, ev: Evidence | None = None) -> Field:
    return Field(value=None, candidate=candidate, status=FieldStatus.UNREADABLE,
                 confidence=round(conf, 3), evidence=ev or Evidence(), notes=[note])


def classify_field(spec: FieldSpec, raw: Any, doc: DocText, quality_ok: bool, cfg: Config,
                   strict_ground: bool = True) -> Field:
    if not isinstance(raw, dict):
        return _unreadable("model did not return this field")

    state = str(raw.get("state", "")).strip().lower()
    mconf = _clamp(raw.get("confidence"))
    page = _page(raw.get("page"))
    quote = redact_text(raw.get("quote")) if raw.get("quote") else None
    value = redact_text(raw.get("value"))

    # ---- NOT STATED -------------------------------------------------
    if state == "not_stated":
        if not quality_ok:
            return _unreadable("model said 'not stated' but the page image is poor; cannot trust an absence")
        if value_follows_label(spec.key, doc):
            return _unreadable("model said 'not stated' but a value follows this field's label on the page")
        if mconf < cfg.absent_threshold:
            return _unreadable(f"'not stated' with low confidence ({mconf:.2f})", conf=mconf)
        return Field(value=None, status=FieldStatus.ABSENT, confidence=round(mconf, 3),
                     evidence=Evidence(page=page))

    # ---- ILLEGIBLE / unknown ---------------------------------------
    if state != "read":
        cand, _, _ = check_value(spec, value) if value is not None else (None, True, "")
        return _unreadable("model marked this illegible" if state == "illegible" else f"unexpected state '{state}'",
                           candidate=cand, conf=mconf * 0.5, ev=Evidence(page=page, quote=quote))

    # ---- READ -------------------------------------------------------
    if value is None:
        return _unreadable("model said 'read' but gave no value", ev=Evidence(page=page, quote=quote))

    norm_value, valid, vnote = check_value(spec, value)
    notes: list[str] = []
    if not valid:
        notes.append(vnote)

    g = grounding_score(quote, doc, page) if quote else None
    if g is None:
        g_comp = 0.5
    elif g >= cfg.ground_min_score:
        g_comp = 1.0
    elif strict_ground:
        g_comp = 0.0
        notes.append(f"quote not found on page by the local reader (score {g:.0f})")
    else:
        # Mixed printed/handwritten page: the local reader cannot read the
        # handwriting, so a miss is "unknown", not "disagree".
        g_comp = 0.5
        notes.append(f"quote not matched by the local reader (score {g:.0f}); page is mixed, so not held against it")

    # For plain text fields the value itself should sit inside its quote.
    if quote and spec.kind in ("str", "name") and isinstance(norm_value, str):
        if partial_score(norm(norm_value), norm(quote)) < 70:
            g_comp = min(g_comp, 0.0)
            notes.append("value does not appear inside its own quote")

    conf = 0.4 * mconf + 0.3 * (1.0 if valid else 0.0) + 0.3 * g_comp
    if not quote:
        conf = min(conf, cfg.extract_threshold - 0.01)
        notes.append("no supporting quote given; evidence is required")
    if not quality_ok:
        conf *= 0.85
        notes.append("page image quality is poor")

    ev_page, bbox, _ = locate_quote(quote, doc, page) if quote else (page, None, 0.0)
    ev = Evidence(page=ev_page if bbox else page, quote=quote, bbox=bbox)

    if conf >= cfg.extract_threshold and valid:
        return Field(value=norm_value, status=FieldStatus.EXTRACTED, confidence=round(conf, 3),
                     evidence=ev, notes=notes)
    return Field(value=None, candidate=norm_value, status=FieldStatus.UNREADABLE,
                 confidence=round(conf, 3), evidence=ev, notes=notes or ["below confidence threshold"])


def build_fields(model_json: dict, doc: DocText, quality_ok: bool, cfg: Config) -> tuple[dict[str, Field], str, str]:
    """
    Returns (fields, language, writing).

    Handwriting policy: Tesseract cannot read handwriting, so for a handwritten
    document the local cross-check is switched OFF entirely (the vision model is
    the only reader, and the report says so). For a mixed document the local
    reader still helps on the printed parts, but a miss is not held against a
    field. Only fully printed documents get the strict check.
    """
    is_dict = isinstance(model_json, dict)
    raw_fields = model_json.get("fields", model_json) if is_dict else {}
    lang = str(model_json.get("language", "other")).strip().lower() if is_dict else "other"
    writing = str(model_json.get("writing", "printed")).strip().lower() if is_dict else "printed"
    if writing not in ("printed", "handwritten", "mixed"):
        writing = "printed"

    use_doc = DocText() if writing == "handwritten" else doc
    strict = writing == "printed"
    fields = {s.key: classify_field(s, raw_fields.get(s.key), use_doc, quality_ok, cfg, strict_ground=strict)
              for s in FIELD_SPECS}
    return fields, (lang if lang in LANGUAGES else "other"), writing


def all_unreadable(reason: str) -> dict[str, Field]:
    """Used when the model call fails: every field needs review, nothing is guessed."""
    return {s.key: _unreadable(reason) for s in FIELD_SPECS}


def summarize(fields: dict[str, Field]) -> tuple[list[str], float]:
    needs = [k for k, f in fields.items() if f.status == FieldStatus.UNREADABLE]
    overall = sum(f.confidence for f in fields.values()) / max(1, len(fields))
    return needs, round(overall, 3)
