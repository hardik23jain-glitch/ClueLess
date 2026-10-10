"""
LandGuard AI - Pre-Transaction Risk-Prevention Layer for Indian Property Registration.
Offline-capable Streamlit application, styled as a website (top navigation, landing page, steps).

Pages:
  Home                  landing page: what it does, how it works, what it never does
  Check my documents    citizen pre-flight: findings with evidence, fields read, next steps, advocate brief
  Officer console       record a disposition per flag, sign into the ledger
  Decision ledger       verify the hash chain and signatures, tamper demo

Design rules shown in the UI: never "clean"/"safe"/"verified title", no numeric title score, always a
"What we did not check" panel, every finding cites page + quote. All illustrations are inline SVG
(no downloads), so the app works offline.
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
    page_title="LandGuard AI | Check property documents before you pay",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

NAV = ["🏠 Home", "🔍 Check my documents", "🏛️ Officer console", "🔐 Decision ledger"]

# ----------------------------------------------------------------------------------------------
# Design system: teal + saffron on warm cream
# ----------------------------------------------------------------------------------------------
CSS = """
<style>
:root{
  --ink:#10262a; --muted:#5b7276; --line:#e4ece8; --card:#ffffff; --cream:#fffbf5;
  --t9:#134e4a; --t7:#0f766e; --t5:#14b8a6; --t1:#ccfbf1; --t0:#f0fdfa;
  --saf:#f59e0b; --saf-d:#b45309; --saf-bg:#fffbeb;
  --a:#e11d48; --a-bg:#fff1f2; --b:#d97706; --b-bg:#fffbeb; --r:#0284c7; --r-bg:#f0f9ff;
  --ok:#059669; --ok-bg:#ecfdf5;
}
html, body, [class*="css"], .stApp { font-family:"Segoe UI","Inter",system-ui,-apple-system,sans-serif; }
.stApp { background:var(--cream); }
#MainMenu, footer, header[data-testid="stHeader"] { visibility:hidden; height:0; }
section[data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"]{ display:none; }
.block-container{ padding-top:.8rem; padding-bottom:0; max-width:1240px; }
h1,h2,h3,h4{ color:var(--ink); }

/* top navigation */
.navbar{ display:flex; align-items:center; gap:.7rem; padding:.3rem 0 .2rem; }
.navbar .logo{ width:40px; height:40px; border-radius:12px; background:linear-gradient(135deg,#14b8a6,#0f766e);
  display:flex; align-items:center; justify-content:center; font-size:1.25rem; box-shadow:0 6px 16px rgba(15,118,110,.35); }
.navbar .nm{ font-weight:800; font-size:1.25rem; color:var(--t9); letter-spacing:-.02em; }
.navbar .nm span{ color:var(--saf); }
.navbar .tag{ margin-left:.4rem; font-size:.72rem; font-weight:700; color:var(--t7); background:var(--t0); border:1px solid var(--t1);
  padding:.15rem .55rem; border-radius:999px; }
div[data-testid="stRadio"] div[role="radiogroup"]{ gap:.35rem; justify-content:flex-end; flex-wrap:wrap; }
div[data-testid="stRadio"] label[data-baseweb="radio"]{ background:#fff; border:1px solid var(--line); border-radius:999px;
  padding:.38rem .95rem; margin:0; cursor:pointer; transition:all .15s; }
div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child{ display:none; }
div[data-testid="stRadio"] label[data-baseweb="radio"]:hover{ border-color:var(--t5); background:var(--t0); }
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked){ background:var(--t7); border-color:var(--t7); }
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) *{ color:#fff !important; }
div[data-testid="stRadio"] label[data-baseweb="radio"] p{ font-weight:650; font-size:.9rem; margin:0; }
hr.nav{ border:0; border-top:1px solid var(--line); margin:.5rem 0 1rem; }

/* hero */
.hero{ display:grid; grid-template-columns:1.15fr .85fr; gap:1.2rem; align-items:center;
  background:linear-gradient(135deg,#134e4a 0%,#0f766e 55%,#0d9488 100%); border-radius:24px; padding:2.2rem 2.4rem; color:#fff;
  position:relative; overflow:hidden; box-shadow:0 18px 40px rgba(15,118,110,.28); margin-bottom:1.2rem; }
@media(max-width:900px){ .hero{ grid-template-columns:1fr; } .hero .art{ display:none; } }
.hero:before{ content:""; position:absolute; right:-80px; bottom:-120px; width:380px; height:380px; border-radius:50%;
  background:radial-gradient(circle,rgba(245,158,11,.35),transparent 65%); }
.hero .eyebrow{ display:inline-block; font-size:.74rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700;
  background:rgba(255,255,255,.14); padding:.3rem .8rem; border-radius:999px; }
.hero h1{ color:#fff; font-size:2.6rem; line-height:1.12; font-weight:800; letter-spacing:-.03em; margin:.8rem 0 .7rem; padding:0; }
.hero h1 em{ font-style:normal; color:#fcd34d; }
.hero p{ font-size:1.05rem; line-height:1.6; opacity:.92; max-width:560px; margin:0; }
.hero .art{ position:relative; z-index:1; }
.hero .art svg{ width:100%; height:auto; filter:drop-shadow(0 16px 24px rgba(0,0,0,.22)); }
.pagehero{ background:linear-gradient(135deg,#134e4a,#0f766e); color:#fff; border-radius:20px; padding:1.4rem 1.7rem; margin-bottom:1rem;
  box-shadow:0 12px 28px rgba(15,118,110,.22); position:relative; overflow:hidden; }
.pagehero:after{ content:""; position:absolute; right:-50px; top:-70px; width:220px; height:220px; border-radius:50%;
  background:radial-gradient(circle,rgba(245,158,11,.4),transparent 70%); }
.pagehero .eyebrow{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; opacity:.8; font-weight:700; }
.pagehero h1{ color:#fff; font-size:1.8rem; margin:.15rem 0 .3rem; padding:0; font-weight:780; letter-spacing:-.02em; }
.pagehero p{ margin:0; opacity:.9; max-width:820px; line-height:1.5; }

/* sections & cards */
.band{ text-align:center; margin:2rem 0 1rem; }
.band h2{ font-size:1.7rem; font-weight:780; letter-spacing:-.02em; margin:0; padding:0; color:var(--t9); }
.band p{ color:var(--muted); margin:.3rem 0 0; }
.grid{ display:grid; gap:1rem; }
.g3{ grid-template-columns:repeat(3,1fr); } .g4{ grid-template-columns:repeat(4,1fr); }
@media(max-width:1000px){ .g3,.g4{ grid-template-columns:1fr 1fr; } } @media(max-width:640px){ .g3,.g4{ grid-template-columns:1fr; } }
.card{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:1.3rem 1.3rem 1.2rem;
  box-shadow:0 2px 10px rgba(16,38,42,.05); transition:transform .15s, box-shadow .15s; }
.card:hover{ transform:translateY(-3px); box-shadow:0 12px 26px rgba(16,38,42,.1); }
.card .ico{ width:54px; height:54px; border-radius:15px; background:var(--t0); display:flex; align-items:center; justify-content:center; margin-bottom:.7rem; }
.card .ico svg{ width:30px; height:30px; }
.card .stepno{ font-size:.72rem; font-weight:800; letter-spacing:.1em; color:var(--saf-d); text-transform:uppercase; }
.card h3{ margin:.15rem 0 .35rem; font-size:1.08rem; font-weight:740; padding:0; color:var(--ink); }
.card p{ margin:0; color:var(--muted); font-size:.92rem; line-height:1.55; }
.trust{ display:grid; grid-template-columns:repeat(4,1fr); gap:.8rem; margin:0 0 .4rem; }
@media(max-width:900px){ .trust{ grid-template-columns:1fr 1fr; } }
.trust div{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:.8rem 1rem; text-align:center; }
.trust b{ display:block; font-size:1.35rem; color:var(--t7); } .trust span{ font-size:.8rem; color:var(--muted); }
.never{ background:linear-gradient(135deg,#fffbeb,#fff7ed); border:1px solid #fde68a; border-radius:20px; padding:1.4rem 1.6rem; }
.never h3{ margin:0 0 .5rem; color:#92400e; padding:0; }
.never ul{ margin:0; padding-left:1.2rem; color:#78350f; line-height:1.8; font-size:.95rem; }
.sitefooter{ margin:2.2rem -1rem 0; padding:1.4rem 1.5rem; background:var(--t9); color:#99f6e4; font-size:.85rem; text-align:center; line-height:1.7; }
.sitefooter b{ color:#fff; }

/* stepper */
.stepper{ display:flex; flex-wrap:wrap; gap:.5rem; margin:.1rem 0 1rem; }
.stepper span{ display:inline-flex; align-items:center; gap:.45rem; font-size:.85rem; font-weight:650; color:var(--t9);
  background:#fff; border:1px solid var(--line); border-radius:999px; padding:.3rem .8rem .3rem .35rem; }
.stepper i{ font-style:normal; width:22px; height:22px; border-radius:50%; background:var(--t7); color:#fff; font-size:.75rem;
  display:inline-flex; align-items:center; justify-content:center; }

/* tiles */
.tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:.8rem; margin:.4rem 0 1.1rem; }
.tile{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:1rem 1.1rem;
  box-shadow:0 2px 8px rgba(16,38,42,.04); position:relative; overflow:hidden; }
.tile:before{ content:""; position:absolute; left:0; top:0; bottom:0; width:5px; background:var(--accent,#94a3b8); }
.tile .v{ font-size:2rem; font-weight:800; line-height:1.1; color:var(--accent,#10262a); }
.tile .l{ font-size:.8rem; color:var(--ink); font-weight:700; margin-top:.25rem; }
.tile .s{ font-size:.78rem; color:var(--muted); margin-top:.1rem; }

/* chips */
.chip{ display:inline-block; padding:.18rem .62rem; border-radius:999px; font-size:.74rem; font-weight:700;
  border:1px solid transparent; margin-right:.35rem; white-space:nowrap; }
.chip.a{ background:var(--a-bg); color:#9f1239; border-color:#fecdd3; }
.chip.b{ background:var(--b-bg); color:#92400e; border-color:#fde68a; }
.chip.r{ background:var(--r-bg); color:#075985; border-color:#bae6fd; }
.chip.ok{ background:var(--ok-bg); color:#065f46; border-color:#a7f3d0; }
.chip.n{ background:#f1f5f4; color:#475b5e; border-color:#d3dedc; }
.chip.ind{ background:var(--t0); color:var(--t9); border-color:var(--t1); }
.meta{ display:flex; flex-wrap:wrap; gap:.5rem 1.8rem; align-items:center; margin:.2rem 0 .8rem; }
.meta .grp{ display:inline-flex; align-items:center; gap:.45rem; }

/* flag cards */
.fcard{ background:var(--card); border:1px solid var(--line); border-left:6px solid var(--accent); border-radius:14px;
  padding:1rem 1.15rem; margin-bottom:.4rem; box-shadow:0 2px 8px rgba(16,38,42,.05); }
.fcard.a{ --accent:var(--a); } .fcard.b{ --accent:var(--b); } .fcard.r{ --accent:var(--r); }
.fcard .top{ display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; margin-bottom:.35rem; }
.fcard .ttl{ font-weight:740; font-size:1.04rem; color:var(--ink); }
.fcard .ev{ margin-top:.5rem; border-left:3px solid var(--t5); padding:.35rem .75rem; background:var(--t0); border-radius:0 10px 10px 0;
  font-size:.86rem; color:#35514f; }
.fcard .ev b{ color:var(--ink); }
.fcard code, .code{ background:var(--t0); color:var(--t9); padding:.05rem .35rem; border-radius:5px; font-size:.78rem; }

/* state cards */
.states{ display:grid; grid-template-columns:repeat(3,1fr); gap:.8rem; margin-bottom:1rem; }
@media(max-width:900px){ .states{ grid-template-columns:1fr; } }
.state{ border-radius:16px; padding:.95rem 1.05rem; border:1px solid var(--line); background:var(--card); }
.state .h{ font-size:.74rem; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }
.state .n{ font-size:1.8rem; font-weight:800; margin:.15rem 0; }
.state .d{ font-size:.83rem; color:var(--muted); line-height:1.4; }
.state.ok{ background:var(--ok-bg); border-color:#a7f3d0; } .state.ok .h,.state.ok .n{ color:#065f46; }
.state.x{ background:var(--a-bg); border-color:#fecdd3; } .state.x .h,.state.x .n{ color:#9f1239; }
.state.u{ background:#f1f5f4; border-color:#d3dedc; } .state.u .h,.state.u .n{ color:#334b4e; }

.sec{ display:flex; align-items:baseline; gap:.6rem; margin:1.3rem 0 .3rem; flex-wrap:wrap; }
.sec h3{ margin:0; font-size:1.15rem; font-weight:760; color:var(--ink); padding:0; }
.sec span{ color:var(--muted); font-size:.86rem; }
.empty{ background:#fff; border:1px dashed #b9cbc6; border-radius:14px; padding:.85rem 1.1rem; color:#4a6366; font-size:.92rem; }
.panel{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:1rem 1.15rem; margin-bottom:1rem;
  box-shadow:0 2px 8px rgba(16,38,42,.04); }
.panel h4{ margin:0 0 .5rem; font-size:1rem; font-weight:740; padding:0; }
.panel ul{ margin:.2rem 0 .4rem; padding-left:1.1rem; color:#2f4a4d; font-size:.92rem; line-height:1.7; }
.disclaimer{ background:linear-gradient(180deg,#fffbeb,#fff7ed); border-color:#fde68a; }

/* field table */
.ftable{ width:100%; border-collapse:separate; border-spacing:0; font-size:.86rem; background:#fff; border:1px solid var(--line);
  border-radius:14px; overflow:hidden; }
.ftable th{ text-align:left; background:var(--t0); color:var(--t9); font-size:.72rem; letter-spacing:.06em; text-transform:uppercase;
  padding:.6rem .75rem; position:sticky; top:0; }
.ftable td{ padding:.5rem .75rem; border-top:1px solid #eef3f1; vertical-align:top; color:#1d3a3d; }
.ftable tr:hover td{ background:#f7fdfb; }
.bar{ width:90px; height:7px; background:#e3ece9; border-radius:99px; overflow:hidden; display:inline-block; vertical-align:middle; }
.bar i{ display:block; height:100%; background:linear-gradient(90deg,#5eead4,#0f766e); border-radius:99px; }
.q{ color:#668083; font-style:italic; }

/* ledger */
.chain{ display:flex; align-items:center; gap:.4rem; overflow-x:auto; padding:.4rem .1rem 1rem; }
.blk{ min-width:155px; background:#fff; border:1px solid var(--line); border-top:5px solid var(--t7); border-radius:14px;
  padding:.65rem .8rem; box-shadow:0 2px 8px rgba(16,38,42,.06); font-size:.78rem; }
.blk b{ font-size:.92rem; color:var(--ink); } .blk .hx{ font-family:Consolas,monospace; color:var(--t7); }
.arrow{ color:#9bb5b0; font-size:1.3rem; }
.receipt{ background:linear-gradient(135deg,#ecfdf5,#f0fdfa); border:1px solid #a7f3d0; border-radius:16px; padding:1rem 1.2rem; }
.receipt .row{ font-size:.88rem; color:#064e3b; margin:.2rem 0; word-break:break-all; }
.alarm{ background:linear-gradient(135deg,#fff1f2,#fff5f5); border:1px solid #fecdd3; border-radius:16px; padding:1rem 1.2rem; }

/* buttons & tabs */
.stButton>button, .stDownloadButton>button{ border-radius:12px; font-weight:700; border:1px solid #b6d8d2; padding:.55rem 1.1rem; }
.stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"]{ background:linear-gradient(135deg,#0f766e,#0d9488); border:0; color:#fff;
  box-shadow:0 8px 18px rgba(15,118,110,.32); }
.stButton>button[kind="primary"]:hover{ filter:brightness(1.07); }
button[data-baseweb="tab"]{ font-weight:700; font-size:.95rem; }
div[data-baseweb="tab-highlight"]{ background:var(--t7) !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------------------------
# Inline SVG illustrations (no downloads, work offline)
# ----------------------------------------------------------------------------------------------
HERO_SVG = """
<svg viewBox="0 0 380 320" xmlns="http://www.w3.org/2000/svg">
 <defs>
  <linearGradient id="sh" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2dd4bf"/><stop offset="1" stop-color="#0f766e"/></linearGradient>
  <linearGradient id="roof" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#f59e0b"/></linearGradient>
 </defs>
 <circle cx="190" cy="165" r="138" fill="#ffffff" opacity=".10"/>
 <circle cx="190" cy="165" r="104" fill="#ffffff" opacity=".10"/>
 <g transform="rotate(-6 165 160)">
  <rect x="78" y="38" width="184" height="236" rx="16" fill="#ffffff"/>
  <rect x="78" y="38" width="184" height="40" rx="16" fill="#ccfbf1"/>
  <rect x="98" y="52" width="78" height="10" rx="5" fill="#0f766e"/>
  <path d="M112 156 L170 104 L228 156 Z" fill="url(#roof)"/>
  <rect x="132" y="156" width="76" height="52" rx="4" fill="#fde68a"/>
  <rect x="160" y="172" width="20" height="36" rx="3" fill="#b45309"/>
  <rect x="98" y="222" width="120" height="8" rx="4" fill="#99f6e4"/>
  <rect x="98" y="240" width="90" height="8" rx="4" fill="#ccfbf1"/>
  <circle cx="226" cy="236" r="19" fill="none" stroke="#f59e0b" stroke-width="3" stroke-dasharray="5 4"/>
 </g>
 <path d="M282 168 L336 188 V232 C336 266 308 284 282 296 C256 284 228 266 228 232 V188 Z" fill="url(#sh)" stroke="#ffffff" stroke-width="5"/>
 <path d="M258 234 L277 253 L309 216" fill="none" stroke="#ffffff" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
 <g fill="#fcd34d"><circle cx="64" cy="82" r="5"/><circle cx="326" cy="70" r="4"/><circle cx="48" cy="236" r="3.5"/></g>
 <g stroke="#ffffff" stroke-width="3" stroke-linecap="round" opacity=".7"><path d="M318 100 v14 M311 107 h14"/><path d="M40 150 v12 M34 156 h12"/></g>
</svg>
"""

ICON_UPLOAD = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M8 4h11l6 6v18H8z"/><path d="M19 4v6h6"/><path d="M12 19h8M12 23h8M12 15h4"/></svg>')
ICON_SEARCH = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
               '<circle cx="14" cy="14" r="8"/><path d="M20 20l8 8"/><path d="M10.5 14l2.5 2.5L18 11.5"/></svg>')
ICON_LOCK = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
             '<rect x="6" y="14" width="20" height="14" rx="3"/><path d="M10 14V10a6 6 0 0112 0v4"/><path d="M16 20v3"/></svg>')
ICON_PIN = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M16 29s9-8 9-15a9 9 0 10-18 0c0 7 9 15 9 15z"/><circle cx="16" cy="14" r="3.5"/></svg>')
ICON_EYE = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3 16s5-9 13-9 13 9 13 9-5 9-13 9S3 16 3 16z"/><circle cx="16" cy="16" r="4"/></svg>')
ICON_LIST = ('<svg viewBox="0 0 32 32" fill="none" stroke="#0f766e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
             '<path d="M11 8h16M11 16h16M11 24h16"/><path d="M4 8l1.5 1.5L8 7M4 16l1.5 1.5L8 15M4 24l1.5 1.5L8 23"/></svg>')


# ----------------------------------------------------------------------------------------------
# HTML helpers (single-line output so Markdown never mistakes indentation for a code block)
# ----------------------------------------------------------------------------------------------
def esc(x: Any) -> str:
    return _html.escape("" if x is None else str(x))


def H(markup: str) -> None:
    st.markdown(" ".join(line.strip() for line in markup.strip().splitlines()), unsafe_allow_html=True)


def pagehero(eyebrow: str, title: str, subtitle: str) -> None:
    H(f'<div class="pagehero"><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>')


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


def stepper(steps: List[str]) -> None:
    H('<div class="stepper">' + "".join(f"<span><i>{i}</i>{esc(s)}</span>" for i, s in enumerate(steps, 1)) + "</div>")


def go(page: str) -> None:
    st.session_state["nav"] = page


SAMPLE_BUNDLES = {
    "Parcel P1: 3-Deed Chain, No Defects Planted (Assam)": {
        "ulpin": "AS000000000101", "draft_id": "P1-D3", "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Ownership passes through three conveyances (2010 -> 2016 -> 2022). No defects planted.",
    },
    "Parcel P2: Broken Ownership Link": {
        "ulpin": "AS000000000102", "draft_id": "P2-D2", "bundle_ids": ["P2-D1"],
        "desc": "Seller claims acquisition in 2018, but the registry's recorded owner is Sunil Verma.",
    },
    "Parcel P3: Parallel Conveyance (Double Sale)": {
        "ulpin": "AS000000000104", "draft_id": "P3-D2", "bundle_ids": ["P3-D1"],
        "desc": "Registry index shows another transfer of the same plot in 2015 to a third party.",
    },
    "Parcel P4: Area Exceeds Parent Deed": {
        "ulpin": "AS000000000103", "draft_id": "P4-D2", "bundle_ids": ["P4-D1"],
        "desc": "Transferred area (1500 sq ft) exceeds the parent deed area (1000 sq ft).",
    },
    "Parcel P5: Boundary Mismatch Against Parent": {
        "ulpin": "AS000000000105", "draft_id": "P5-D2", "bundle_ids": ["P5-D1"],
        "desc": "North boundary in the draft deed differs from the one recorded in the parent deed.",
    },
    "Parcel P6: Attorney Transfer Missing POA Reg No": {
        "ulpin": "AS000000000107", "draft_id": "P6-D2", "bundle_ids": ["P6-D1"],
        "desc": "Deed executed through a power-of-attorney holder with no POA registration number.",
    },
    "Parcel P7: Chain Gap Explained by Succession (Decoy)": {
        "ulpin": "AS000000000108", "draft_id": "P7-D3", "bundle_ids": ["P7-D1", "P7-D2"],
        "desc": "Seller gap is explained by a registered succession document, so the broken-link advisory is suppressed.",
    },
    "Parcel P8: Hindi Devanagari Deed (Boundary Mismatch)": {
        "ulpin": "AS000000000109", "draft_id": "P8-D2", "bundle_ids": ["P8-D1"],
        "desc": "Devanagari sale deed compared with an earlier registered deed. Boundary difference found.",
    },
    "P1 Degraded Scan": {
        "ulpin": "AS000000000101", "draft_id": "P1-D3-scan", "bundle_ids": ["P1-D1", "P1-D2"],
        "desc": "Scanned copy of P1 with simulated tilt and blur; tests OCR and the quality gate.",
    },
    "P6 Degraded Scan: Attorney Transfer": {
        "ulpin": "AS000000000107", "draft_id": "P6-D2-scan", "bundle_ids": ["P6-D1"],
        "desc": "On a poor scan the POA detail is unreadable, so it goes to human review instead of a false hard stop.",
    },
}


def _get_cfg() -> Config:
    return Config(provider="mock")


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
        f'<div class="fcard {kind}"><div class="top">{chip(rule_id or "R", kind)}'
        f'<span class="ttl">{esc(title)}</span></div>'
        f'<div style="margin-bottom:.2rem">{chip(label, kind)}<code>{esc(code)}</code>'
        f'{f" <code>{esc(field_path)}</code>" if field_path else ""}</div>{citation}</div>'
    )
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
    H('<div style="max-height:560px;overflow:auto;border-radius:14px"><table class="ftable"><thead><tr>'
      '<th>Field</th><th>Status</th><th>Value</th><th>Reading confidence</th><th>Evidence</th></tr></thead><tbody>'
      + "".join(rows) + '</tbody></table></div>')
    st.caption("Confidence is how reliably a field was read. It is not a statement about the deed or the title.")


# =============================================================================
# PAGE: HOME (landing)
# =============================================================================
def page_home() -> None:
    H(f'<div class="hero"><div><span class="eyebrow">Property documents · India</span>'
      f'<h1>Check your property papers <em>before</em> you pay.</h1>'
      f'<p>LandGuard AI reads your deeds, runs fixed registration checks and shows exactly which page every finding comes from. '
      f'It tells you what the documents support, what they contradict, and what nobody has checked. It never certifies title.</p></div>'
      f'<div class="art">{HERO_SVG}</div></div>')

    c1, c2, _ = st.columns([1.2, 1.2, 3])
    c1.button("Check my documents →", type="primary", on_click=go, args=(NAV[1],), use_container_width=True)
    c2.button("I am a Sub-Registrar", on_click=go, args=(NAV[2],), use_container_width=True)

    H('<div class="trust"><div><b>24</b><span>fields read from every deed</span></div>'
      '<div><b>Page + quote</b><span>behind every finding</span></div>'
      '<div><b>English · हिन्दी</b><span>tested on typed and scanned deeds</span></div>'
      '<div><b>Signed</b><span>tamper-evident decision log</span></div></div>')

    H('<div class="band"><h2>How it works</h2><p>Three simple steps. No legal jargon required.</p></div>')
    H(f'<div class="grid g3">'
      f'<div class="card"><div class="ico">{ICON_UPLOAD}</div><div class="stepno">Step 1</div><h3>Share your deeds</h3>'
      f'<p>Pick the sale deed and the earlier deeds in the chain. PDFs, scans and phone photos work, in English or Hindi.</p></div>'
      f'<div class="card"><div class="ico">{ICON_SEARCH}</div><div class="stepno">Step 2</div><h3>We read and check</h3>'
      f'<p>An AI reads the pages. Fixed rules, with no AI in them, then check registration requirements and the registry index.</p></div>'
      f'<div class="card"><div class="ico">{ICON_LIST}</div><div class="stepno">Step 3</div><h3>You get clear next steps</h3>'
      f'<p>See each finding with its page, a list to ask your seller for, and a brief your advocate can use.</p></div></div>')

    H('<div class="band"><h2>Built to be trusted</h2><p>Why people and officers can rely on what they see.</p></div>')
    H(f'<div class="grid g4">'
      f'<div class="card"><div class="ico">{ICON_PIN}</div><h3>Evidence for everything</h3><p>Every finding points to the page and the exact words it came from.</p></div>'
      f'<div class="card"><div class="ico">{ICON_EYE}</div><h3>No guessing</h3><p>If a part is unreadable we say &ldquo;needs review&rdquo; instead of inventing a result.</p></div>'
      f'<div class="card"><div class="ico">{ICON_LIST}</div><h3>Ask-your-seller list</h3><p>A plain checklist of missing documents, plus an advocate hand-off brief.</p></div>'
      f'<div class="card"><div class="ico">{ICON_LOCK}</div><h3>Signed officer record</h3><p>Sub-Registrar decisions go into a hash-chained, Ed25519-signed log. Edits are detected.</p></div></div>')

    H('<div class="band"><h2>What we never do</h2></div>')
    notchecked = "".join(f"<li>{esc(i)}</li>" for i in NOT_CHECKED)
    H('<div class="never"><h3>LandGuard AI does not certify title</h3>'
      '<ul><li>We never say a property is &ldquo;clean&rdquo; or &ldquo;safe&rdquo;, and we give no title score.</li>'
      '<li>&ldquo;Nothing found&rdquo; means only that nothing was found among the documents you uploaded.</li>'
      '<li>Things we did not check:</li></ul>'
      f'<ul style="margin-top:.2rem">{notchecked}</ul></div>')

    H('<div class="sitefooter"><b>LandGuard AI</b> · Pre-registration risk layer for Indian property deeds<br>'
      'Document analysis and question lists only, not legal advice. Demo uses synthetic documents. '
      'Built for the Cline AI Builder Hackathon.</div>')


# =============================================================================
# PAGE: CHECK MY DOCUMENTS (citizen)
# =============================================================================
def page_citizen() -> None:
    pagehero("Citizen pre-flight", "Check my documents",
             "Pick a case, read what we found, and see what to ask for next. This is a document analysis and a question "
             "list, not a legal opinion, and never a title certificate.")
    stepper(["Choose a case", "Read the findings", "Take the next steps"])

    cfg = _get_cfg()
    draft_doc: Optional[DeedExtraction] = None
    bundle_docs: List[DeedExtraction] = []

    with st.container(border=True):
        st.markdown("**Step 1 · Choose a case**")
        c1, c2 = st.columns([1, 2])
        data_source = c1.radio("Choose Input Mode:", ["Select Pre-Loaded Sample Bundle", "Upload Deed Files"], key="cit_mode")
        if data_source == "Select Pre-Loaded Sample Bundle":
            bundle_key = c2.selectbox("Sample Parcel Chain:", list(SAMPLE_BUNDLES.keys()), key="cit_bundle")
            meta = SAMPLE_BUNDLES[bundle_key]
            c2.info(meta["desc"])
            draft_doc = load_extraction(cfg, meta["draft_id"])
            bundle_docs = [load_extraction(cfg, bid) for bid in meta["bundle_ids"] if load_extraction(cfg, bid)]
        else:
            uploaded = c2.file_uploader("Upload PDF or Image Deed Bundle", accept_multiple_files=True, key="cit_upload")
            if not uploaded:
                c2.info("Add your deeds, or switch to a sample case.")
                return
            c2.info("Upload received. This demo shows the cached sample extraction instead of calling the model.")
            draft_doc = load_extraction(cfg, "P1-D3")
            bundle_docs = [load_extraction(cfg, "P1-D1"), load_extraction(cfg, "P1-D2")]

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
        ("Must-fix items", len(class_a), "#e11d48", "Class A · registrability checks"),
        ("Things to discuss", len(class_b), "#d97706", "Class B · advisories, not refusal grounds"),
        ("Could not read", len(needs_review), "#0284c7", "sent to human review"),
        ("Fields read", sum(1 for f in draft_doc.fields.values() if f.status == FieldStatus.EXTRACTED),
         "#059669", f"of {len(draft_doc.fields)} checked"),
    ])

    tab1, tab2, tab3 = st.tabs(["🔎 Findings", "📋 What we read", "✅ What to do next"])

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
            section("Ask your seller for", "A checklist built from what is missing or unreadable.")
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
# PAGE: OFFICER CONSOLE
# =============================================================================
def page_officer() -> None:
    pagehero("Sub-Registrar console", "Record your decision, with reasons",
             "Every flag needs a recorded disposition. The entry is hashed, signed with Ed25519 and appended to a "
             "tamper-evident ledger. The system supports your decision; it does not make it.")
    stepper(["Pick the application", "Record a decision per flag", "Sign and record"])

    cfg = _get_cfg()
    with st.container(border=True):
        st.markdown("**Step 1 · Pick the application**")
        c1, c2 = st.columns([1, 1.4])
        bundle_key = c1.selectbox("Select Active Application:", list(SAMPLE_BUNDLES.keys()), index=1, key="off_bundle")
        bundle_meta = SAMPLE_BUNDLES[bundle_key]
        c2.info(bundle_meta["desc"])

    draft_doc = load_extraction(cfg, bundle_meta["draft_id"])
    bundle_docs = [load_extraction(cfg, bid) for bid in bundle_meta["bundle_ids"] if load_extraction(cfg, bid)]
    if not draft_doc:
        st.error("Failed to load application draft.")
        return

    with st.spinner("Analyzing… 🛡️"):
        analysis = run_risk_analysis(draft_doc, bundle_docs)
    class_a = analysis.get("class_a_flags", [])
    class_b = analysis.get("class_b_flags", [])
    all_flags = class_a + class_b

    tiles([
        ("Class A", len(class_a), "#e11d48", "may justify refusal"),
        ("Class B", len(class_b), "#d97706", "advisories: record a disposition"),
        ("Unreadable fields", len(analysis.get("needs_review", [])), "#0284c7", "no flags raised on them"),
        ("Ruleset", RULESET_VERSION, "#0f766e", "recorded in the ledger"),
    ])

    with st.container(border=True):
        c1, c2 = st.columns(2)
        parcel_ulpin = c1.text_input("Parcel ULPIN / Bhu-Aadhaar", value=bundle_meta["ulpin"])
        officer_id = c2.text_input("Officer digital token (DSC ID)", value="OFFICER-SUBREG-KAMRUP-04")

    section("Step 2 · Findings and dispositions", "Class B advisories cannot be used to refuse; only Class A with a ground reference.")
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

    section("Step 3 · Sign and record", "Creates a SHA-256 block, salted name commitments and an Ed25519 signature.")
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
# PAGE: DECISION LEDGER
# =============================================================================
def page_ledger() -> None:
    pagehero("Decision ledger", "Prove nothing was changed afterwards",
             "A hash-chained, Ed25519-signed log of officer decisions. It shows what the system produced and what the officer "
             "recorded, and that none of it was altered. It does not prove fault. Names are stored only as salted commitments.")

    blocks = al.list_blocks()
    head = al.get_chain_head()

    tiles([
        ("Blocks recorded", len(blocks), "#0f766e", "append-only"),
        ("Chain head", f"#{head[0]}" if head else "—", "#d97706", (head[1][:18] + "…") if head else "empty ledger"),
        ("Signatures", "Ed25519", "#059669", "one per entry"),
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
                '<div class="alarm"><b style="color:#9f1239">🚨 Tampering detected</b>'
                f'<div style="margin-top:.4rem;font-size:.9rem;color:#881337">A disposition in block #{esc(bad_idx)} was edited in the copy. '
                f'Verification returned <span class="code">ok={esc(ok)}</span>, <span class="code">reason="{esc(reason)}"</span>.</div>'
                '<div style="margin-top:.4rem;font-size:.86rem;color:#881337">The edited content no longer matches its SHA-256 '
                'hash or signature. The live ledger was not modified.</div></div>')
        finally:
            al.DB_PATH = orig_db_path
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# MAIN APP ROUTER
# =============================================================================
def main() -> None:
    st.session_state.setdefault("nav", NAV[0])

    brand, nav_col = st.columns([1.15, 3])
    with brand:
        H('<div class="navbar"><div class="logo">🛡️</div><div class="nm">Land<span>Guard</span> AI</div></div>')
    with nav_col:
        st.radio("Navigation:", NAV, horizontal=True, key="nav", label_visibility="collapsed")
    H('<hr class="nav">')

    page = st.session_state["nav"]
    if page == NAV[0]:
        page_home()
    elif page == NAV[1]:
        page_citizen()
    elif page == NAV[2]:
        page_officer()
    else:
        page_ledger()

    if page != NAV[0]:
        H(f'<div class="sitefooter"><b>LandGuard AI</b> · Ruleset {esc(RULESET_VERSION)} · cached offline demo data<br>'
          'Deterministic rules · every finding cites page and quote · no “clean”, no title score · signed, tamper-evident log</div>')


if __name__ == "__main__":
    main()
