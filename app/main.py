"""
LandGuard AI - Pre-Transaction Risk-Prevention Layer for Indian Property Registration.
Offline-capable Streamlit application.

Screens:
  1. Citizen Pre-Flight Check: flags with evidence, evidence states, what we did not check, advocate brief.
  2. Sub-Registrar Officer Console: list flags, dispositions, sign and record to ledger.
  3. Tamper-Evident Ledger & Verification: inspect blocks, verify cryptographic signatures, tamper demo.

Design rules shown in the UI: never "clean"/"safe"/"verified title", no numeric title score, always a
"What we did not check" panel, every finding cites page + quote.
"""

from __future__ import annotations

import html as _html
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from extract.cache import load_extraction
from extract.config import Config
from extract.pipeline import apply_human_correction
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
from rules.engine import HARD_STOP, RULESET_VERSION

st.set_page_config(
    page_title="LandGuard AI | Property Registration Risk Prevention",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------------------------
# Design system
# ----------------------------------------------------------------------------------------------
CSS = """
<style>
:root{
  --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --card:#ffffff; --bg:#f8fafc;
  --brand:#4f46e5; --brand2:#7c3aed; --navy:#0f172a;
  --a:#dc2626; --a-bg:#fef2f2; --b:#d97706; --b-bg:#fffbeb; --r:#2563eb; --r-bg:#eff6ff;
  --ok:#059669; --ok-bg:#ecfdf5;
}
html, body, [class*="css"], .stApp { font-family: "Segoe UI", "Inter", system-ui, -apple-system, sans-serif; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }

/* hero */
.hero{ background: linear-gradient(135deg,#0f172a 0%,#312e81 55%,#4f46e5 100%); color:#fff; border-radius:18px;
  padding:1.6rem 1.8rem; margin-bottom:1.2rem; position:relative; overflow:hidden;
  box-shadow:0 10px 30px rgba(49,46,129,.25); }
.hero:after{ content:""; position:absolute; right:-60px; top:-60px; width:240px; height:240px; border-radius:50%;
  background:radial-gradient(circle,rgba(255,255,255,.18),transparent 70%); }
.hero .eyebrow{ font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; opacity:.75; font-weight:600; }
.hero h1{ margin:.2rem 0 .3rem; font-size:1.85rem; font-weight:750; letter-spacing:-.02em; color:#fff; padding:0; }
.hero p{ margin:0; opacity:.86; font-size:.98rem; max-width:860px; line-height:1.5; }

/* tiles */
.tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:.8rem; margin:.4rem 0 1.1rem; }
.tile{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:.95rem 1.05rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04); position:relative; overflow:hidden; }
.tile:before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--accent,#94a3b8); }
.tile .v{ font-size:1.9rem; font-weight:760; line-height:1.1; color:var(--accent,#0f172a); }
.tile .l{ font-size:.78rem; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.06em; margin-top:.25rem; }
.tile .s{ font-size:.78rem; color:var(--muted); margin-top:.15rem; }

/* chips */
.chip{ display:inline-block; padding:.18rem .62rem; border-radius:999px; font-size:.74rem; font-weight:650;
  border:1px solid transparent; margin-right:.35rem; white-space:nowrap; }
.chip.a{ background:var(--a-bg); color:#991b1b; border-color:#fecaca; }
.chip.b{ background:var(--b-bg); color:#92400e; border-color:#fde68a; }
.chip.r{ background:var(--r-bg); color:#1e40af; border-color:#bfdbfe; }
.chip.ok{ background:var(--ok-bg); color:#065f46; border-color:#a7f3d0; }
.chip.n{ background:#f1f5f9; color:#475569; border-color:#cbd5e1; }
.chip.ind{ background:#eef2ff; color:#3730a3; border-color:#c7d2fe; }
.meta{ display:flex; flex-wrap:wrap; gap:.5rem 1.8rem; align-items:center; margin:.2rem 0 .8rem; }
.meta .grp{ display:inline-flex; align-items:center; gap:.45rem; }

/* flag cards */
.fcard{ background:var(--card); border:1px solid var(--line); border-left:5px solid var(--accent); border-radius:12px;
  padding:1rem 1.15rem; margin-bottom:.85rem; box-shadow:0 1px 3px rgba(15,23,42,.05); }
.fcard.a{ --accent:var(--a); } .fcard.b{ --accent:var(--b); } .fcard.r{ --accent:var(--r); }
.fcard .top{ display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; margin-bottom:.35rem; }
.fcard .ttl{ font-weight:700; font-size:1.02rem; color:var(--ink); }
.fcard .dtl{ color:#334155; font-size:.93rem; line-height:1.5; }
.fcard .mit{ margin-top:.5rem; font-size:.88rem; color:#475569; background:#f8fafc; border-radius:8px; padding:.5rem .7rem; }
.fcard .ev{ margin-top:.5rem; border-left:3px solid #cbd5e1; padding:.3rem .7rem; background:#f8fafc; border-radius:0 8px 8px 0;
  font-size:.86rem; color:#475569; }
.fcard .ev b{ color:#0f172a; }
.fcard code, .code{ background:#eef2ff; color:#3730a3; padding:.05rem .35rem; border-radius:5px; font-size:.78rem; }

/* state cards */
.states{ display:grid; grid-template-columns:repeat(3,1fr); gap:.8rem; margin-bottom:1rem; }
@media(max-width:900px){ .states{ grid-template-columns:1fr; } }
.state{ border-radius:14px; padding:.9rem 1rem; border:1px solid var(--line); background:var(--card); }
.state .h{ font-size:.74rem; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }
.state .n{ font-size:1.7rem; font-weight:760; margin:.15rem 0; }
.state .d{ font-size:.82rem; color:var(--muted); line-height:1.4; }
.state.ok{ background:var(--ok-bg); border-color:#a7f3d0; } .state.ok .h,.state.ok .n{ color:#065f46; }
.state.x{ background:var(--a-bg); border-color:#fecaca; } .state.x .h,.state.x .n{ color:#991b1b; }
.state.u{ background:#f1f5f9; border-color:#cbd5e1; } .state.u .h,.state.u .n{ color:#334155; }

/* section titles */
.sec{ display:flex; align-items:baseline; gap:.6rem; margin:1.3rem 0 .15rem; }
.sec h3{ margin:0; font-size:1.12rem; font-weight:720; color:var(--ink); padding:0; }
.sec span{ color:var(--muted); font-size:.85rem; }
.empty{ background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:.8rem 1rem; color:#475569; font-size:.9rem; }

/* side panels */
.panel{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem; margin-bottom:1rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04); }
.panel h4{ margin:0 0 .5rem; font-size:.98rem; font-weight:720; padding:0; }
.panel ul{ margin:.2rem 0 .4rem; padding-left:1.1rem; color:#334155; font-size:.9rem; line-height:1.65; }
.disclaimer{ background:linear-gradient(180deg,#fffbeb,#fff7ed); border:1px solid #fde68a; }

/* field table */
.ftable{ width:100%; border-collapse:separate; border-spacing:0; font-size:.86rem; background:#fff; border:1px solid var(--line);
  border-radius:12px; overflow:hidden; }
.ftable th{ text-align:left; background:#f1f5f9; color:#475569; font-size:.72rem; letter-spacing:.06em; text-transform:uppercase;
  padding:.55rem .75rem; position:sticky; top:0; }
.ftable td{ padding:.5rem .75rem; border-top:1px solid #f1f5f9; vertical-align:top; color:#1e293b; }
.ftable tr:hover td{ background:#fafaff; }
.bar{ width:90px; height:7px; background:#e2e8f0; border-radius:99px; overflow:hidden; display:inline-block; vertical-align:middle; }
.bar i{ display:block; height:100%; background:linear-gradient(90deg,#818cf8,#4f46e5); border-radius:99px; }
.q{ color:#64748b; font-style:italic; }

/* ledger chain */
.chain{ display:flex; align-items:center; gap:.4rem; overflow-x:auto; padding:.4rem .1rem 1rem; }
.blk{ min-width:150px; background:#fff; border:1px solid var(--line); border-top:4px solid var(--brand); border-radius:12px;
  padding:.6rem .75rem; box-shadow:0 1px 3px rgba(15,23,42,.06); font-size:.78rem; }
.blk b{ font-size:.92rem; color:var(--ink); } .blk .hx{ font-family:Consolas,monospace; color:#4338ca; }
.arrow{ color:#94a3b8; font-size:1.2rem; }
.receipt{ background:linear-gradient(135deg,#ecfdf5,#f0fdf4); border:1px solid #a7f3d0; border-radius:14px; padding:1rem 1.2rem; }
.receipt .row{ font-size:.88rem; color:#064e3b; margin:.2rem 0; word-break:break-all; }
.alarm{ background:linear-gradient(135deg,#fef2f2,#fff1f2); border:1px solid #fecaca; border-radius:14px; padding:1rem 1.2rem; }

/* sidebar */
section[data-testid="stSidebar"]{ background:linear-gradient(180deg,#0f172a,#1e1b4b); }
section[data-testid="stSidebar"] *{ color:#e2e8f0; }
section[data-testid="stSidebar"] .stSelectbox label, section[data-testid="stSidebar"] .stRadio label{ color:#e2e8f0 !important; }
/* inputs inside the dark sidebar sit on white: keep their text dark */
section[data-testid="stSidebar"] div[data-baseweb="select"] *{ color:#0f172a !important; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *{ color:#0f172a !important; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button{ color:#0f172a !important; }
.brand{ display:flex; align-items:center; gap:.6rem; margin-bottom:.2rem; }
.brand .logo{ width:38px; height:38px; border-radius:11px; background:linear-gradient(135deg,#6366f1,#a855f7);
  display:flex; align-items:center; justify-content:center; font-size:1.2rem; box-shadow:0 4px 12px rgba(99,102,241,.5); }
.brand .nm{ font-weight:780; font-size:1.15rem; color:#fff; letter-spacing:-.01em; }
.sbnote{ font-size:.78rem; color:#a5b4fc; line-height:1.55; }
.principles{ background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:.7rem .85rem;
  font-size:.8rem; line-height:1.6; }

/* buttons & tabs */
.stButton>button, .stDownloadButton>button{ border-radius:10px; font-weight:650; border:1px solid #c7d2fe; }
.stButton>button[kind="primary"]{ background:linear-gradient(135deg,#4f46e5,#7c3aed); border:0; color:#fff;
  box-shadow:0 4px 14px rgba(79,70,229,.35); }
button[data-baseweb="tab"]{ font-weight:650; font-size:.95rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------------------------
# HTML helpers (single-line output so Markdown never mistakes indentation for a code block)
# ----------------------------------------------------------------------------------------------
def esc(x: Any) -> str:
    return _html.escape("" if x is None else str(x))


def H(markup: str) -> None:
    st.markdown(" ".join(line.strip() for line in markup.strip().splitlines()), unsafe_allow_html=True)


def hero(eyebrow: str, title: str, subtitle: str) -> None:
    H(f'<div class="hero"><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>')


def tiles(items: List[tuple]) -> None:
    """items: (label, value, accent_color, sublabel)"""
    cells = "".join(
        f'<div class="tile" style="--accent:{c}"><div class="v">{esc(v)}</div><div class="l">{esc(l)}</div>'
        f'{f"<div class=s>{esc(s)}</div>" if s else ""}</div>'
        for l, v, c, s in items
    )
    H(f'<div class="tiles">{cells}</div>')


def chip(text: str, kind: str = "n") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def section(title: str, hint: str = "") -> None:
    H(f'<div class="sec"><h3>{esc(title)}</h3><span>{esc(hint)}</span></div>')


def empty(msg: str) -> None:
    H(f'<div class="empty">{esc(msg)}</div>')


SAMPLE_BUNDLES = {
    "Parcel P1: 3-Deed Chain, No Defects Planted (Assam)": {
        "ulpin": "AS000000000101",
        "draft_id": "P1-D3",
        "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Ownership passes through three conveyances (2010 -> 2016 -> 2022). No defects planted.",
    },
    "Parcel P2: Broken Ownership Link": {
        "ulpin": "AS000000000102",
        "draft_id": "P2-D2",
        "bundle_ids": ["P2-D1"],
        "desc": "Seller claims acquisition in 2018, but the registry's recorded owner is Sunil Verma.",
    },
    "Parcel P3: Parallel Conveyance (Double Sale)": {
        "ulpin": "AS000000000104",
        "draft_id": "P3-D2",
        "bundle_ids": ["P3-D1"],
        "desc": "Registry index shows another transfer of the same plot in 2015 to a third party.",
    },
    "Parcel P4: Area Exceeds Parent Deed": {
        "ulpin": "AS000000000103",
        "draft_id": "P4-D2",
        "bundle_ids": ["P4-D1"],
        "desc": "Transferred area (1500 sq ft) exceeds the parent deed area (1000 sq ft).",
    },
    "Parcel P5: Boundary Mismatch Against Parent": {
        "ulpin": "AS000000000105",
        "draft_id": "P5-D2",
        "bundle_ids": ["P5-D1"],
        "desc": "North boundary in the draft deed differs from the one recorded in the parent deed.",
    },
    "Parcel P6: Attorney Transfer Missing POA Reg No": {
        "ulpin": "AS000000000107",
        "draft_id": "P6-D2",
        "bundle_ids": ["P6-D1"],
        "desc": "Deed executed through a power-of-attorney holder with no POA registration number.",
    },
    "Parcel P7: Chain Gap Explained by Succession (Decoy)": {
        "ulpin": "AS000000000108",
        "draft_id": "P7-D3",
        "bundle_ids": ["P7-D1", "P7-D2"],
        "desc": "Seller gap is explained by a registered succession document, so the broken-link advisory is suppressed.",
    },
    "Parcel P8: Hindi Devanagari Deed (Boundary Mismatch)": {
        "ulpin": "AS000000000109",
        "draft_id": "P8-D2",
        "bundle_ids": ["P8-D1"],
        "desc": "Devanagari sale deed compared with an earlier registered deed. Boundary difference found.",
    },
    "P1 Degraded Scan": {
        "ulpin": "AS000000000101",
        "draft_id": "P1-D3-scan",
        "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Scanned copy of P1 with simulated tilt and blur; tests OCR and the quality gate.",
    },
    "P6 Degraded Scan: Attorney Transfer": {
        "ulpin": "AS000000000107",
        "draft_id": "P6-D2-scan",
        "bundle_ids": ["P6-D1"],
        "desc": "On a poor scan the POA detail is unreadable, so it goes to human review instead of a false hard stop.",
    },
}


def _get_cfg() -> Config:
    return Config(provider="mock")


def _sidebar_brand() -> None:
    H('<div class="brand"><div class="logo">🛡️</div><div class="nm">LandGuard AI</div></div>')
    H('<div class="sbnote">Pre-registration risk layer for Indian property deeds.<br>Never certifies title.</div>')


# ----------------------------------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------------------------------
def render_flag_card(flag: Dict[str, Any], class_type: str) -> None:
    code = flag.get("code", "")
    title = flag.get("title", code)
    rule_id = flag.get("flag_id", flag.get("rule_id", ""))
    field_path = flag.get("field_path", "")
    kind = class_type.lower()
    label = {"A": "🛑 Class A · Registrability", "B": "⚠️ Class B · Advisory (not a refusal ground)",
             "R": "🔎 Needs review · could not be read"}[class_type]

    citation = ""
    ev_list = flag.get("evidence", [])
    if ev_list and isinstance(ev_list, list):
        ev = ev_list[0]
        page, quote = ev.get("page"), (ev.get("quote") or "").strip()
        if page or quote:
            where = f"<b>Page {esc(page)}</b>" if page else ""
            q = f' &ldquo;{esc(quote[:220])}&rdquo;' if quote else ""
            citation = f'<div class="ev">📍 {where}{q}</div>'

    mitigation = flag.get("mitigation", "")
    H(
        f'<div class="fcard {kind}" style="margin-bottom:.3rem"><div class="top">{chip(rule_id or "R", kind)}'
        f'<span class="ttl">{esc(title)}</span></div>'
        f'<div style="margin-bottom:.2rem">{chip(label, kind)}<code>{esc(code)}</code>'
        f'{f" <code>{esc(field_path)}</code>" if field_path else ""}</div>{citation}</div>'
    )
    # Details and next step stay one click away so the page is not a wall of text.
    with st.expander("Details and next step"):
        st.write(flag.get("detail", ""))
        if mitigation:
            st.markdown(f"**Next step:** {mitigation}")


def render_evidence_states(ex: DeedExtraction, flags_a: List[Dict], flags_b: List[Dict], needs_review: List[Dict]) -> None:
    n_read = sum(1 for f in ex.fields.values() if f.status == FieldStatus.EXTRACTED)
    n_absent = sum(1 for f in ex.fields.values() if f.status == FieldStatus.ABSENT)
    n_contra = len(flags_a) + len(flags_b)
    H(
        '<div class="states">'
        f'<div class="state ok"><div class="h">✓ Supported by your documents</div><div class="n">{n_read}</div>'
        '<div class="d">Fields read with page evidence from the uploaded deeds.</div></div>'
        f'<div class="state x"><div class="h">⚠ Contradiction / missing item</div><div class="n">{n_contra}</div>'
        '<div class="d">Differences or missing prerequisites found among the uploaded instruments.</div></div>'
        f'<div class="state u"><div class="h">○ No evidence provided</div><div class="n">{n_absent + len(needs_review)}</div>'
        f'<div class="d">{n_absent} not stated in the deed, {len(needs_review)} could not be read. Registries and other documents were not inspected.</div></div>'
        '</div>'
    )


def render_fields_table(ex: DeedExtraction) -> None:
    pill = {FieldStatus.EXTRACTED: ("Read", "ok"), FieldStatus.ABSENT: ("Not stated", "n"),
            FieldStatus.UNREADABLE: ("Needs review", "r")}
    rows = []
    for key, f in ex.fields.items():
        txt, kind = pill[f.status]
        val = esc(f.value) if f.status == FieldStatus.EXTRACTED else (
            f'<span class="q">candidate: {esc(f.candidate)}</span>' if f.candidate not in (None, "") else "—")
        conf = max(0, min(100, int(round(f.confidence * 100))))
        ev = f.evidence
        evid = ""
        if ev.page or ev.quote:
            evid = f'p.{esc(ev.page)} <span class="q">&ldquo;{esc((ev.quote or "")[:70])}&rdquo;</span>'
        rows.append(
            f'<tr><td><b>{esc(key.replace(".", " › "))}</b></td><td>{chip(txt, kind)}</td><td>{val}</td>'
            f'<td><span class="bar"><i style="width:{conf}%"></i></span> {conf}%</td><td>{evid}</td></tr>')
    H('<div style="max-height:560px;overflow:auto;border-radius:12px"><table class="ftable"><thead><tr>'
      '<th>Field</th><th>Status</th><th>Value</th><th>Reading confidence</th><th>Evidence</th></tr></thead><tbody>'
      + "".join(rows) + '</tbody></table></div>')
    st.caption("Confidence is how reliably a field was read. It is not a statement about the deed or the title.")


# =============================================================================
# SCREEN 1: CITIZEN PRE-FLIGHT CHECK
# =============================================================================
def screen_citizen_preflight() -> None:
    hero("Citizen pre-flight", "Check your documents before you pay",
         "We read your deeds, run fixed registration checks, and show exactly where each finding comes from. "
         "This is a document analysis and a question list, not a legal opinion, and never a title certificate.")

    cfg = _get_cfg()

    st.sidebar.markdown("### Document bundle")
    data_source = st.sidebar.radio("Choose Input Mode:", ["Select Pre-Loaded Sample Bundle", "Upload Deed Files"])

    draft_doc: Optional[DeedExtraction] = None
    bundle_docs: List[DeedExtraction] = []

    if data_source == "Select Pre-Loaded Sample Bundle":
        bundle_key = st.sidebar.selectbox("Sample Parcel Chain:", list(SAMPLE_BUNDLES.keys()))
        bundle_meta = SAMPLE_BUNDLES[bundle_key]
        st.sidebar.info(bundle_meta["desc"])
        draft_doc = load_extraction(cfg, bundle_meta["draft_id"])
        bundle_docs = [load_extraction(cfg, bid) for bid in bundle_meta["bundle_ids"] if load_extraction(cfg, bid)]
    else:
        st.sidebar.markdown("#### Upload Documents")
        uploaded_files = st.sidebar.file_uploader("Upload PDF or Image Deed Bundle", accept_multiple_files=True)
        if uploaded_files:
            st.info("Upload received. This demo uses the cached sample extraction instead of calling the model.")
            draft_doc = load_extraction(cfg, "P1-D3")
            bundle_docs = [load_extraction(cfg, "P1-D1"), load_extraction(cfg, "P1-D2")]
        else:
            empty("Select a sample bundle or upload deeds in the sidebar to begin.")
            return

    if not draft_doc:
        st.error("Could not load extraction data for the selected document.")
        return

    with st.spinner("Analyzing… 🛡️"):
        analysis = run_risk_analysis(draft_doc, bundle_docs)
    class_a = analysis.get("class_a_flags", [])
    class_b = analysis.get("class_b_flags", [])
    needs_review = analysis.get("needs_review", [])

    parents = "".join(chip(b.doc_id, "n") for b in bundle_docs) or chip("none", "n")
    H(f'<div class="meta"><span class="grp"><b>Deed under review</b>{chip(draft_doc.doc_id, "ind")}</span>'
      f'<span class="grp"><b>Earlier deeds in the chain</b>{parents}</span></div>')

    tiles([
        ("Class A", len(class_a), "#dc2626", "registrability checks"),
        ("Class B", len(class_b), "#d97706", "advisories, not refusal grounds"),
        ("Needs review", len(needs_review), "#2563eb", "unreadable fields"),
        ("Fields read", sum(1 for f in draft_doc.fields.values() if f.status == FieldStatus.EXTRACTED),
         "#059669", f"of {len(draft_doc.fields)} checked"),
    ])

    tab1, tab2, tab3 = st.tabs(["🔎 Findings", "📋 Extracted fields", "✅ What to do next"])

    with tab1:
        render_evidence_states(draft_doc, class_a, class_b, needs_review)

        section(f"Class A · Registrability ({len(class_a)})",
                "Objective prerequisites. A gap here may justify refusal or return for correction.")
        if class_a:
            for flag in class_a:
                render_flag_card(flag, "A")
        else:
            empty("No Class A items found among the uploaded documents. This does not mean the deed is free of problems.")

        section(f"Class B · Advisories ({len(class_b)})",
                "Title-intelligence signals. Never grounds for refusal; discuss with an advocate.")
        if class_b:
            for flag in class_b:
                render_flag_card(flag, "B")
        else:
            empty("No Class B advisories found among the uploaded documents.")

        section(f"Needs review ({len(needs_review)})",
                "Parts we could not read. No checks were run on them, and this says nothing about the deed.")
        if needs_review:
            for item in needs_review:
                render_flag_card(item, "R")
            with st.expander("✍️ Type the value yourself and re-run the checks"):
                review_keys = [r.get("field_path") for r in needs_review]
                chosen_key = st.selectbox("Field to correct:", review_keys)
                val_input = st.text_input(f"Value for '{chosen_key}' as printed on the deed:")
                if st.button("Apply correction", type="primary"):
                    if val_input.strip():
                        try:
                            apply_human_correction(draft_doc.doc_id, chosen_key, val_input.strip(), cfg=cfg)
                            st.success(f"Updated '{chosen_key}'. Re-running the checks...")
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Correction error: {ex}")
                    else:
                        st.warning("Please enter a value.")
        else:
            empty("Nothing is waiting for review.")

    with tab2:
        section("What we read from your deed", "Every value links back to the page and the exact words it came from.")
        render_fields_table(draft_doc)

    with tab3:
        left, right = st.columns([1.15, 1])
        req_items = build_request_list(draft_doc)
        with left:
            section("Ask your seller for", "Static checklist built from what is missing or unreadable.")
            if req_items:
                items = "".join(f'<li>{esc(r.get("text"))}</li>' for r in req_items)
                H(f'<div class="panel"><ul>{items}</ul></div>')
            else:
                empty("No extra documents requested based on what was uploaded.")

            section("Advocate hand-off brief", "Fixed wording, no AI-written legal text.")
            brief_md = build_brief(analysis, req_items)
            st.info("This brief is a document analysis and a question list for your advocate. "
                    "It is not a legal opinion and does not guarantee title.")
            with st.expander("Preview the brief", expanded=True):
                st.markdown(brief_md)
            st.download_button(
                label="📄 Download advocate brief (Markdown)",
                data=brief_md,
                file_name=f"advocate_brief_{draft_doc.doc_id}.md",
                mime="text/markdown",
                use_container_width=True,
                type="primary",
            )
        with right:
            notchecked = "".join(f"<li>{esc(i)}</li>" for i in NOT_CHECKED)
            H('<div class="panel disclaimer"><h4>⚠️ What we did not check</h4>'
              '<div style="font-size:.88rem;color:#78350f;margin-bottom:.3rem">LandGuard AI does not certify title. '
              'These items were not inspected:</div>'
              f'<ul>{notchecked}</ul>'
              '<div style="font-size:.84rem;color:#78350f"><i>An advocate should confirm possession, mutation and revenue records.</i></div></div>')


# =============================================================================
# SCREEN 2: SUB-REGISTRAR OFFICER CONSOLE
# =============================================================================
def screen_officer_console() -> None:
    hero("Sub-Registrar console", "Record your decision, with reasons",
         "Every flag needs a recorded disposition. The entry is hashed, signed with Ed25519 and appended to a "
         "tamper-evident ledger. The system supports your decision; it does not make it.")

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

    tiles([
        ("Class A", len(class_a), "#dc2626", "may justify refusal"),
        ("Class B", len(class_b), "#d97706", "advisories: record a disposition"),
        ("Unreadable fields", len(analysis.get("needs_review", [])), "#2563eb", "no flags raised on them"),
        ("Ruleset", RULESET_VERSION, "#4f46e5", "recorded in the ledger"),
    ])

    with st.container(border=True):
        c1, c2 = st.columns(2)
        parcel_ulpin = c1.text_input("Parcel ULPIN / Bhu-Aadhaar", value=bundle_meta["ulpin"])
        officer_id = c2.text_input("Officer digital token (DSC ID)", value="OFFICER-SUBREG-KAMRUP-04")

    section("Findings and dispositions", "Class B advisories cannot be used to refuse; only Class A with a ground reference.")
    if not all_flags:
        empty("No flags were raised among the uploaded documents. This does not certify title.")

    dispositions: Dict[str, Dict[str, str]] = {}
    for idx, flag in enumerate(all_flags):
        fid = flag.get("flag_id", f"FLAG-{idx}")
        is_class_a = (flag.get("class") == "A" or flag.get("severity") == HARD_STOP)
        with st.container(border=True):
            render_flag_card(flag, "A" if is_class_a else "B")
            allowed_actions = list(DISPOSITION_CODES)
            if not is_class_a:
                allowed_actions = [a for a in allowed_actions if a != "REFUSE_RECORDED_GROUND"]
            allowed_actions.sort()

            c1, c2, c3 = st.columns([1.2, 1.6, 1.1])
            action = c1.selectbox(f"Action for {fid}", allowed_actions, key=f"act_{fid}",
                                  help="REFUSE_RECORDED_GROUND is restricted to Class A flags.")
            reason = c2.text_input(f"Recorded reason for {fid}", key=f"reason_{fid}",
                                   placeholder="A reason is required...")
            ground_ref = ""
            if action == "REFUSE_RECORDED_GROUND":
                ground_ref = c3.text_input("Ground reference", key=f"ground_{fid}", placeholder="e.g. s.58(…)")
            else:
                c3.caption("Ground reference applies only to a formal refusal.")
            entry = {"action": action, "reason": reason}
            if ground_ref:
                entry["ground_ref"] = ground_ref
            dispositions[fid] = entry

    section("Sign and record", "Creates a SHA-256 block, salted name commitments and an Ed25519 signature.")
    if st.button("🔐 Sign and record decision", type="primary"):
        try:
            missing = validate_dispositions(dispositions, all_flags)
            if missing:
                st.error(f"Missing disposition decisions for: {', '.join(missing)}")
                return
            with st.spinner("Signing and recording… 🛡️"):
                result = commit_to_ledger(
                    parcel_ulpin=parcel_ulpin,
                    draft_deed_json=draft_doc,
                    parent_deed_json_list=bundle_docs,
                    all_flags_dicts=all_flags,
                    officer_dispositions=dispositions,
                    officer_id=officer_id,
                )
            st.balloons()
            H(
                '<div class="receipt"><b style="color:#065f46">✅ Decision recorded in the tamper-evident ledger</b>'
                f'<div class="row"><b>Block</b> #{esc(result.get("row_id"))}</div>'
                f'<div class="row"><b>Entry hash (SHA-256)</b> <span class="code">{esc(result.get("entry_hash"))}</span></div>'
                f'<div class="row"><b>Ed25519 signature</b> <span class="code">{esc(str(result.get("signature"))[:48])}…</span></div>'
                f'<div class="row"><b>Signer public key</b> <span class="code">{esc(str(result.get("public_key"))[:48])}…</span></div></div>'
            )
        except ValueError as val_err:
            st.error(f"Disposition validation error: {val_err}")
        except Exception as ex:
            st.error(f"Ledger commit failed: {ex}")


# =============================================================================
# SCREEN 3: LEDGER VERIFICATION & TAMPER DEMO
# =============================================================================
def screen_ledger_verify() -> None:
    hero("Decision ledger", "Prove nothing was changed afterwards",
         "A hash-chained, Ed25519-signed log of officer decisions. It shows what the system produced and what the officer "
         "recorded, and that none of it was altered. It does not prove fault. Names are stored only as salted commitments.")

    blocks = al.list_blocks()
    head = al.get_chain_head()

    tiles([
        ("Blocks recorded", len(blocks), "#4f46e5", "append-only"),
        ("Chain head", f"#{head[0]}" if head else "—", "#7c3aed", (head[1][:18] + "…") if head else "empty ledger"),
        ("Signatures", "Ed25519", "#059669", "per entry"),
    ])

    if st.button("🔍 Verify entire chain and signatures", type="primary"):
        with st.spinner("Verifying hashes and signatures… 🛡️"):
            ok, bad_idx, reason = sg.verify_signatures()
        if ok:
            st.success("Chain verified: every SHA-256 hash and Ed25519 signature matches.")
        else:
            st.error(f"Verification failed at block #{bad_idx}: {reason}")

    section("The chain", "Each block commits to the one before it.")
    if blocks:
        cells = []
        for b in blocks[-8:]:
            cells.append(
                f'<div class="blk"><b>Block #{esc(b.get("idx"))}</b><br>{esc(b.get("parcel_ref"))}<br>'
                f'prev <span class="hx">{esc(b.get("prev_hash", "")[:10])}</span><br>'
                f'hash <span class="hx">{esc(b.get("entry_hash", "")[:10])}</span></div>')
        H('<div class="chain">' + '<span class="arrow">→</span>'.join(cells) + '</div>')

        table = []
        for b in blocks:
            cs = b.get("checklist_state") or {}
            table.append({
                "Idx": b.get("idx"),
                "Timestamp": b.get("timestamp"),
                "Parcel ULPIN": b.get("parcel_ref"),
                "Bundle hash": f"{b.get('bundle_hash', '')[:16]}…",
                "Entry hash": f"{b.get('entry_hash', '')[:16]}…",
                "Class A": cs.get("hard_stop_count", 0),
                "Class B": cs.get("advisory_count", 0),
                "Ruleset": cs.get("ruleset_version", ""),
                "Officer DSC": b.get("officer_sig_ref"),
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        empty("The ledger is empty. Record a decision in the Officer Console first.")

    section("Tamper test", "Edits a temporary COPY of the database. The real ledger is never touched.")
    if st.button("🧪 Run tamper demonstration"):
        if not blocks:
            st.warning("Record at least one block in the Officer Console before testing tampering.")
            return
        tmp_dir = tempfile.mkdtemp()
        tmp_db = Path(tmp_dir) / "tampered_audit.db"
        shutil.copy(al.DB_PATH, tmp_db)
        conn = sqlite3.connect(tmp_db)
        try:
            conn.execute("UPDATE audit_log SET dispositions = '{\"TAMPERED\": {\"action\": \"FORGED_APPROVAL\"}}' "
                         "WHERE idx = (SELECT MIN(idx) FROM audit_log)")
            conn.commit()
        finally:
            conn.close()

        orig_db_path = al.DB_PATH
        try:
            al.DB_PATH = str(tmp_db)
            ok, bad_idx, reason = sg.verify_signatures()
            H(
                '<div class="alarm"><b style="color:#991b1b">🚨 Tampering detected</b>'
                f'<div style="margin-top:.4rem;font-size:.9rem;color:#7f1d1d">A disposition in block #{esc(bad_idx)} was edited in the copy. '
                f'Verification returned <span class="code">ok={esc(ok)}</span>, <span class="code">reason="{esc(reason)}"</span>.</div>'
                '<div style="margin-top:.4rem;font-size:.86rem;color:#7f1d1d">The edited content no longer matches its SHA-256 '
                'hash or signature. The live ledger was not modified.</div></div>')
        finally:
            al.DB_PATH = orig_db_path
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# MAIN APP ROUTER
# =============================================================================
def main() -> None:
    with st.sidebar:
        _sidebar_brand()
        screen = st.radio(
            "Navigation:",
            ["1. Citizen Pre-Flight Check", "2. Sub-Registrar Officer Console", "3. Decision Ledger & Verification"],
        )
        st.markdown("---")

    if screen.startswith("1."):
        screen_citizen_preflight()
    elif screen.startswith("2."):
        screen_officer_console()
    else:
        screen_ledger_verify()

    with st.sidebar:
        st.markdown("---")
        H(f'<div class="sbnote">Ruleset <b>{esc(RULESET_VERSION)}</b> · Provider <b>cached (offline)</b></div>')
        H('<div class="principles">'
          '• Deterministic rules, no LLM in the checks<br>'
          '• Every finding cites page and quote<br>'
          '• No “clean”, no title score<br>'
          '• Signed, tamper-evident log</div>')


if __name__ == "__main__":
    main()
