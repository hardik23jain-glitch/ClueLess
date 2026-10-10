"""P1 extraction -> P2 rules engine: unreadable never becomes a flag; evidence is attached."""

from extract.schema import FIELD_KEYS, DeedExtraction, Evidence, Field, FieldStatus, Provenance
from extract.to_rules import run_rules_on_extraction, to_rules_doc


def ext(value, page=1, quote="q"):
    return Field(value=value, status=FieldStatus.EXTRACTED, confidence=0.95, evidence=Evidence(page=page, quote=quote))


ABSENT = Field(value=None, status=FieldStatus.ABSENT, confidence=0.95)
UNREADABLE = Field(value=None, status=FieldStatus.UNREADABLE, confidence=0.2)


def make(**over):
    base = {
        "doc_type": ext("sale_deed"), "execution_date": ext("2021-03-12"), "presentation_date": ext("2021-03-20"),
        "seller.name": ext("Ramesh Kumar"), "buyer.name": ext("Sunita Devi"),
        "acting_through_poa.is_attorney": ext(False), "acting_through_poa.poa_reg_no": ABSENT,
        "property.ulpin": ABSENT, "property.area_value": ext(1200.0), "property.area_unit": ext("sqft"),
        "property.boundaries.N": ext("Road"), "property.boundaries.E": ext("Plot 2"),
        "property.boundaries.S": ext("Drain"), "property.boundaries.W": ext("Lane"),
        "consideration": ext(450000.0),
    }
    base.update({k.replace("__", "."): v for k, v in over.items()})
    fields = {k: base.get(k, ABSENT) for k in FIELD_KEYS}
    unread = [k for k, f in fields.items() if f.status == FieldStatus.UNREADABLE]
    return DeedExtraction(doc_id="T", provenance=Provenance(file_sha256="0" * 64), fields=fields, needs_review=unread)


def test_shape_conversion():
    d = to_rules_doc(make())
    assert d["seller"]["name"] == "Ramesh Kumar" and d["property"]["boundaries"]["N"] == "Road"
    assert d["acting_through_poa"]["used"] is False        # is_attorney -> engine's "used"


def test_absent_poa_with_attorney_fires_a1_with_evidence():
    ex = make(**{"acting_through_poa__is_attorney": ext(True, page=1, quote="through his attorney")})
    res = run_rules_on_extraction(ex)
    a1 = [f for f in res["class_a_flags"] if f["flag_id"] == "A1"]
    assert a1 and a1[0]["evidence"][0]["quote"] == "through his attorney"


def test_unreadable_field_never_becomes_a_flag():
    res = run_rules_on_extraction(make(seller__name=UNREADABLE, execution_date=UNREADABLE))
    ids = {f["flag_id"] for f in res["class_a_flags"] + res["class_b_flags"]}
    assert "A5" not in ids and "A4" not in ids              # no false 'missing' flags
    assert {r["field_path"] for r in res["needs_review"]} == {"seller.name", "execution_date"}


def test_unreadable_attorney_flag_is_surfaced_not_silently_skipped():
    res = run_rules_on_extraction(make(acting_through_poa__is_attorney=UNREADABLE))
    assert any(r["field_path"] == "acting_through_poa.is_attorney" for r in res["needs_review"])


def test_clean_deed_has_no_class_a_flags():
    res = run_rules_on_extraction(make())
    assert res["class_a_flags"] == []
