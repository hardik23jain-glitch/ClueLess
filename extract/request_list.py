"""
The "Ask your seller" request-list generator (B2C feature, P1-owned).

Static text only, taken from FIELD_SPECS. Per the safety rules, legal wording
never comes from an LLM. Two kinds of items:

  absent      -> "Ask for X": the document does not state it.
  unreadable  -> "Upload a clearer copy of X": we could not read it.

The B2C portal must never imply either means anything about title; these are
document-completeness prompts only.
"""

from __future__ import annotations

from .schema import SPEC_BY_KEY, DeedExtraction, FieldStatus

# The POA number is only requested when the seller actually acts via an attorney.
_CONDITIONAL = {"acting_through_poa.poa_reg_no": "acting_through_poa.is_attorney"}


def build_request_list(ex: DeedExtraction) -> list[dict]:
    items: list[dict] = []
    for key, f in ex.fields.items():
        spec = SPEC_BY_KEY[key]
        gate = _CONDITIONAL.get(key)
        if gate:
            g = ex.fields[gate]
            if not (g.status == FieldStatus.EXTRACTED and g.value is True):
                continue                      # not applicable: seller signs personally (or unknown)
        if f.status == FieldStatus.ABSENT:
            items.append({"field": key, "kind": "ask_seller", "text": f"Ask for: {spec.ask_seller}",
                          "doc_id": ex.doc_id, "page": f.evidence.page})
        elif f.status == FieldStatus.UNREADABLE:
            items.append({"field": key, "kind": "reupload", "text": f"Upload a clearer copy so we can read: {spec.ask_seller}",
                          "doc_id": ex.doc_id, "page": f.evidence.page})
    return items
