# integration.py: API wrapper for the Streamlit frontend (P2's wrapper, extended by P1)
#
# What changed vs the first version:
#   * run_risk_analysis accepts P1 extractions (DeedExtraction / extraction JSON) as well as plain
#     engine dicts. For extractions it uses extract.to_rules: unreadable fields never become flags,
#     parent deeds are linked by registration number, and every flag carries page/quote evidence.
#   * commit_to_ledger binds the SHA-256 of the ORIGINAL uploaded files (extraction provenance), the
#     extraction hashes, ruleset + model versions and salted party-name commitments, validates the
#     officer's dispositions, and signs the entry with Ed25519.

from typing import Any, Dict, List

from rules.engine import HARD_STOP, RULESET_VERSION, WARNING, evaluate_document
from ledger.audit_log import (
    compute_bundle_hash,
    compute_bundle_hash_from_hashes,
    create_audit_block,
    get_chain_head,
)
from ledger.signing import party_commitment, sign_block

DISPOSITION_CODES = {"ACK_PROCEED", "PARTIES_INFORMED", "REFER_REVENUE_AUTHORITY",
                     "RETURN_FOR_CORRECTION", "REFUSE_RECORDED_GROUND"}


def _is_extraction(x: Any) -> bool:
    return (hasattr(x, "fields") and hasattr(x, "provenance")) or (
        isinstance(x, dict) and "fields" in x and "provenance" in x)


def _as_extraction(x: Any):
    from extract.schema import DeedExtraction
    return x if hasattr(x, "fields") else DeedExtraction.model_validate(x)


def run_risk_analysis(
    draft_deed_json: Any,
    parent_deed_json_list: List[Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Runs the rules engine and splits flags into Class A, Class B and needs-review."""
    if _is_extraction(draft_deed_json):
        from extract.to_rules import run_rules_on_extraction
        return run_rules_on_extraction(_as_extraction(draft_deed_json), bundle=list(parent_deed_json_list))

    bundle = {
        str(doc.get('doc_id', i)): doc
        for i, doc in enumerate(parent_deed_json_list)
    }
    flags = evaluate_document(draft_deed_json, bundle=bundle)
    return {
        "class_a_flags": [f.to_dict() for f in flags if f.severity == HARD_STOP],
        "class_b_flags": [f.to_dict() for f in flags if f.severity == WARNING],
        "needs_review": [],
    }


def validate_dispositions(dispositions: Dict[str, Any], all_flags: List[Dict[str, Any]]) -> List[str]:
    """
    Officer decisions must use the allowed codes, carry a reason, and REFUSE_RECORDED_GROUND only
    applies to a Class A flag and needs a ground reference (an officer cannot refuse on title grounds).
    Returns the flag ids that still have no disposition. Raises ValueError on an invalid entry.
    """
    by_id = {f.get("flag_id"): f for f in all_flags}
    for flag_id, d in (dispositions or {}).items():
        if not isinstance(d, dict) or d.get("action") not in DISPOSITION_CODES:
            raise ValueError(f"{flag_id}: action must be one of {sorted(DISPOSITION_CODES)}")
        if not str(d.get("reason", "")).strip():
            raise ValueError(f"{flag_id}: a recorded reason is required")
        if d["action"] == "REFUSE_RECORDED_GROUND":
            flag = by_id.get(flag_id)
            if flag is None or flag.get("class") != "A":
                raise ValueError(f"{flag_id}: REFUSE_RECORDED_GROUND is only allowed for a Class A flag")
            if not str(d.get("ground_ref", "")).strip():
                raise ValueError(f"{flag_id}: REFUSE_RECORDED_GROUND requires a ground_ref")
    return [fid for fid in by_id if fid and fid not in (dispositions or {})]


def commit_to_ledger(
    parcel_ulpin: str,
    draft_deed_json: Any,
    parent_deed_json_list: List[Any],
    all_flags_dicts: List[Dict[str, Any]],
    officer_dispositions: Dict[str, Any],
    officer_id: str,
) -> Dict[str, Any]:
    """Hashes the bundle, validates the decisions, writes the chain entry and signs it."""
    undispositioned = validate_dispositions(officer_dispositions, all_flags_dicts)

    all_docs = [draft_deed_json] + list(parent_deed_json_list)
    extractions = [_as_extraction(d) for d in all_docs if _is_extraction(d)]
    if len(extractions) == len(all_docs):
        # Bind the ORIGINAL uploaded files (SHA-256 recorded at ingest), as the design requires.
        bundle_hash = compute_bundle_hash_from_hashes(e.provenance.file_sha256 for e in extractions)
    else:
        import json
        bundle_hash = compute_bundle_hash([json.dumps(d, sort_keys=True, default=str).encode('utf-8')
                                           for d in all_docs])

    draft = extractions[0] if extractions and _is_extraction(draft_deed_json) else None
    commitments = []
    if draft is not None:
        for role in ("seller.name", "buyer.name"):
            c = party_commitment(draft.fields[role].value)
            if c:
                commitments.append(c)

    checklist_state = {
        'flags': all_flags_dicts,
        'hard_stop_count': sum(1 for flag in all_flags_dicts if flag.get('severity') == HARD_STOP),
        'advisory_count': sum(1 for flag in all_flags_dicts if flag.get('severity') == WARNING),
        'undispositioned': undispositioned,
        'ruleset_version': RULESET_VERSION,
        'extraction_hashes': [e.provenance.extraction_hash for e in extractions],
        'model_versions': sorted({e.provenance.model_version for e in extractions}),
        'party_commitments': commitments,
    }

    row_id = create_audit_block(
        parcel_ref=parcel_ulpin,
        bundle_hash=bundle_hash,
        checklist_state=checklist_state,
        dispositions=officer_dispositions,
        officer_sig_ref=officer_id,
    )

    head = get_chain_head()
    entry_hash = head[1] if head else None
    sig = sign_block(row_id, entry_hash) if entry_hash else {}

    return {
        "row_id": row_id,
        "entry_hash": entry_hash,
        "signature": sig.get("signature"),
        "public_key": sig.get("public_key"),
        "undispositioned": undispositioned,
    }
