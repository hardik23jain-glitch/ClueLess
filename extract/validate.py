"""
Step 5b: parse the model's reply and check every value's FORMAT.

Two jobs:
  1. `parse_model_json`: tolerate the usual LLM JSON mess (fences, trailing
     commas) without ever inventing data. Anything unparseable -> an error the
     pipeline turns into "everything unreadable", never a guess.
  2. `check_value`: per-field-kind normalisation + validity. Validity is one of
     the three signals that make up confidence (see classify.py). A value that
     fails its format (a 9-character ULPIN, an impossible date) cannot be
     trusted however confident the model sounded.

Indic digits are normalised first (Devanagari / Bengali-Assamese), a trick from
the label-checker's fields.py: every numeric pattern then works on any script.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional

from .schema import AREA_UNITS, FieldSpec
from .textutil import normalize_digits

# ---------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------


class ModelOutputError(ValueError):
    pass


def parse_model_json(raw: str) -> dict:
    s = (raw or "").strip()
    if "```" in s:
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if m:
            s = m.group(1).strip()
    s = re.sub(r",\s*([\]}])", r"\1", s)            # trailing commas
    # strict=False tolerates raw newlines/tabs inside strings, which models emit
    # when quoting multi-line text from a page.
    try:
        data = json.loads(s, strict=False)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)       # outermost object
        if not m:
            raise ModelOutputError("model reply contained no JSON object")
        try:
            data = json.loads(m.group(0), strict=False)
        except json.JSONDecodeError as e:
            raise ModelOutputError(f"model JSON could not be parsed: {e}")
    if not isinstance(data, dict):
        raise ModelOutputError("model JSON was not an object")
    return data


# ---------------------------------------------------------------------
# Value checks
# ---------------------------------------------------------------------
_UNIT_ALIASES = {
    "sqft": "sqft", "sq ft": "sqft", "sq.ft": "sqft", "sq. ft.": "sqft", "square feet": "sqft",
    "square foot": "sqft", "वर्ग फुट": "sqft", "वर्गफुट": "sqft",
    "sqm": "sqm", "sq m": "sqm", "sq.m": "sqm", "square meter": "sqm", "square metre": "sqm", "वर्ग मीटर": "sqm",
    "sqyd": "sqyd", "sq yd": "sqyd", "sq.yd": "sqyd", "square yard": "sqyd", "square yards": "sqyd", "गज": "sqyd",
    "acre": "acre", "acres": "acre", "एकड़": "acre",
    "hectare": "hectare", "hectares": "hectare", "ha": "hectare", "हेक्टेयर": "hectare",
    "bigha": "bigha", "bighas": "bigha", "बीघा": "bigha", "বিঘা": "bigha",
    "katha": "katha", "kattha": "katha", "kathas": "katha", "कट्ठा": "katha", "কঠা": "katha",
    "biswa": "biswa", "बिस्वा": "biswa",
    "gunta": "gunta", "guntha": "gunta", "गुंठा": "gunta",
    "cent": "cent", "cents": "cent",
    "marla": "marla", "marlas": "marla",
    "kanal": "kanal", "kanals": "kanal",
}
_DOC_TYPE_ALIASES = {"sale deed": "sale_deed", "agreement to sell": "agreement_to_sell", "power of attorney": "poa",
                     "gpa": "poa", "gift deed": "gift", "partition deed": "partition", "legal heir": "succession",
                     "succession certificate": "succession"}


def _parse_date(v: Any) -> Optional[str]:
    s = normalize_digits(str(v)).strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)      # Indian dd/mm/yyyy
        if not m:
            return None
        d, mo, y = map(int, m.groups())
    try:
        dt = date(y, mo, d)
    except ValueError:
        return None
    if not (1800 <= dt.year <= date.today().year + 1):
        return None
    return dt.isoformat()


def _parse_number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    s = normalize_digits(str(v))
    s = re.sub(r"[₹,\s]|rs\.?|inr|/-", "", s, flags=re.I)
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n >= 0 else None


def check_value(spec: FieldSpec, value: Any) -> tuple[Any, bool, str]:
    """
    Normalise `value` for this field. Returns (normalised_value, valid, note).
    A null value is returned as (None, True, "") - nothing to validate.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, True, ""
    k = spec.kind

    if k in ("str", "name"):
        return str(value).strip(), True, ""

    if k == "bool":
        if isinstance(value, bool):
            return value, True, ""
        s = str(value).strip().lower()
        if s in ("true", "yes", "1"):
            return True, True, ""
        if s in ("false", "no", "0"):
            return False, True, ""
        return value, False, f"'{value}' is not true/false"

    if k == "date":
        iso = _parse_date(value)
        return (iso, True, "") if iso else (value, False, f"'{value}' is not a valid date")

    if k == "number":
        n = _parse_number(value)
        return (n, True, "") if n is not None else (value, False, f"'{value}' is not a number")

    if k == "year":
        n = _parse_number(value)
        if n is not None and 1800 <= int(n) <= date.today().year and float(n).is_integer():
            return int(n), True, ""
        return value, False, f"'{value}' is not a plausible year"

    if k == "ulpin":
        s = re.sub(r"[\s\-]", "", str(value)).upper()
        # ULPIN (Bhu-Aadhaar) is 14 alphanumeric characters.
        return (s, True, "") if re.fullmatch(r"[A-Z0-9]{14}", s) else (str(value), False, "ULPIN must be 14 alphanumeric characters")

    if k == "unit":
        s = str(value).strip().lower()
        u = _UNIT_ALIASES.get(s, s if s in AREA_UNITS else None)
        return (u, True, "") if u else (str(value), False, f"unknown area unit '{value}'")

    if k == "enum":
        s = str(value).strip().lower().replace("-", "_")
        s = _DOC_TYPE_ALIASES.get(s, s.replace(" ", "_"))
        return (s, True, "") if s in spec.choices else (str(value), False, f"'{value}' is not one of {list(spec.choices)}")

    return value, True, ""
