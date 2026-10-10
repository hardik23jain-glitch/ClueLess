"""
The bridge between P1's extraction (contract v1.1) and P2's rules engine.

The engine reads a plain nested dict (doc["seller"]["name"], doc["acting_through_poa"]
= {"used", "poa_reg_no"}, ...). Extraction produces flat field objects with a status.
Feeding one to the other directly gives false Class A flags, because the engine has
no concept of "unreadable". This module converts and enforces the rule:

    extracted  -> the value
    absent     -> None            (the engine may flag it: that is Class A working)
    unreadable -> None + listed as UNKNOWN. Any engine flag that rests on an unknown
                  field is DROPPED and replaced by a NEEDS_REVIEW item. We never raise
                  a registrability flag on something we could not read.

It also attaches page/quote/box evidence to every flag from the extraction.

Use:  result = run_rules_on_extraction(ex, bundle_docs)   # bundle_docs: list of rules-docs
"""

from __future__ import annotations

import re
from typing import Any

from .schema import DeedExtraction, FieldStatus

_RENAME = {"acting_through_poa.is_attorney": "acting_through_poa.used"}   # engine's name for it


def _set(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def to_rules_doc(ex: DeedExtraction) -> dict:
    doc: dict[str, Any] = {"doc_id": ex.doc_id}
    unknown: list[str] = []
    for key, f in ex.fields.items():
        path = _RENAME.get(key, key)
        _set(doc, path, f.value if f.status == FieldStatus.EXTRACTED else None)
        if f.status == FieldStatus.UNREADABLE:
            unknown.append(path)
    doc["_unknown"] = unknown
    return doc


def _touches(flag_path: str, unknown: list[str]) -> bool:
    """A flag rests on an unknown field if the paths are equal or one contains the other."""
    return any(flag_path == u or u.startswith(flag_path + ".") or flag_path.startswith(u + ".")
               for u in unknown if flag_path)


def _evidence(ex: DeedExtraction, field_path: str) -> list[dict]:
    # A1 fires on the missing POA number, but the evidence worth showing is the
    # "acting through an attorney" text, which sits on the sibling is_attorney field.
    if field_path.startswith("acting_through_poa"):
        field_path = "acting_through_poa"
    out = []
    for key, f in ex.fields.items():
        path = _RENAME.get(key, key)
        if path == field_path or path.startswith(field_path + ".") or key == field_path:
            if f.evidence.page or f.evidence.quote:
                out.append({"doc_id": ex.doc_id, "field": key, "page": f.evidence.page,
                            "quote": f.evidence.quote, "bbox": f.evidence.bbox})
    return out


def as_rules_doc(x: Any) -> dict:
    """Accept a DeedExtraction, an extraction JSON dict (has 'fields' + 'provenance'), or a plain engine dict."""
    if isinstance(x, DeedExtraction):
        return to_rules_doc(x)
    if isinstance(x, dict) and "fields" in x and "provenance" in x:
        return to_rules_doc(DeedExtraction.model_validate(x))
    return x


def _digits(s: Any) -> set:
    return set(re.findall(r"\d+", str(s or "")))


def link_parent(doc: dict, bundle_docs: list[dict]) -> None:
    """
    The engine finds a parent deed only when parent_ref.doc_ref equals a bundle doc_id, but a deed
    says things like "Deed No. 1187 of 2015". Match that text to a bundle deed by its registration
    number (all the number groups in the registration no. must appear in the reference) and rewrite
    doc_ref to that deed's doc_id. No match: leave it, and the engine safely skips A7/B3.
    """
    pr = doc.get("parent_ref")
    ref = pr.get("doc_ref") if isinstance(pr, dict) else None
    if not ref:
        return
    ref_digits = _digits(ref)
    for b in bundle_docs:
        if str(b.get("doc_id")) == str(ref):
            return
        reg = _digits(b.get("registration_no"))
        if reg and reg <= ref_digits:
            pr["doc_ref"] = str(b["doc_id"])
            return


def run_rules_on_extraction(ex: DeedExtraction, bundle: list | None = None, as_of=None) -> dict:
    """
    Returns {"class_a_flags": [...], "class_b_flags": [...], "needs_review": [...]} (flag dicts).
    `bundle` = the other uploaded deeds (DeedExtractions, extraction dicts or plain engine dicts).
    """
    from rules.engine import HARD_STOP, WARNING, evaluate_document   # P2's module

    doc = to_rules_doc(ex)
    unknown = doc["_unknown"]
    bundle_docs = [as_rules_doc(b) for b in (bundle or [])]
    link_parent(doc, bundle_docs)
    index = {str(d.get("doc_id", i)): d for i, d in enumerate(bundle_docs)}
    flags = evaluate_document(doc, bundle=index, as_of=as_of)

    keep = [f for f in flags if not _touches(f.field_path, unknown)]
    a = [f.to_dict() for f in keep if f.severity == HARD_STOP]
    b = [f.to_dict() for f in keep if f.severity == WARNING]
    for item in a + b:
        item["evidence"] = _evidence(ex, item.get("field_path", ""))

    review = [{
        "flag_id": "R0", "class": "R", "severity": "NEEDS_REVIEW", "code": "FIELD_UNREADABLE",
        "document_id": ex.doc_id, "field_path": key,
        "title": f"Could not read: {key}",
        "detail": "This field could not be read reliably, so no checks that depend on it were run. "
                  "This is not a finding about the deed.",
        "mitigation": "A human reviewer should read the field, or a clearer copy should be uploaded.",
        "evidence": _evidence(ex, key),
    } for key in ex.needs_review]
    return {"class_a_flags": a, "class_b_flags": b, "needs_review": review}
