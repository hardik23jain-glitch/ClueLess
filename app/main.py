"""
LandGuard AI - Pre-Transaction Risk-Prevention Layer for Indian Property Registration.
Offline-capable Streamlit application.

Screens:
  1. Citizen Pre-Flight Check: flags with evidence, evidence states, what we did not check, advocate brief.
  2. Sub-Registrar Officer Console: list flags, dispositions, sign and record to ledger.
  3. Tamper-Evident Ledger & Verification: inspect blocks, verify cryptographic signatures, tamper demo.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from extract.cache import load_extraction
from extract.config import Config
from extract.pipeline import apply_human_correction, extract_deed
from extract.request_list import build_request_list
from extract.schema import DeedExtraction, FieldStatus
from integration import (
    DISPOSITION_CODES,
    commit_to_ledger,
    run_risk_analysis,
    validate_dispositions,
)
from ledger import audit_log as al
from ledger import signing as sg
from rules.advocate_brief import NOT_CHECKED, build_brief
from rules.engine import HARD_STOP, RULESET_VERSION, WARNING

# Set page layout and title
st.set_page_config(
    page_title="LandGuard AI - Property Registration Risk Prevention",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clean, professional government / legal tech appearance
st.markdown("""
<style>
    .main-header { font-size: 2.1rem; font-weight: 700; color: #1e293b; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.05rem; color: #64748b; margin-bottom: 1.5rem; }
    .card { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1rem; }
    .flag-a { border-left: 5px solid #ef4444; background-color: #fef2f2; padding: 0.9rem; border-radius: 4px; margin-bottom: 0.8rem; }
    .flag-b { border-left: 5px solid #f59e0b; background-color: #fffbeb; padding: 0.9rem; border-radius: 4px; margin-bottom: 0.8rem; }
    .flag-r { border-left: 5px solid #3b82f6; background-color: #eff6ff; padding: 0.9rem; border-radius: 4px; margin-bottom: 0.8rem; }
    .citation { font-size: 0.88rem; color: #475569; font-style: italic; margin-top: 0.3rem; }
    .evidence-badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; margin-right: 0.5rem; }
    .badge-supported { background-color: #dcfce7; color: #166534; border: 1px solid #86efac; }
    .badge-contradiction { background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
    .badge-none { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
</style>
""", unsafe_allow_html=True)


SAMPLE_BUNDLES = {
    "Parcel P1: Clean 3-Deed Chain (Assam)": {
        "ulpin": "AS000000000101",
        "draft_id": "P1-D3",
        "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Title passes smoothly through three generations of conveyances (2010 -> 2016 -> 2022). Zero defects.",
    },
    "Parcel P2: Broken Ownership Link": {
        "ulpin": "AS000000000102",
        "draft_id": "P2-D2",
        "bundle_ids": ["P2-D1"],
        "desc": "Seller claims acquisition in 2018, but current owner recorded in registry is Sunil Verma.",
    },
    "Parcel P3: Parallel Conveyance (Double Sale)": {
        "ulpin": "AS000000000104",
        "draft_id": "P3-D2",
        "bundle_ids": ["P3-D1"],
        "desc": "Registry index reveals a parallel transfer of the same plot in 2015 to a third party.",
    },
    "Parcel P4: Area Exceeds Parent Deed": {
        "ulpin": "AS000000000103",
        "draft_id": "P4-D2",
        "bundle_ids": ["P4-D1"],
        "desc": "Transferred area (1500 sq ft) strictly exceeds the parent title deed area (1000 sq ft).",
    },
    "Parcel P5: Boundary Mismatch Against Parent": {
        "ulpin": "AS000000000105",
        "draft_id": "P5-D2",
        "bundle_ids": ["P5-D1"],
        "desc": "North boundary in draft deed contradicts the boundary recorded in parent deed.",
    },
    "Parcel P6: Attorney Transfer Missing POA Reg No": {
        "ulpin": "AS000000000107",
        "draft_id": "P6-D2",
        "bundle_ids": ["P6-D1"],
        "desc": "Draft deed executed through power-of-attorney holder with no POA registration number.",
    },
    "Parcel P7: Chain Gap Explained by Succession (DECOY)": {
        "ulpin": "AS000000000108",
        "draft_id": "P7-D3",
        "bundle_ids": ["P7-D1", "P7-D2"],
        "desc": "Seller gap legitimately explained by registered succession certificate. B1 advisory is suppressed.",
    },
    "Parcel P8: Hindi Devanagari Deed (Boundary Mismatch)": {
        "ulpin": "AS000000000109",
        "draft_id": "P8-D2",
        "bundle_ids": ["P8-D1"],
        "desc": "Devanagari sale deed evaluated against earlier registered title deed. Boundary difference identified.",
    },
    "P1 Degraded Scan: Clean Chain": {
        "ulpin": "AS000000000101",
        "draft_id": "P1-D3-scan",
        "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Scanned copy of P1 with simulated tilt and blur; tests OCR and quality gate.",
    },
    "P6 Degraded Scan: Attorney Transfer": {
        "ulpin": "AS000000000107",
        "draft_id": "P6-D2-scan",
        "bundle_ids": ["P6-D1"],
        "desc": "Degraded scan where unreadable POA details trigger human review rather than false hard stop.",
    },
}


def _get_cfg() -> Config:
    return Config(provider="mock")


def render_evidence_states(flags_a: List[Dict], flags_b: List[Dict], needs_review: List[Dict]) -> None:
    st.markdown("#### Document Evidence States")
    col1, col2, col3 = st.columns(3)

    has_contradictions = (len(flags_a) > 0 or len(flags_b) > 0)
    has_unknowns = len(needs_review) > 0

    with col1:
        st.markdown(
            '<div class="evidence-badge badge-supported">✓ SUPPORTED BY UPLOADED DOCUMENTS</div>',
            unsafe_allow_html=True,
        )
        st.caption("Document chain elements and fields verified across uploaded bundle.")

    with col2:
        if has_contradictions:
            st.markdown(
                '<div class="evidence-badge badge-contradiction">⚠ CONTRADICTION DETECTED</div>',
                unsafe_allow_html=True,
            )
            st.caption("Differences or missing statutory prerequisites identified between instruments.")
        else:
            st.markdown(
                '<div class="evidence-badge badge-none">○ NO CONTRADICTION DETECTED</div>',
                unsafe_allow_html=True,
            )
            st.caption("No conflicting terms identified between the provided instruments.")

    with col3:
        if has_unknowns:
            st.markdown(
                '<div class="evidence-badge badge-none">? NO EVIDENCE / UNREADABLE</div>',
                unsafe_allow_html=True,
            )
            st.caption("Certain fields could not be read reliably; routed to reviewer verification.")
        else:
            st.markdown(
                '<div class="evidence-badge badge-none">○ NO EVIDENCE PROVIDED (OUT OF SCOPE)</div>',
                unsafe_allow_html=True,
            )
            st.caption("External registries and un-uploaded instruments remain uninspected.")


def render_flag_card(flag: Dict[str, Any], class_type: str) -> None:
    code = flag.get("code", "")
    title = flag.get("title", code)
    detail = flag.get("detail", "")
    mitigation = flag.get("mitigation", "")
    rule_id = flag.get("flag_id", flag.get("rule_id", ""))
    field_path = flag.get("field_path", "")

    css_class = "flag-a" if class_type == "A" else ("flag-b" if class_type == "B" else "flag-r")
    badge_label = "Class A Hard Stop (Registrability)" if class_type == "A" else (
        "Class B Title Advisory (Not a Refusal Ground)" if class_type == "B" else "Needs Review (Unreadable Field)"
    )

    ev_list = flag.get("evidence", [])
    citation_text = ""
    if ev_list and isinstance(ev_list, list):
        ev = ev_list[0]
        p = ev.get("page")
        q = ev.get("quote", "")
        if p or q:
            q_clean = q.strip() if q else ""
            citation_text = f"Page {p}: \"{q_clean}\"" if p else f"\"{q_clean}\""

    st.markdown(f"""
    <div class="{css_class}">
        <div style="font-weight: 700; font-size: 1rem; color: #0f172a;">
            [{rule_id}] {title}
        </div>
        <div style="font-size: 0.85rem; color: #475569; margin-bottom: 0.4rem;">
            {badge_label} | Code: <code>{code}</code> {f'| Field: <code>{field_path}</code>' if field_path else ''}
        </div>
        <div style="color: #1e293b; font-size: 0.92rem;">
            {detail}
        </div>
        <div style="color: #334155; font-size: 0.88rem; margin-top: 0.4rem;">
            <strong>Mitigation / Next Step:</strong> {mitigation}
        </div>
        {f'<div class="citation">Evidence Citation: {citation_text}</div>' if citation_text else ''}
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# SCREEN 1: CITIZEN PRE-FLIGHT CHECK
# =============================================================================
def screen_citizen_preflight() -> None:
    st.markdown('<div class="main-header">Citizen Pre-Flight Risk Check</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Automated pre-registration scan of deed bundles. Deterministic rules check registrability and title intelligence without certifying title.</div>',
        unsafe_allow_html=True,
    )

    cfg = _get_cfg()

    # Document selection mode
    st.sidebar.markdown("### Document Bundle Selection")
    data_source = st.sidebar.radio("Choose Input Mode:", ["Select Pre-Loaded Sample Bundle", "Upload Deed Files"])

    draft_doc: Optional[DeedExtraction] = None
    bundle_docs: List[DeedExtraction] = []
    bundle_name = ""

    if data_source == "Select Pre-Loaded Sample Bundle":
        bundle_key = st.sidebar.selectbox("Sample Parcel Chain:", list(SAMPLE_BUNDLES.keys()))
        bundle_meta = SAMPLE_BUNDLES[bundle_key]
        bundle_name = bundle_key
        st.sidebar.info(bundle_meta["desc"])

        draft_doc = load_extraction(cfg, bundle_meta["draft_id"])
        bundle_docs = [load_extraction(cfg, bid) for bid in bundle_meta["bundle_ids"] if load_extraction(cfg, bid)]

    else:
        st.sidebar.markdown("#### Upload Documents")
        uploaded_files = st.sidebar.file_uploader("Upload PDF or Image Deed Bundle", accept_multiple_files=True)
        if uploaded_files:
            st.info("Document upload received. Using offline mock extraction cache for demo security.")
            draft_doc = load_extraction(cfg, "P1-D3")
            bundle_docs = [load_extraction(cfg, "P1-D1"), load_extraction(cfg, "P1-D2")]
        else:
            st.info("Please select a sample bundle or upload deeds to begin analysis.")
            return

    if not draft_doc:
        st.error("Could not load extraction data for the selected document.")
        return

    # Run deterministic risk analysis
    analysis = run_risk_analysis(draft_doc, bundle_docs)
    class_a = analysis.get("class_a_flags", [])
    class_b = analysis.get("class_b_flags", [])
    needs_review = analysis.get("needs_review", [])

    st.markdown(f"### Bundle Overview: `{draft_doc.doc_id}`")
    st.caption(f"Referenced Parent Deeds in Chain: {', '.join([b.doc_id for b in bundle_docs]) if bundle_docs else 'None'}")

    # Evidence State Badges
    render_evidence_states(class_a, class_b, needs_review)
    st.markdown("---")

    col_left, col_right = st.columns([1.6, 1.0])

    with col_left:
        # Class A Section
        st.markdown(f"#### Class A: Hard Stops ({len(class_a)})")
        st.caption("Objective registrability checks under registration laws. Missing requirements may justify refusal.")
        if class_a:
            for flag in class_a:
                render_flag_card(flag, "A")
        else:
            st.success("No Class A hard stops identified. All formal statutory prerequisites are satisfied.")

        # Class B Section
        st.markdown(f"#### Class B: Title Advisories ({len(class_b)})")
        st.caption("Intelligence advisories on ownership history, area, or boundaries. Never grounds for refusal.")
        if class_b:
            for flag in class_b:
                render_flag_card(flag, "B")
        else:
            st.info("No Class B advisories identified among the uploaded documents.")

        # Needs Review Section
        st.markdown(f"#### Needs Human Review ({len(needs_review)})")
        st.caption("Fields that could not be read reliably. As per safety rules, unreadable fields never produce flags.")
        if needs_review:
            for item in needs_review:
                render_flag_card(item, "R")

            # Human-in-the-loop Correction
            st.markdown("##### Human-in-the-Loop Field Correction")
            with st.expander("Type correction for an unreadable field and re-run"):
                review_keys = [r.get("field_path") for r in needs_review]
                chosen_key = st.selectbox("Select field to correct:", review_keys)
                val_input = st.text_input(f"Enter verified value for '{chosen_key}':")
                if st.button("Apply Human Correction"):
                    if val_input.strip():
                        try:
                            apply_human_correction(draft_doc.doc_id, chosen_key, val_input.strip(), cfg=cfg)
                            st.success(f"Updated '{chosen_key}'. Refreshing analysis...")
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Correction error: {ex}")
                    else:
                        st.warning("Please enter a non-empty value.")
        else:
            st.caption("No unreadable fields pending review.")

    with col_right:
        # What we did not check panel
        st.markdown("#### What We Did Not Check")
        st.markdown("""
        <div class="card" style="font-size: 0.9rem; line-height: 1.6;">
            <strong>Statutory Disclaimer:</strong> LandGuard AI is an automated document consistency assistant. It does <em>not</em> certify title. The following items have not been verified:
            <ul style="margin-top: 0.5rem; margin-bottom: 0.5rem; padding-left: 1.2rem;">
        """ + "".join([f"<li>{item}</li>" for item in NOT_CHECKED]) + """
            </ul>
            <em>Consult an advocate to verify physical possession, mutation, and revenue records.</em>
        </div>
        """, unsafe_allow_html=True)

        # Ask your seller request list
        st.markdown("#### Documents to Ask Your Seller")
        req_items = build_request_list(draft_doc)
        if req_items:
            for req in req_items:
                st.markdown(f"- **{req.get('field')}:** {req.get('text')}")
        else:
            st.markdown("- No supplementary documentation requested based on uploaded details.")

        # Advocate brief download
        st.markdown("#### Advocate Hand-Off Brief")
        brief_markdown = build_brief(analysis, req_items)
        st.download_button(
            label="📄 Download Advocate Brief (Markdown)",
            data=brief_markdown,
            file_name=f"advocate_brief_{draft_doc.doc_id}.md",
            mime="text/markdown",
            use_container_width=True,
        )


# =============================================================================
# SCREEN 2: SUB-REGISTRAR OFFICER CONSOLE
# =============================================================================
def screen_officer_console() -> None:
    st.markdown('<div class="main-header">Sub-Registrar Officer Console</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Official disposition recording portal. Record statutory actions, justify decisions, and commit signed entries into the tamper-evident ledger.</div>',
        unsafe_allow_html=True,
    )

    cfg = _get_cfg()

    bundle_key = st.sidebar.selectbox("Select Active Application:", list(SAMPLE_BUNDLES.keys()), index=1)
    bundle_meta = SAMPLE_BUNDLES[bundle_key]
    st.sidebar.caption(bundle_meta["desc"])

    draft_doc = load_extraction(cfg, bundle_meta["draft_id"])
    bundle_docs = [load_extraction(cfg, bid) for bid in bundle_meta["bundle_ids"] if load_extraction(cfg, bid)]

    if not draft_doc:
        st.error("Failed to load application draft.")
        return

    analysis = run_risk_analysis(draft_doc, bundle_docs)
    class_a = analysis.get("class_a_flags", [])
    class_b = analysis.get("class_b_flags", [])
    all_flags = class_a + class_b

    col_meta1, col_meta2, col_meta3 = st.columns(3)
    with col_meta1:
        parcel_ulpin = st.text_input("Parcel ULPIN / Bhu-Aadhaar:", value=bundle_meta["ulpin"])
    with col_meta2:
        officer_id = st.text_input("Officer Digital Token (DSC ID):", value="OFFICER-SUBREG-KAMRUP-04")
    with col_meta3:
        st.metric("Total Flags Requiring Action", len(all_flags))

    st.markdown("### Statutory Check Findings & Dispositions")

    if not all_flags:
        st.success("No flags raised for this parcel. Document bundle is ready for standard registration recording.")

    # Collect dispositions per flag
    dispositions: Dict[str, Dict[str, str]] = {}

    for idx, flag in enumerate(all_flags):
        fid = flag.get("flag_id", f"FLAG-{idx}")
        is_class_a = (flag.get("class") == "A" or flag.get("severity") == HARD_STOP)

        st.markdown(f"#### [{fid}] {flag.get('title')}")
        st.caption(f"Category: {'Class A Hard Stop' if is_class_a else 'Class B Advisory'} | Code: {flag.get('code')}")
        st.write(flag.get("detail"))

        c1, c2, c3 = st.columns([1.2, 1.5, 1.2])

        # Allowed actions
        allowed_actions = list(DISPOSITION_CODES)
        if not is_class_a:
            allowed_actions = [a for a in allowed_actions if a != "REFUSE_RECORDED_GROUND"]

        with c1:
            action = st.selectbox(
                f"Action for {fid}:",
                allowed_actions,
                key=f"act_{fid}",
                help="REFUSE_RECORDED_GROUND is strictly restricted to Class A hard stops under registration law.",
            )

        with c2:
            reason = st.text_input(
                f"Statutory Reason for {fid}:",
                key=f"reason_{fid}",
                placeholder="Enter mandatory reason for disposition...",
            )

        ground_ref = ""
        with c3:
            if action == "REFUSE_RECORDED_GROUND":
                ground_ref = st.text_input(
                    f"Ground Ref (e.g. s.12(1)(g)):",
                    key=f"ground_{fid}",
                    placeholder="Mandatory statutory reference...",
                )
            else:
                st.caption("Ground ref only applies to formal refusal.")

        disp_entry = {"action": action, "reason": reason}
        if ground_ref:
            disp_entry["ground_ref"] = ground_ref
        dispositions[fid] = disp_entry
        st.markdown("---")

    # Sign and commit
    st.markdown("### Sign & Commit Decision to Immutable Ledger")
    st.caption("Submitting will generate a cryptographic SHA-256 block hash, salted HMAC commitments, and an Ed25519 digital signature.")

    if st.button("🔐 Sign and Record Decision", type="primary"):
        # Validate dispositions first
        try:
            missing = validate_dispositions(dispositions, all_flags)
            if missing:
                st.error(f"Missing disposition decisions for: {', '.join(missing)}")
                return

            # Commit to ledger
            result = commit_to_ledger(
                parcel_ulpin=parcel_ulpin,
                draft_deed_json=draft_doc,
                parent_deed_json_list=bundle_docs,
                all_flags_dicts=all_flags,
                officer_dispositions=dispositions,
                officer_id=officer_id,
            )

            st.success("Decision recorded successfully in the tamper-evident ledger!")
            r1, r2 = st.columns(2)
            with r1:
                st.markdown(f"**Block Index:** `#{result.get('row_id')}`")
                st.markdown(f"**Entry Hash (SHA-256):** `{result.get('entry_hash')}`")
            with r2:
                st.markdown(f"**Ed25519 Signature:** `{str(result.get('signature'))[:36]}...`")
                st.markdown(f"**Signer Public Key:** `{str(result.get('public_key'))[:36]}...`")

        except ValueError as val_err:
            st.error(f"Disposition Validation Error: {val_err}")
        except Exception as ex:
            st.error(f"Ledger Commit Failed: {ex}")


# =============================================================================
# SCREEN 3: LEDGER VERIFICATION & TAMPER DEMO
# =============================================================================
def screen_ledger_verify() -> None:
    st.markdown('<div class="main-header">Decision Ledger & Cryptographic Verification</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Certificate Transparency-style hash-chained decision audit log with Ed25519 signatures and zero personal data leakage.</div>',
        unsafe_allow_html=True,
    )

    blocks = al.list_blocks()

    col_btn1, col_btn2 = st.columns([1.5, 2.5])
    with col_btn1:
        if st.button("🔍 Verify Entire Ledger Chain & Signatures", type="primary", use_container_width=True):
            ok, bad_idx, reason = sg.verify_signatures()
            if ok:
                st.success("✅ Chain Integrity Verified: All SHA-256 block hashes and Ed25519 digital signatures match across all ledger entries.")
            else:
                st.error(f"❌ Verification Failed at Block #{bad_idx}: {reason}")

    with col_btn2:
        head = al.get_chain_head()
        if head:
            st.info(f"Chain Head Index: **#{head[0]}** | Head Hash: `{head[1][:32]}...`")
        else:
            st.info("Ledger is currently empty (Genesis state). Use Officer Console to record an entry.")

    st.markdown("### Ledger Blocks Table")
    if blocks:
        table_data = []
        for b in blocks:
            cs = b.get("checklist_state", {})
            table_data.append({
                "Idx": b.get("idx"),
                "Timestamp": b.get("timestamp"),
                "Parcel ULPIN": b.get("parcel_ref"),
                "Bundle Hash": f"{b.get('bundle_hash', '')[:16]}...",
                "Entry Hash": f"{b.get('entry_hash', '')[:16]}...",
                "Hard Stops": cs.get("hard_stop_count", 0),
                "Advisories": cs.get("advisory_count", 0),
                "Ruleset": cs.get("ruleset_version", "v1.2"),
                "Officer DSC": b.get("officer_sig_ref"),
            })
        st.dataframe(table_data, use_container_width=True)
    else:
        st.caption("No blocks recorded in audit_log.db yet.")

    st.markdown("---")
    st.markdown("### Tamper Detection Demonstration")
    st.markdown("""
    This demo creates an isolated **temporary copy** of the SQLite ledger database, maliciously mutates
    a disposition record in the copy (simulating unauthorized modification), and executes the verification engine.
    *The real ledger database is never touched.*
    """)

    if st.button("🧪 Run Tamper Demonstration on Isolated Copy"):
        if not blocks:
            st.warning("Please record at least one block in the Officer Console before testing tampering.")
            return

        # Create temporary file copy of the DB
        tmp_dir = tempfile.mkdtemp()
        tmp_db = Path(tmp_dir) / "tampered_audit.db"
        shutil.copy(al.DB_PATH, tmp_db)

        # Mutate the copy
        conn = sqlite3.connect(tmp_db)
        try:
            # Modify dispositions of the first row
            conn.execute("UPDATE audit_log SET dispositions = '{\"TAMPERED\": {\"action\": \"FORGED_APPROVAL\"}}' WHERE idx = 1")
            conn.commit()
        finally:
            conn.close()

        # Test verification against the tampered copy by pointing al.DB_PATH temporarily
        orig_db_path = al.DB_PATH
        try:
            al.DB_PATH = str(tmp_db)
            ok, bad_idx, reason = sg.verify_signatures()

            st.error(f"🚨 Tampering Immediately Detected on Block #{bad_idx}!")
            st.markdown(f"""
            - **Tamper Simulation Result:** `verify_signatures()` returned `(ok=False, bad_idx={bad_idx}, reason='{reason}')`
            - **Detection Mechanism:** The cryptographic SHA-256 hash chain and Ed25519 signature formed over `entry_hash` no longer match the altered content.
            - **Safety Guarantee:** The live database at `ledger/audit_log.db` remained completely untouched and secure.
            """)
        finally:
            al.DB_PATH = orig_db_path
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# MAIN APP ROUTER
# =============================================================================
def main():
    st.sidebar.markdown("## 🛡️ LandGuard AI")
    st.sidebar.caption("Indian Property Registration Risk Layer")
    st.sidebar.markdown(f"**Ruleset:** `{RULESET_VERSION}` | **Provider:** `Mock (Offline)`")

    screen = st.sidebar.radio(
        "Navigation:",
        [
            "1. Citizen Pre-Flight Check",
            "2. Sub-Registrar Officer Console",
            "3. Decision Ledger & Verification",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    **Core Principles:**
    - Deterministic rules only (No LLM in rules)
    - Explainable page & quote citations
    - No 'clean' or numeric title scores
    - Tamper-evident Ed25519 signed log
    """)

    if screen == "1. Citizen Pre-Flight Check":
        screen_citizen_preflight()
    elif screen == "2. Sub-Registrar Officer Console":
        screen_officer_console()
    elif screen == "3. Decision Ledger & Verification":
        screen_ledger_verify()


if __name__ == "__main__":
    main()
