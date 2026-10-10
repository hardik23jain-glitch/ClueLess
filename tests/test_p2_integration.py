"""P1 extraction + P2 rules/ledger working together."""

import json
import sqlite3

import pytest
from test_to_rules import ext, make  # helpers from the adapter tests

import ledger.audit_log as al
import ledger.signing as sg
from integration import commit_to_ledger, run_risk_analysis, validate_dispositions
from ledger.mock_index import MockRegistry
from rules.advocate_brief import build_brief
from rules.engine import evaluate_document


@pytest.fixture
def ledger_db(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sg, "KEY_PATH", tmp_path / "key.pem")
    monkeypatch.setenv("LANDGUARD_COMMIT_SALT", "test-salt")


# ----------------------------------------------------------------- registry / engine
def test_registry_accepts_real_and_short_ulpins():
    for u in ("AS000000000104", "AS-104", "as 104"):
        assert MockRegistry.get_parcel(u)["current_owner"] == "Meera Patel"


def test_double_sale_fires_with_14_char_ulpin():
    doc = {"doc_id": "D", "seller": {"name": "Meera Patel"}, "property": {"ulpin": "AS000000000104"}}
    assert "B2" in {f.rule_id for f in evaluate_document(doc)}


def test_extracted_ulpin_reaches_registry():
    ex = make(**{"property__ulpin": ext("AS000000000104"), "seller__name": ext("Meera Patel")})
    res = run_risk_analysis(ex, [])
    assert "B2" in {f["flag_id"] for f in res["class_b_flags"]}      # registry check ran on real extraction output


# ----------------------------------------------------------------- parent linking
def test_parent_deed_linked_by_registration_number_so_b3_fires():
    ex = make(**{"parent_ref__doc_ref": ext("Deed No. 1187 of 2015 dated 04/08/2015")})
    parent = {"doc_id": "PARENT-9", "registration_no": "1187/2015",
              "property": {"area_value": 1000, "area_unit": "sqft"}}
    res = run_risk_analysis(ex, [parent])
    assert "B3" in {f["flag_id"] for f in res["class_b_flags"]}      # 1200 sqft > parent's 1000


# ----------------------------------------------------------------- dispositions
def test_disposition_rules():
    flags = [{"flag_id": "A1", "class": "A"}, {"flag_id": "B2", "class": "B"}]
    assert validate_dispositions({"A1": {"action": "RETURN_FOR_CORRECTION", "reason": "r"}}, flags) == ["B2"]
    with pytest.raises(ValueError):
        validate_dispositions({"B2": {"action": "REFUSE_RECORDED_GROUND", "reason": "r", "ground_ref": "s.58"}}, flags)
    with pytest.raises(ValueError):
        validate_dispositions({"A1": {"action": "REFUSE_RECORDED_GROUND", "reason": "r"}}, flags)   # no ground_ref
    with pytest.raises(ValueError):
        validate_dispositions({"A1": {"action": "ACK_PROCEED", "reason": " "}}, flags)             # no reason
    with pytest.raises(ValueError):
        validate_dispositions({"A1": {"action": "SHRUG", "reason": "r"}}, flags)


# ----------------------------------------------------------------- ledger: signed, committed, tamper-evident
def test_commit_signs_binds_hashes_and_detects_tampering(ledger_db):
    draft = make(**{"acting_through_poa__is_attorney": ext(True)})
    res = run_risk_analysis(draft, [])
    flags = res["class_a_flags"] + res["class_b_flags"]
    out = commit_to_ledger("AS000000000104", draft, [], flags,
                           {"A1": {"action": "RETURN_FOR_CORRECTION", "reason": "POA number needed"}}, "MOCK-DSC-1")
    assert out["signature"] and out["public_key"]
    assert sg.verify_signatures() == (True, None, "ok")

    block = al.list_blocks()[0]
    cs = block["checklist_state"]
    assert cs["ruleset_version"] and len(cs["party_commitments"]) == 2
    assert "Ramesh" not in json.dumps(block)                                  # no names in the immutable log
    assert block["bundle_hash"] == al.compute_bundle_hash_from_hashes([draft.provenance.file_sha256])

    c = sqlite3.connect(al.DB_PATH)
    c.execute("UPDATE audit_log SET dispositions = '{}' WHERE idx = 1")
    c.commit()
    c.close()
    ok, idx, reason = sg.verify_signatures()
    assert not ok and idx == 1


def test_second_entry_chains_and_is_signed(ledger_db):
    draft = make()
    for _ in range(2):
        commit_to_ledger("AS000000000105", draft, [], [], {}, "MOCK-DSC-1")
    assert [b["idx"] for b in al.list_blocks()] == [1, 2] and sg.verify_signatures()[0]


# ----------------------------------------------------------------- advocate brief
def test_brief_uses_static_library_and_safe_language():
    draft = make(**{"acting_through_poa__is_attorney": ext(True, quote="through his attorney"),
                    "property__ulpin": ext("AS000000000104"), "seller__name": ext("Meera Patel")})
    text = build_brief(run_risk_analysis(draft, [])).lower()
    assert "what we did not check" in text and "not a legal opinion" in text
    for banned in ("clean", "safe", "verified title", "serious problem"):
        assert banned not in text
    assert "power of attorney" in text and "page 1" in text                   # static wording + evidence citation
