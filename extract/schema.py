"""
Contract v1.1: the shape of an extracted deed. P2 (rules), P3 (UI) and the
ledger all read this, so it is the single most important file in extract/.

Key ideas
---------
* Every value lives in a Field object: value + status + confidence + evidence.
* status has THREE values and they must never be merged:
    extracted  - read with enough confidence
    absent     - the page is readable and the thing is genuinely not stated
                 (this is what makes Class A rules fire)
    unreadable - it probably exists but we cannot read it reliably
                 (the rules engine treats this as UNKNOWN, never as a flag)
* FIELD_SPECS is the one list that drives the prompt, the validators, the
  request-list and the eval, so adding a field is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field as PField


class FieldStatus(str, Enum):
    EXTRACTED = "extracted"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


class Source(str, Enum):
    VISION_LLM = "vision_llm"
    CLINE_REVIEW = "cline_review"
    HUMAN = "human_corrected"
    CACHE = "cache"


DOC_TYPES = ["sale_deed", "agreement_to_sell", "poa", "will", "gift",
             "partition", "succession", "other"]
ID_TYPES = ["aadhaar", "pan", "voter_id", "passport", "driving_licence", "other"]
AREA_UNITS = ["sqft", "sqm", "sqyd", "acre", "hectare", "bigha", "katha",
              "biswa", "gunta", "cent", "marla", "kanal", "other"]
LANGUAGES = ["en", "hi", "as", "mr", "other"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str              # str | name | date | number | bool | enum | ulpin | year | unit
    description: str       # goes into the prompt
    choices: tuple = ()    # for enums
    ask_seller: str = ""   # plain-language request-list text if the field is absent


# Order matters only for readability. Descriptions are what the model sees.
FIELD_SPECS: list[FieldSpec] = [
    FieldSpec("doc_type", "enum", "Type of instrument.", tuple(DOC_TYPES),
              "A clearer copy showing what kind of document this is."),
    FieldSpec("registered", "bool", "true if the document shows it was registered (registration stamp / number / sub-registrar endorsement).", (),
              "Proof that this document was registered."),
    FieldSpec("registration_no", "str", "Registration / document number from the registration endorsement.", (),
              "The registration number of this document."),
    FieldSpec("execution_date", "date", "Date the deed was executed/signed, ISO format YYYY-MM-DD.", (),
              "The date this deed was signed."),
    FieldSpec("presentation_date", "date", "Date the deed was presented for registration, ISO YYYY-MM-DD.", (),
              "The date this deed was presented for registration."),
    FieldSpec("seller.name", "name", "Full name of the seller/executant, as printed (original script).", (),
              "The seller's full name as written on the deed."),
    FieldSpec("seller.relation_name", "name", "Father's/husband's name of the seller (the 's/o, w/o, d/o' name).", (),
              "The seller's father's or husband's name."),
    FieldSpec("buyer.name", "name", "Full name of the buyer/transferee, as printed.", (),
              "The buyer's full name as written on the deed."),
    FieldSpec("buyer.relation_name", "name", "Father's/husband's name of the buyer.", (),
              "The buyer's father's or husband's name."),
    FieldSpec("party.id_type", "enum", "Type of ID mentioned for the parties (type ONLY). NEVER output an ID number.", tuple(ID_TYPES),
              "The type of ID proof used for the parties (do not send the number)."),
    FieldSpec("acting_through_poa.is_attorney", "bool", "true if the seller signs through a power-of-attorney holder/attorney; false if the seller signs personally.", (),
              "Confirmation of whether the seller signed personally or through an attorney."),
    FieldSpec("acting_through_poa.poa_reg_no", "str", "Registration number of the power of attorney, if the seller acts through one. Null if not stated.", (),
              "The registration number of the power of attorney."),
    FieldSpec("property.ulpin", "ulpin", "ULPIN / Bhu-Aadhaar (14 alphanumeric characters), if printed.", (),
              "The property's ULPIN (Bhu-Aadhaar) number."),
    FieldSpec("property.survey_no", "str", "Survey / khasra / plot number of the property: the number only (do NOT include the khata number or other text).", (),
              "The survey / khasra / plot number."),
    FieldSpec("property.area_value", "number", "Area of the property as a number only.", (),
              "The area of the property."),
    FieldSpec("property.area_unit", "unit", "Unit of that area.", tuple(AREA_UNITS),
              "The unit of the property's area (sq ft, katha, bigha, ...)."),
    FieldSpec("property.boundaries.N", "str", "North boundary (what lies to the north).", (),
              "The north boundary of the property."),
    FieldSpec("property.boundaries.E", "str", "East boundary.", (),
              "The east boundary of the property."),
    FieldSpec("property.boundaries.S", "str", "South boundary.", (),
              "The south boundary of the property."),
    FieldSpec("property.boundaries.W", "str", "West boundary.", (),
              "The west boundary of the property."),
    FieldSpec("parent_ref.doc_ref", "str", "Reference (number/date) to the seller's earlier title deed, if mentioned.", (),
              "The earlier deed through which the seller acquired the property."),
    FieldSpec("parent_ref.claimed_acquisition_year", "year", "Year the seller says they acquired the property (4 digits).", (),
              "The year the seller acquired the property."),
    FieldSpec("consideration", "number", "Sale consideration in rupees, number only.", (),
              "The sale amount (consideration) stated in the deed."),
    FieldSpec("stamp_duty", "number", "Stamp duty paid in rupees, number only.", (),
              "Proof of stamp duty paid."),
]

SPEC_BY_KEY: dict[str, FieldSpec] = {s.key: s for s in FIELD_SPECS}
FIELD_KEYS: list[str] = [s.key for s in FIELD_SPECS]


class Evidence(BaseModel):
    page: Optional[int] = None            # 1-based
    quote: Optional[str] = None           # verbatim text from the page
    bbox: Optional[list[float]] = None    # [x, y, w, h] in rendered-page pixels; best-effort


class Field(BaseModel):
    value: Any = None                       # only set when status == extracted
    candidate: Any = None                   # low-confidence reading, for human / review-agent help; never used by rules
    status: FieldStatus = FieldStatus.UNREADABLE
    confidence: float = 0.0
    evidence: Evidence = PField(default_factory=Evidence)
    source: Source = Source.VISION_LLM
    notes: list[str] = PField(default_factory=list)   # why a field was downgraded, etc.


class Provenance(BaseModel):
    file_sha256: str
    file_name: str = ""
    pages: int = 0
    extraction_method: str = "vision_llm"
    provider: str = ""
    model_version: str = ""
    prompt_version: str = ""
    contract_version: str = "1.1"
    cache_key: str = ""
    extracted_at: str = ""
    extraction_hash: str = ""             # filled last; feeds the ledger
    redaction: dict = PField(default_factory=dict)   # {"status": "...", "aadhaar": n, ...}
    quality: dict = PField(default_factory=dict)
    local_text: str = "none"              # "text_layer" | "tesseract" | "none"
    review: str = "not_run"               # cline review outcome
    warnings: list[str] = PField(default_factory=list)


class DeedExtraction(BaseModel):
    doc_id: str
    provenance: Provenance
    fields: dict[str, Field]
    needs_review: list[str] = PField(default_factory=list)
    language: str = "other"
    writing: str = "printed"              # printed | handwritten | mixed (reported by the vision model)
    overall_confidence: float = 0.0
    retake_required: bool = False

    def get(self, key: str) -> Field:
        return self.fields[key]
