"""Offline tests for the "Ask your seller" request list (extract/request_list.py).

No network, no rendering, no model: we build DeedExtraction objects directly and
pin the two item kinds and the POA conditional. The wording is static (taken from
FIELD_SPECS, never from an LLM), so these tests lock down the status -> item
mapping and the gating and nothing else.
"""

from extract.request_list import build_request_list
from extract.schema import (FIELD_KEYS, DeedExtraction, Evidence, Field, FieldStatus,
                            Provenance)


def make_extraction(**overrides):
    """A DeedExtraction whose fields are all cleanly read unless overridden.

    `overrides` maps field key -> Field. Any field not overridden is a clean
    EXTRACTED read, so it produces no request-list item.
    """
    fields = {k: Field(status=FieldStatus.EXTRACTED, value="x", evidence=Evidence(page=1))
              for k in FIELD_KEYS}
    fields.update(overrides)
    prov = Provenance(file_sha256="0" * 64)
    return DeedExtraction(doc_id="T-1", provenance=prov, fields=fields)


def kinds_by_field(ex):
    return {i["field"]: i["kind"] for i in build_request_list(ex)}


# ---------------------------------------------------------------- item kinds
def test_absent_field_gives_ask_seller():
    ex = make_extraction(**{"property.ulpin": Field(status=FieldStatus.ABSENT, evidence=Evidence(page=1))})
    items = kinds_by_field(ex)
    assert items["property.ulpin"] == "ask_seller"
    assert set(items) == {"property.ulpin"}            # nothing else flagged


def test_unreadable_field_gives_reupload():
    ex = make_extraction(**{"stamp_duty": Field(status=FieldStatus.UNREADABLE, evidence=Evidence(page=1))})
    items = kinds_by_field(ex)
    assert items["stamp_duty"] == "reupload"
    assert set(items) == {"stamp_duty"}


def test_extracted_fields_produce_no_items():
    assert build_request_list(make_extraction()) == []


# ---------------------------------------------------------------- POA gating
def test_poa_reg_no_only_requested_when_is_attorney_true():
    attorney_true = Field(status=FieldStatus.EXTRACTED, value=True, evidence=Evidence(page=1))
    attorney_false = Field(status=FieldStatus.EXTRACTED, value=False, evidence=Evidence(page=1))
    attorney_unknown = Field(status=FieldStatus.UNREADABLE, evidence=Evidence(page=1))
    poa_absent = Field(status=FieldStatus.ABSENT, evidence=Evidence(page=1))

    # Attorney signs and no POA number stated -> ask for it.
    ex = make_extraction(**{"acting_through_poa.is_attorney": attorney_true,
                            "acting_through_poa.poa_reg_no": poa_absent})
    assert kinds_by_field(ex)["acting_through_poa.poa_reg_no"] == "ask_seller"

    # Seller signs personally -> the POA number is not applicable, no item.
    ex = make_extraction(**{"acting_through_poa.is_attorney": attorney_false,
                            "acting_through_poa.poa_reg_no": poa_absent})
    assert "acting_through_poa.poa_reg_no" not in kinds_by_field(ex)

    # Attorney status itself unreadable -> unknown, so do not request the number.
    ex = make_extraction(**{"acting_through_poa.is_attorney": attorney_unknown,
                            "acting_through_poa.poa_reg_no": poa_absent})
    assert "acting_through_poa.poa_reg_no" not in kinds_by_field(ex)
