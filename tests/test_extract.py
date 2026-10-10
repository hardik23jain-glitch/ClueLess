"""Offline tests for the extraction pipeline: no network, no Tesseract, no Node needed."""

import json
from pathlib import Path

import fitz
import pytest

from extract.cache import extraction_hash
from extract.config import Config
from extract.pipeline import apply_human_correction, extract_deed
from extract.redact import is_aadhaar, redact_text, verhoeff_check_digit
from extract.request_list import build_request_list
from extract.schema import FIELD_KEYS, SPEC_BY_KEY, FieldStatus
from extract.validate import ModelOutputError, check_value, parse_model_json

_base = "23456789012"
AADHAAR = _base + verhoeff_check_digit(_base)
AADHAAR_SPACED = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"

DEED_LINES = [
    "SALE DEED",
    "This deed of sale is executed on 12/03/2021 at Guwahati between Ramesh Kumar son of Mohan Kumar the seller",
    "and Sunita Devi wife of Anil Devi the buyer. The seller signs personally.",
    f"Seller identity proof Aadhaar {AADHAAR_SPACED} was verified by the registrar.",
    "Survey No 123 situated in Beltola. Total area 1200 sq ft.",
    "Stamp duty paid Rs 5000 by e-stamp.",
    "Sale consideration Rs 4,50,000 paid in full by the buyer to the seller.",
]


def make_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in DEED_LINES:
        page.insert_text((50, y), line, fontsize=9)
        y += 22
    doc.save(str(path))


def field(value, state="read", conf=0.95, page=1, quote=None):
    return {"value": value, "state": state, "confidence": conf, "page": page, "quote": quote}


def model_reply():
    f = {k: field(None, "illegible", 0.2, None, None) for k in FIELD_KEYS}
    f.update({
        "doc_type": field("sale_deed", quote="SALE DEED"),
        "execution_date": field("2021-03-12", quote="executed on 12/03/2021"),
        "seller.name": field("Ramesh Kumar", quote="Ramesh Kumar son of Mohan Kumar"),
        "seller.relation_name": field("Mohan Kumar", quote="son of Mohan Kumar"),
        "buyer.name": field("Sunita Devi", quote="Sunita Devi wife of Anil Devi"),
        "acting_through_poa.is_attorney": field(False, quote="The seller signs personally"),
        "acting_through_poa.poa_reg_no": field(None, "not_stated", 0.95, None, None),
        "property.survey_no": field("123", quote="Survey No 123"),
        "property.area_value": field("1200", quote="Total area 1200 sq ft"),
        "property.area_unit": field("sq ft", quote="1200 sq ft"),
        # Hallucinated: this text is NOT on the page -> must not be accepted.
        "parent_ref.doc_ref": field("Deed 4411 of 1998", quote="acquired by Deed 4411 of 1998 registered at Dispur"),
        # Model says not stated, but "Stamp duty paid Rs 5000" is printed -> contradiction -> review.
        "stamp_duty": field(None, "not_stated", 0.95, None, None),
        # No label/value on page for ULPIN: legitimately absent.
        "property.ulpin": field(None, "not_stated", 0.9, None, None),
        "consideration": field("4,50,000", quote="Sale consideration Rs 4,50,000"),
        "property.boundaries.N": field("Road", "illegible", 0.3, 1, None),
    })
    return {"language": "en", "fields": f}


@pytest.fixture
def env(tmp_path):
    pdf = tmp_path / "T-1.pdf"
    make_pdf(pdf)
    mock = tmp_path / "mock"
    mock.mkdir()
    (mock / "T-1.json").write_text(json.dumps(model_reply()), encoding="utf-8")
    cfg = Config(provider="mock", mock_dir=mock, extracted_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                 enable_cline_review=False)
    return pdf, cfg


# ---------------------------------------------------------------- redaction
def test_verhoeff_and_aadhaar():
    assert is_aadhaar(AADHAAR)
    assert not is_aadhaar(AADHAAR[:-1] + str((int(AADHAAR[-1]) + 1) % 10))   # bad checksum
    assert not is_aadhaar("123456789012")                                    # starts with 1


def test_redact_text():
    assert "AADHAAR" in redact_text(f"id {AADHAAR_SPACED} ok")
    assert redact_text("ABCDE1234F") == "[PAN REDACTED]"
    assert redact_text("Rs 450000") == "Rs 450000"


def test_redaction_survives_trailing_punctuation():
    from extract.ingest import Word
    from extract.redact import find_sensitive_boxes

    toks = ["Aadhaar", AADHAAR_SPACED.split()[0], AADHAAR_SPACED.split()[1], AADHAAR_SPACED.split()[2] + "."]
    words = [Word(t, i * 50, 10, 40, 10) for i, t in enumerate(toks)]
    boxes, counts = find_sensitive_boxes(words)
    assert counts["aadhaar"] == 1 and len(boxes) == 3


def test_redaction_handles_devanagari_digits_and_danda():
    from extract.ingest import Word
    from extract.redact import find_sensitive_boxes

    dev = str.maketrans("0123456789", "०१२३४५६७८९")
    parts = AADHAAR_SPACED.translate(dev).split()
    toks = ["आधार", parts[0], parts[1], parts[2] + "।"]                  # danda glued to the last group
    boxes, counts = find_sensitive_boxes([Word(t, i * 50, 10, 40, 10) for i, t in enumerate(toks)])
    assert counts["aadhaar"] == 1 and len(boxes) == 3


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("key,value,ok,expected", [
    ("execution_date", "12/03/2021", True, "2021-03-12"),
    ("execution_date", "31/02/2021", False, None),
    ("consideration", "₹4,50,000/-", True, 450000.0),
    ("property.ulpin", "ab12 cd34 ef56", False, None),            # 12 chars: too short
    ("property.ulpin", "AB12CD34EF56GH", True, "AB12CD34EF56GH"),
    ("property.area_unit", "Square Feet", True, "sqft"),
    ("property.area_unit", "furlongs", False, None),
    ("doc_type", "Sale Deed", True, "sale_deed"),
    ("parent_ref.claimed_acquisition_year", "2018", True, 2018),
])
def test_check_value(key, value, ok, expected):
    v, valid, _ = check_value(SPEC_BY_KEY[key], value)
    assert valid is ok
    if ok:
        assert v == expected


def test_parse_model_json_tolerates_fences_and_fails_cleanly():
    assert parse_model_json('```json\n{"a": 1,}\n```') == {"a": 1}
    with pytest.raises(ModelOutputError):
        parse_model_json("sorry, I cannot read this")
    # raw newline inside a string (seen on a real Gemini reply)
    assert parse_model_json('{"quote": "line one\nline two"}')["quote"] == "line one\nline two"


def test_retry_on_transient_error(monkeypatch):
    import extract.providers as pv

    monkeypatch.setattr("time.sleep", lambda s: None)

    class Flaky(pv.VisionProvider):
        calls = 0

        def read(self, images, system, user, doc_id=""):
            Flaky.calls += 1
            if Flaky.calls < 3:
                raise RuntimeError("503 UNAVAILABLE The request timed out")
            return "{}"

    assert pv.read_with_retry(Flaky(), [], "", "") == "{}" and Flaky.calls == 3

    class Broken(pv.VisionProvider):
        def read(self, images, system, user, doc_id=""):
            raise RuntimeError("400 invalid API key")

    with pytest.raises(RuntimeError):
        pv.read_with_retry(Broken(), [], "", "")


# ---------------------------------------------------------------- end to end
def test_end_to_end(env):
    pdf, cfg = env
    ex = extract_deed(pdf, cfg=cfg)
    F = ex.fields

    assert F["seller.name"].status == FieldStatus.EXTRACTED and F["seller.name"].value == "Ramesh Kumar"
    assert F["execution_date"].value == "2021-03-12"
    assert F["property.area_unit"].value == "sqft"
    assert F["consideration"].value == 450000.0
    assert F["seller.name"].evidence.bbox is not None            # located on the page
    # Genuinely absent: the page is readable and has no ULPIN.
    assert F["property.ulpin"].status == FieldStatus.ABSENT
    assert F["acting_through_poa.poa_reg_no"].status == FieldStatus.ABSENT
    # Hallucinated quote -> never accepted, value withheld.
    assert F["parent_ref.doc_ref"].status == FieldStatus.UNREADABLE and F["parent_ref.doc_ref"].value is None
    # 'not stated' contradicted by a value printed after the label -> needs review, not a false absent.
    assert F["stamp_duty"].status == FieldStatus.UNREADABLE
    # Illegible stays unreadable, never absent.
    assert F["property.boundaries.N"].status == FieldStatus.UNREADABLE
    assert "stamp_duty" in ex.needs_review and "seller.name" not in ex.needs_review
    # Aadhaar found and redacted (and the run verified it had word boxes).
    assert ex.provenance.redaction["aadhaar"] == 1 and ex.provenance.redaction["status"] == "verified"
    assert ex.provenance.local_text == "text_layer"
    assert len(ex.provenance.file_sha256) == 64 and (Path(cfg.extracted_dir) / "T-1.json").exists()


def test_handwritten_uses_vision_model_alone(env):
    pdf, cfg = env
    reply = model_reply()
    reply["writing"] = "handwritten"
    (Path(cfg.mock_dir) / "T-1.json").write_text(json.dumps(reply), encoding="utf-8")
    ex = extract_deed(pdf, cfg=cfg)
    F = ex.fields
    assert ex.writing == "handwritten"
    # The local reader is OFF for handwriting: the quote that printed-mode rejected is no longer held against the field
    assert F["parent_ref.doc_ref"].status == FieldStatus.EXTRACTED
    assert F["seller.name"].evidence.bbox is None            # no local boxes in handwritten mode
    assert F["stamp_duty"].status == FieldStatus.ABSENT      # label check is also off
    assert any("handwritten" in w for w in ex.provenance.warnings)


def test_mixed_does_not_penalise_local_miss(env):
    pdf, cfg = env
    reply = model_reply()
    reply["writing"] = "mixed"
    (Path(cfg.mock_dir) / "T-1.json").write_text(json.dumps(reply), encoding="utf-8")
    ex = extract_deed(pdf, cfg=cfg)
    assert ex.fields["parent_ref.doc_ref"].status == FieldStatus.EXTRACTED      # miss = unknown, not disagree
    assert ex.fields["stamp_duty"].status == FieldStatus.UNREADABLE              # printed label check still active
    assert ex.fields["seller.name"].evidence.bbox is not None


def test_blank_amount_is_not_a_value_but_filled_amount_is():
    from extract.localtext import DocText, PageText, value_follows_label
    from extract.textutil import norm

    def doc(text):
        return DocText(pages={1: PageText(1, [], norm(text), "text_layer", True)})

    blank = "That the Stamp Duty under Article 31 of the Indian Stamp Act, 1899 works out to Rs ……… (Rupees ………. Only)"
    assert not value_follows_label("stamp_duty", doc(blank))
    assert value_follows_label("stamp_duty", doc("Stamp duty paid Rs 5000 by e-stamp"))
    assert value_follows_label("property.survey_no", doc("Survey No 123 situated at Beltola"))
    assert not value_follows_label("property.survey_no", doc("Survey No ______ situated at Beltola"))


def test_extraction_hash_is_stable(env):
    pdf, cfg = env
    a = extract_deed(pdf, cfg=cfg)
    b = extract_deed(pdf, cfg=cfg)
    assert a.provenance.extraction_hash == b.provenance.extraction_hash == extraction_hash(a)


def test_failure_never_guesses(tmp_path, env):
    pdf, cfg = env
    cfg.mock_dir = tmp_path / "empty"                              # no canned reply -> provider error
    ex = extract_deed(pdf, cfg=cfg)
    assert all(f.status == FieldStatus.UNREADABLE and f.value is None for f in ex.fields.values())
    assert ex.provenance.warnings


def test_request_list_and_conditional_poa(env):
    pdf, cfg = env
    ex = extract_deed(pdf, cfg=cfg)
    fields = {i["field"] for i in build_request_list(ex)}
    assert "property.ulpin" in fields                              # absent -> ask seller
    assert "stamp_duty" in fields                                  # unreadable -> re-upload
    assert "acting_through_poa.poa_reg_no" not in fields           # seller signs personally: not applicable


def test_human_correction(env):
    pdf, cfg = env
    ex = extract_deed(pdf, cfg=cfg)
    before = ex.provenance.extraction_hash
    out = apply_human_correction("T-1", "stamp_duty", "5000", cfg=cfg)
    assert out.fields["stamp_duty"].status == FieldStatus.EXTRACTED and out.fields["stamp_duty"].value == 5000.0
    assert "stamp_duty" not in out.needs_review
    assert out.provenance.extraction_hash != before
