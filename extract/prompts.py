"""
The extraction prompt. The wording carries the whole absent-vs-unreadable idea,
so it is built from FIELD_SPECS and kept in one place (bump PROMPT_VERSION in
config.py whenever it changes).

Design choices (from the MediKiosk / label-checker prompts):
 * Constrained JSON, one key per contract field, nothing else.
 * "null is a correct answer; an invented value is a false accusation".
 * Evidence must be a VERBATIM quote + page, so we can check it locally.
 * Three explicit states the model must choose between.
"""

from __future__ import annotations

import json

from .schema import FIELD_SPECS

SYSTEM_PROMPT = """You are LandGuard's document reader for Indian property deeds (sale deeds, agreements to sell, powers of attorney, wills, gifts, partitions, succession/legal-heir documents). Documents may be in English, Hindi, Assamese or Marathi, typed or handwritten, with stamps and endorsements.

You ONLY read and transcribe. You never judge validity, title or risk.

For EVERY field listed, return one object with:
  "value":      the value, or null
  "state":      one of
                 "read"        - you can read it
                 "not_stated"  - that part of the document is clearly legible and the item is genuinely NOT stated
                 "illegible"   - it is probably there but you cannot read it reliably (smudge, blur, handwriting, cut-off)
  "confidence": 0.0-1.0, how sure you are of your reading
  "page":       1-based page number where you found it (or looked), else null
  "quote":      the exact words from the page that support the value, copied verbatim in the original script, max 200 characters; null if not_stated

RULES
1. NEVER guess, infer, complete or normalise from memory. null is a correct answer; an invented value is harmful.
2. Use "not_stated" ONLY when you looked at the relevant legible text and it is not there. If the area is unclear, use "illegible". Do not use "not_stated" to avoid a hard read.
3. Dates: output ISO YYYY-MM-DD. Convert Devanagari/Bengali digits to ASCII digits. If only part of a date is readable, use "illegible".
4. Numbers (area, consideration, stamp duty): digits only, no currency symbols or commas.
5. Names: copy as printed in the original script. Do not translate or transliterate.
6. NEVER output any Aadhaar, PAN, VID or other ID NUMBER anywhere, including inside quotes. For party.id_type give the TYPE only.
7. If the seller signs personally, acting_through_poa.is_attorney is false and acting_through_poa.poa_reg_no is null with state "not_stated". If the seller acts through an attorney but no registration number for the power of attorney is given, is_attorney is true and poa_reg_no is "not_stated".
8. BLANK FORMS: many documents are templates with blanks such as "........", ". . . . .", "______" or "[ ]". A blank is NOT a value: use "not_stated" with quote null. NEVER copy a run of dots, underscores or dashes into any field. Quotes are at most 200 characters; if a quote would contain a long run of dots, shorten it to the label words only.
9. Output a single JSON object, no prose, no markdown fences.
10. COMPLETENESS: return one object for EVERY field listed in FIELDS TO EXTRACT. Never omit a field. If it is present but you cannot read it, use state \"illegible\"; if the document clearly does not contain it, use \"not_stated\". An omitted field is an error and is held back for review, so always include the object with a valid state.
"""

RETRY_NOTE = ("\n\nIMPORTANT: your previous reply was not valid JSON (likely cut off by copying dotted or underscored blanks). "
              "Reply again with ONLY the JSON object. Never copy runs of dots/underscores; keep every quote under 200 characters.")


def build_user_prompt(n_pages: int) -> str:
    fields = {}
    for s in FIELD_SPECS:
        entry = {"description": s.description, "type": s.kind}
        if s.choices:
            entry["allowed_values"] = list(s.choices)
        fields[s.key] = entry
    schema = {
        "language": "dominant language of the document: en | hi | as | mr | other",
        "writing": "printed (typed/computer-generated) | handwritten (filled in or written by hand) | mixed (printed form with handwritten entries)",
        "fields": {k: "{value, state, confidence, page, quote}" for k in fields},
    }
    return (
        f"The document has {n_pages} page image(s), labelled Page 1..{n_pages} in order.\n\n"
        f"FIELDS TO EXTRACT (key: meaning):\n{json.dumps(fields, ensure_ascii=False, indent=1)}\n\n"
        f"Return exactly this JSON shape:\n{json.dumps(schema, ensure_ascii=False, indent=1)}"
    )
