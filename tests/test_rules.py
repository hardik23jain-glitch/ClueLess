"""
Unit tests for ALL deterministic rules (Class A: A1-A7, Class B: B0-B8).
Every rule has at least one positive test and one negative test.
Includes:
- Decoy test: succession / will / gift / partition in bundle explains ownership gap and suppresses B1.
- Unreadable test: unreadable fields from extraction never produce flags (using extract.to_rules).
"""

from datetime import date
import pytest

from extract.schema import DeedExtraction, Evidence, Field, FieldStatus, Provenance, FIELD_KEYS
from extract.to_rules import run_rules_on_extraction
from rules.engine import evaluate_document, evaluate_class_a, evaluate_class_b, Flag, HARD_STOP, WARNING


def _base_doc(**overrides):
    base = {
        "doc_id": "DRAFT-TEST",
        "doc_type": "sale_deed",
        "registered": True,
        "registration_no": "1001/2022",
        "execution_date": "2022-01-10",
        "presentation_date": "2022-02-15",
        "seller": {"name": "Ramesh Kumar"},
        "buyer": {"name": "Sita Sharma"},
        "acting_through_poa": {"used": False, "poa_reg_no": None},
        "property": {
            "ulpin": "AS000000000105",
            "area_value": 1000.0,
            "area_unit": "sqft",
            "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"},
        },
        "parent_ref": {
            "doc_ref": "PARENT-TEST",
            "ulpin": "AS000000000105",
            "area_value": 1000.0,
            "area_unit": "sqft",
            "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"},
            "execution_date": "2015-05-10",
            "claimed_acquisition_year": 2015,
        },
        "consideration": 500000.0,
    }
    for k, v in overrides.items():
        if "." in k:
            parts = k.split(".")
            d = base
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            d[parts[-1]] = v
        else:
            base[k] = v
    return base


# =============================================================================
# Class A Rules: A1 - A7
# =============================================================================

def test_a1_poa_registration_positive():
    doc = _base_doc(acting_through_poa={"used": True, "poa_reg_no": None})
    flags = evaluate_document(doc)
    assert any(f.rule_id == "A1" and f.code == "POA_REGISTRATION_MISSING" for f in flags)


def test_a1_poa_registration_negative():
    doc1 = _base_doc(acting_through_poa={"used": True, "poa_reg_no": "POA-2020-99"})
    doc2 = _base_doc(acting_through_poa={"used": False, "poa_reg_no": None})
    assert not any(f.rule_id == "A1" for f in evaluate_document(doc1))
    assert not any(f.rule_id == "A1" for f in evaluate_document(doc2))


def test_a2_area_missing_positive():
    doc_none = _base_doc(**{"property.area_value": None})
    doc_zero = _base_doc(**{"property.area_value": 0})
    doc_no_unit = _base_doc(**{"property.area_unit": ""})
    for d in (doc_none, doc_zero, doc_no_unit):
        flags = evaluate_document(d)
        assert any(f.rule_id == "A2" and f.code == "PROPERTY_AREA_MISSING" for f in flags)


def test_a2_area_missing_negative():
    doc = _base_doc(**{"property.area_value": 1500.0, "property.area_unit": "sqft"})
    assert not any(f.rule_id == "A2" for f in evaluate_document(doc))


def test_a3_boundaries_missing_positive():
    doc_missing_south = _base_doc(**{"property.boundaries": {"N": "Road", "E": "Plot 10", "S": "", "W": "Plot 8"}})
    doc_not_dict = _base_doc(**{"property.boundaries": "Road to north"})
    for d in (doc_missing_south, doc_not_dict):
        flags = evaluate_document(d)
        assert any(f.rule_id == "A3" and f.code == "PROPERTY_BOUNDARIES_MISSING" for f in flags)


def test_a3_boundaries_missing_negative():
    doc = _base_doc(**{"property.boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}})
    assert not any(f.rule_id == "A3" for f in evaluate_document(doc))


def test_a4_presentation_window_positive():
    # Execution 2022-01-10, presentation 2022-06-15 (> 4 months)
    doc_late = _base_doc(execution_date="2022-01-10", presentation_date="2022-06-15")
    flags = evaluate_document(doc_late)
    assert any(f.rule_id == "A4" and f.code == "PRESENTATION_WINDOW_EXCEEDED" for f in flags)

    # Presentation before execution
    doc_early = _base_doc(execution_date="2022-05-10", presentation_date="2022-01-10")
    flags_early = evaluate_document(doc_early)
    assert any(f.rule_id == "A4" and f.code == "PRESENTATION_BEFORE_EXECUTION" for f in flags_early)


def test_a4_presentation_window_negative():
    doc = _base_doc(execution_date="2022-01-10", presentation_date="2022-03-10")
    assert not any(f.rule_id == "A4" for f in evaluate_document(doc))


def test_a5_party_names_positive():
    doc_no_seller = _base_doc(**{"seller.name": ""})
    doc_no_buyer = _base_doc(**{"buyer.name": None})
    assert any(f.rule_id == "A5" and f.code == "SELLER_NAME_MISSING" for f in evaluate_document(doc_no_seller))
    assert any(f.rule_id == "A5" and f.code == "BUYER_NAME_MISSING" for f in evaluate_document(doc_no_buyer))


def test_a5_party_names_negative():
    doc = _base_doc(**{"seller.name": "Amit Shah", "buyer.name": "Rajiv Roy"})
    assert not any(f.rule_id == "A5" for f in evaluate_document(doc))


def test_a6_consideration_missing_positive():
    doc_sale_zero = _base_doc(doc_type="sale_deed", consideration=0)
    doc_sale_none = _base_doc(doc_type="sale_deed", consideration=None)
    assert any(f.rule_id == "A6" and f.code == "CONSIDERATION_MISSING" for f in evaluate_document(doc_sale_zero))
    assert any(f.rule_id == "A6" and f.code == "CONSIDERATION_MISSING" for f in evaluate_document(doc_sale_none))


def test_a6_consideration_missing_negative():
    doc_sale = _base_doc(doc_type="sale_deed", consideration=750000.0)
    doc_gift = _base_doc(doc_type="gift", consideration=0)
    doc_will = _base_doc(doc_type="will", consideration=None)
    assert not any(f.rule_id == "A6" for f in evaluate_document(doc_sale))
    assert not any(f.rule_id == "A6" for f in evaluate_document(doc_gift))
    assert not any(f.rule_id == "A6" for f in evaluate_document(doc_will))


def test_a7_ulpin_parent_mismatch_positive():
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1000, "area_unit": "sqft",
                  "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "ulpin": "AS000000000104"}
    )
    flags = evaluate_document(doc)
    assert any(f.rule_id == "A7" and f.code == "ULPIN_PARENT_MISMATCH" for f in flags)


def test_a7_ulpin_parent_mismatch_negative():
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1000, "area_unit": "sqft",
                  "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "ulpin": "AS000000000105"}
    )
    assert not any(f.rule_id == "A7" for f in evaluate_document(doc))


# =============================================================================
# Class B Rules: B0 - B8
# =============================================================================

def test_b0_registry_unavailable_positive():
    # Unknown ULPIN not in MockRegistry
    doc_unknown = _base_doc(**{"property.ulpin": "AS999999999999"})
    doc_no_ulpin = _base_doc(**{"property.ulpin": None})
    assert any(f.rule_id == "B0" and f.code == "REGISTRY_CHECK_UNAVAILABLE" for f in evaluate_document(doc_unknown))
    assert any(f.rule_id == "B0" and f.code == "REGISTRY_CHECK_UNAVAILABLE" for f in evaluate_document(doc_no_ulpin))


def test_b0_registry_unavailable_negative():
    doc = _base_doc(**{"property.ulpin": "AS000000000104"})
    assert not any(f.rule_id == "B0" for f in evaluate_document(doc))


def test_b1_broken_link_positive():
    # AS000000000104 current owner is Meera Patel. Seller is Vikram Singh without linking doc.
    doc = _base_doc(**{"property.ulpin": "AS000000000104", "seller.name": "Vikram Singh"})
    flags = evaluate_document(doc)
    assert any(f.rule_id == "B1" and f.code == "BROKEN_OWNERSHIP_LINK" for f in flags)


def test_b1_broken_link_negative():
    # Seller is recorded owner Meera Patel
    doc = _base_doc(**{"property.ulpin": "AS000000000104", "seller.name": "Meera Patel"})
    assert not any(f.rule_id == "B1" for f in evaluate_document(doc))


def test_b1_decoy_linking_instrument_suppresses_b1():
    # DECOY: Seller differs from recorded owner, but bundle contains a succession/will document
    # transferring from Meera Patel (owner) to Vikram Singh (seller). B1 MUST BE SUPPRESSED!
    doc = _base_doc(
        doc_id="DRAFT-DEED",
        property={"ulpin": "AS000000000104", "area_value": 1000, "area_unit": "sqft",
                  "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        seller={"name": "Vikram Singh"},
        buyer={"name": "Kavita Rao"}
    )
    linking_doc = {
        "doc_id": "WILL-1",
        "doc_type": "will",
        "seller": {"name": "Meera Patel"},
        "buyer": {"name": "Vikram Singh"},
    }
    flags = evaluate_document(doc, bundle=[linking_doc])
    assert not any(f.rule_id == "B1" for f in flags)


def test_b2_double_sale_positive():
    # Parcel AS000000000104 has a recorded parallel conveyance for Meera Patel
    doc = _base_doc(**{"property.ulpin": "AS000000000104", "seller.name": "Meera Patel"})
    flags = evaluate_document(doc)
    assert any(f.rule_id == "B2" and f.code == "PARALLEL_CONVEYANCE" for f in flags)


def test_b2_double_sale_negative():
    # Parcel AS000000000105 has no parallel conveyance
    doc = _base_doc(**{"property.ulpin": "AS000000000105", "seller.name": "Ramesh Kumar"})
    assert not any(f.rule_id == "B2" for f in evaluate_document(doc))


def test_b3_area_exceeds_parent_positive():
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1500.0, "area_unit": "sqft",
                  "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "area_value": 1200.0, "area_unit": "sqft"}
    )
    flags = evaluate_document(doc)
    assert any(f.rule_id == "B3" and f.code == "AREA_EXCEEDS_PARENT" for f in flags)


def test_b3_area_exceeds_parent_negative():
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1000.0, "area_unit": "sqft",
                  "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "area_value": 1200.0, "area_unit": "sqft"}
    )
    assert not any(f.rule_id == "B3" for f in evaluate_document(doc))


def test_b4_boundary_mismatch_positive():
    # Draft North is Canal, parent North is Road
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1000.0, "area_unit": "sqft",
                  "boundaries": {"N": "Canal", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "boundaries": {"N": "Road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}}
    )
    flags = evaluate_document(doc)
    assert any(f.rule_id == "B4" and f.code == "BOUNDARY_PARENT_MISMATCH" for f in flags)


def test_b4_boundary_mismatch_negative():
    # All boundaries match parent after normalisation
    doc = _base_doc(
        property={"ulpin": "AS000000000105", "area_value": 1000.0, "area_unit": "sqft",
                  "boundaries": {"N": "Main Road ", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}},
        parent_ref={"doc_ref": "P1", "boundaries": {"N": "main road", "E": "Plot 10", "S": "Lane", "W": "Plot 8"}}
    )
    assert not any(f.rule_id == "B4" for f in evaluate_document(doc))


def test_b5_date_order_anomaly_positive():
    # Anomaly 1: claimed_acquisition_year (2025) > deed execution year (2022)
    doc1 = _base_doc(
        execution_date="2022-01-10",
        parent_ref={"doc_ref": "P1", "claimed_acquisition_year": 2025}
    )
    flags1 = evaluate_document(doc1)
    assert any(f.rule_id == "B5" and f.code == "DATE_ORDER_ANOMALY" for f in flags1)

    # Anomaly 2: parent deed dated after draft deed
    doc2 = _base_doc(
        execution_date="2020-01-10",
        parent_ref={"doc_ref": "PARENT-LATER", "execution_date": "2023-05-15"}
    )
    parent_doc = {"doc_id": "PARENT-LATER", "execution_date": "2023-05-15"}
    flags2 = evaluate_document(doc2, bundle=[parent_doc])
    assert any(f.rule_id == "B5" and f.code == "DATE_ORDER_ANOMALY" for f in flags2)


def test_b5_date_order_anomaly_negative():
    # Acquisition 2015 < deed 2022, parent deed dated 2015 < draft 2022
    doc = _base_doc(
        execution_date="2022-01-10",
        parent_ref={"doc_ref": "P1", "claimed_acquisition_year": 2015, "execution_date": "2015-05-10"}
    )
    assert not any(f.rule_id == "B5" for f in evaluate_document(doc))


def test_b6_name_mismatch_positive():
    # Seller "Meeraa Patel" vs recorded owner "Meera Patel" (difflib ratio ~ 0.95 >= 0.85)
    doc = _base_doc(**{"property.ulpin": "AS000000000104", "seller.name": "Meeraa Patel"})
    flags = evaluate_document(doc)
    b6_flags = [f for f in flags if f.rule_id == "B6"]
    assert b6_flags and b6_flags[0].code == "NAME_MISMATCH_TRANSLITERATION"
    assert "possible same person, please confirm" in b6_flags[0].detail.lower()
    # Crucial rule requirement: B6 must NEVER auto-resolve B1! B1 must still fire:
    assert any(f.rule_id == "B1" for f in flags)


def test_b6_name_mismatch_negative():
    # Exact match does not trigger B6 advisory
    doc = _base_doc(**{"property.ulpin": "AS000000000104", "seller.name": "Meera Patel"})
    assert not any(f.rule_id == "B6" for f in evaluate_document(doc))


def test_b7_unregistered_instrument_positive():
    # Bundle contains an unregistered agreement to sell
    doc = _base_doc(doc_id="DRAFT-1")
    chain_doc = {
        "doc_id": "ATS-1",
        "doc_type": "agreement_to_sell",
        "registered": False,
    }
    flags = evaluate_document(doc, bundle=[chain_doc])
    b7 = [f for f in flags if f.rule_id == "B7"]
    assert b7 and b7[0].code == "UNREGISTERED_INSTRUMENT_IN_CHAIN"
    assert "not a registered conveyance" in b7[0].detail.lower()


def test_b7_unregistered_instrument_negative():
    # Chain document is registered
    doc = _base_doc(doc_id="DRAFT-1")
    chain_doc = {
        "doc_id": "ATS-1",
        "doc_type": "agreement_to_sell",
        "registered": True,
    }
    assert not any(f.rule_id == "B7" for f in evaluate_document(doc, bundle=[chain_doc]))


def test_b8_encumbrance_positive():
    # Parcel AS000000000106 has an active mortgage in MockRegistry
    doc = _base_doc(**{"property.ulpin": "AS000000000106", "seller.name": "Arjun Deshpande"})
    flags = evaluate_document(doc)
    b8 = [f for f in flags if f.rule_id == "B8"]
    assert b8 and b8[0].code == "PARCEL_ENCUMBRANCE"
    assert "mortgage" in b8[0].detail.lower()


def test_b8_encumbrance_negative():
    # Parcel AS000000000105 has no encumbrances in MockRegistry
    doc = _base_doc(**{"property.ulpin": "AS000000000105", "seller.name": "Ramesh Kumar"})
    assert not any(f.rule_id == "B8" for f in evaluate_document(doc))


# =============================================================================
# Unreadable Field Test (via extract.to_rules)
# =============================================================================

def test_unreadable_field_never_raises_a_flag():
    """
    Design Rule 5: 'unreadable' = UNKNOWN; it must NEVER produce a rule flag.
    It becomes a needs_review item instead.
    """
    def _ext_field(val, status=FieldStatus.EXTRACTED):
        return Field(value=val if status == FieldStatus.EXTRACTED else None,
                     status=status, confidence=0.9 if status == FieldStatus.EXTRACTED else 0.1,
                     evidence=Evidence(page=1, quote="evidence quote"))

    fields = {k: _ext_field(None, FieldStatus.ABSENT) for k in FIELD_KEYS}
    # Set default valid values
    fields["doc_type"] = _ext_field("sale_deed")
    fields["execution_date"] = _ext_field("2022-01-10")
    fields["presentation_date"] = _ext_field("2022-02-15")
    fields["seller.name"] = _ext_field("Ramesh Kumar")
    fields["buyer.name"] = _ext_field("Sita Sharma")
    fields["acting_through_poa.is_attorney"] = _ext_field(True)
    # But poa_reg_no is UNREADABLE!
    fields["acting_through_poa.poa_reg_no"] = _ext_field(None, FieldStatus.UNREADABLE)
    # And property.boundaries.N is UNREADABLE!
    fields["property.boundaries.N"] = _ext_field(None, FieldStatus.UNREADABLE)
    # And property.area_value is UNREADABLE!
    fields["property.area_value"] = _ext_field(None, FieldStatus.UNREADABLE)

    unread_keys = ["acting_through_poa.poa_reg_no", "property.boundaries.N", "property.area_value"]
    extraction = DeedExtraction(
        doc_id="DOC-UNREADABLE",
        provenance=Provenance(file_sha256="a" * 64),
        fields=fields,
        needs_review=unread_keys
    )

    res = run_rules_on_extraction(extraction)
    all_flag_ids = {f["flag_id"] for f in res["class_a_flags"] + res["class_b_flags"]}

    # A1 (poa_reg_no), A2 (area_value), A3 (boundaries) must NOT be raised because they are unreadable!
    assert "A1" not in all_flag_ids
    assert "A2" not in all_flag_ids
    assert "A3" not in all_flag_ids

    # Unreadable fields must be surfaced in needs_review
    review_paths = {r["field_path"] for r in res["needs_review"]}
    assert "acting_through_poa.poa_reg_no" in review_paths
    assert "property.boundaries.N" in review_paths
    assert "property.area_value" in review_paths
