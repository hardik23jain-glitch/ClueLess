"""
Advocate hand-off brief: deterministic, from a CURATED STATIC LIBRARY, no LLM.

Why not an LLM: the project's safety rule is that legal explanations come from a fixed,
reviewed library and never imply a title conclusion. A free-text LLM brief (the first version of
brief_agent.mjs) wrote things like "indicates a serious problem with the property's title".
Everything below is fixed wording; only the flag codes, field names and the user's own
document quotes are filled in.

Language rules enforced by tests: never "clean", "safe", "verified title", or a score.
"""

from __future__ import annotations

from typing import Any, Dict, List

# code -> (what it means in plain words, what to ask for)
LIBRARY: Dict[str, tuple] = {
    "POA_REGISTRATION_MISSING": (
        "The seller signed through an attorney (power of attorney), but the deed gives no registration number for that power of attorney.",
        "The registered power of attorney and its registration number."),
    "PROPERTY_AREA_MISSING": (
        "The deed does not state the property's area and unit clearly.",
        "The area and its unit, taken from the survey record."),
    "PROPERTY_BOUNDARIES_MISSING": (
        "One or more boundaries (north, east, south, west) are not described.",
        "The full four-side boundary description from the survey map."),
    "EXECUTION_DATE_MISSING": (
        "The date the deed was signed is missing or not readable as a date.",
        "A copy showing the date of signing."),
    "PRESENTATION_DATE_INVALID": ("The date of presentation for registration is not a valid date.", "The correct presentation date."),
    "PRESENTATION_BEFORE_EXECUTION": (
        "The deed shows a presentation date earlier than the signing date.", "Both dates checked against the original."),
    "PRESENTATION_WINDOW_EXCEEDED": (
        "The deed appears to have been presented later than the time allowed after signing (the allowed period is a draft rule: confirm with a lawyer).",
        "Advice on the late-presentation procedure."),
    "SELLER_NAME_MISSING": ("The seller's name is missing.", "A copy where the seller's full name is readable."),
    "BUYER_NAME_MISSING": ("The buyer's name is missing.", "A copy where the buyer's full name is readable."),
    "CONSIDERATION_MISSING": ("The sale amount is missing or zero.", "The stated sale amount."),
    "ULPIN_PARENT_MISMATCH": (
        "The property ID (ULPIN) on this deed differs from the one on the earlier deed.",
        "An explanation or corrected ULPIN reconciling the two deeds."),
    "REGISTRY_CHECK_UNAVAILABLE": (
        "We could not look this property up in the registry index (no usable ULPIN or no match), so no ownership-history comparison was done.",
        "An encumbrance certificate and the land revenue / mutation records."),
    "BROKEN_OWNERSHIP_LINK": (
        "The seller's name differs from the latest owner recorded for this property, and no document in your upload explains the change (such as a will, gift, partition or succession document).",
        "The document showing how ownership passed to the seller."),
    "PARALLEL_CONVEYANCE": (
        "The registry index lists another transfer of this property that is not in your documents.",
        "The record of that other transfer, and advice from a lawyer on it."),
    "AREA_EXCEEDS_PARENT": (
        "The area on this deed is larger than the area on the earlier deed it came from.",
        "The survey or demarcation report reconciling the two areas."),
    "FIELD_UNREADABLE": (
        "Part of the document could not be read reliably, so checks depending on it were not run. This says nothing about the deed itself.",
        "A clearer copy of the page."),
}

NOT_CHECKED = [
    "Encumbrance certificate (mortgages, charges)",
    "Mutation / revenue records",
    "Court cases or litigation",
    "Succession or inheritance records not in your upload",
    "Other deeds not in your upload",
    "Prohibited-property or acquisition lists",
    "Physical possession of the property",
]


def _bullets(flags: List[Dict[str, Any]]) -> str:
    lines = []
    for f in flags:
        meaning, ask = LIBRARY.get(f.get("code", ""), (f.get("detail", ""), f.get("mitigation", "")))
        where = ""
        ev = f.get("evidence") or []
        if ev and ev[0].get("page"):
            q = (ev[0].get("quote") or "").strip()
            where = f" (see page {ev[0]['page']}" + (f': "{q[:90]}"' if q else "") + ")"
        field = f.get("field_path", "")
        lines.append(f"- **{f.get('title', f.get('code'))}**{where}\n  {meaning}\n  *Ask for:* {ask}"
                     + (f"  \n  *Field:* `{field}`" if field else ""))
    return "\n".join(lines) if lines else "- None found among the documents you uploaded."


def build_brief(result: Dict[str, List[Dict[str, Any]]], request_items: List[Dict[str, Any]] | None = None) -> str:
    a, b, r = result.get("class_a_flags", []), result.get("class_b_flags", []), result.get("needs_review", [])
    reqs = "\n".join(f"- {i['text']}" for i in (request_items or [])) or "- Nothing extra beyond the items above."
    return f"""# Advocate hand-off brief

This brief lists what the uploaded documents show, what they contradict, and what nobody has checked.
It is a document analysis and a question list. It is not a legal opinion and does not say anything
about who owns the property.

## 1. Missing or inconsistent registration details
{_bullets(a)}

## 2. Points to discuss with your advocate
{_bullets(b)}

## 3. Parts we could not read
{_bullets(r)}

## 4. Documents to request from the seller
{reqs}

## 5. What we did not check
{chr(10).join("- " + n for n in NOT_CHECKED)}

*A result of "nothing found" means only that nothing was found among the documents you uploaded.*
"""
