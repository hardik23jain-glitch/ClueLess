# ClueLess: LandGuard AI

Pre-transaction risk-prevention layer for Indian property registration. LandGuard reads deed bundles, flags registrability problems and ownership-history advisories with page-level evidence, and records every Sub-Registrar decision in a tamper-evident log. **It never certifies title.**

Built for the Cline AI Builder Hackathon (Round 2).

> Status: planning complete, implementation starting. Sections marked *(TODO)* are filled as we build.

## Problem

India registers deeds, not title. Registration records that a document was presented and executed, not that the seller owns the property, and registering officers can't decide title. Risk signals (a broken ownership chain, a second sale of the same parcel, an area that doesn't add up) sit buried in scanned deeds in several languages, so preventable disputes happen and there is no record of what was visible at registration.

## Solution

One core engine, two faces:

1. **Core engine:** deed bundle (PDF/image) → structured extraction → deterministic rules → evidence-linked flags.
2. **Sub-Registrar console (B2G):** review flags, record a disposition per flag, sign; the decision goes into a hash-chained, signed log.
3. **Citizen portal (B2C):** registrability pre-flight, evidence-gap map, "ask your seller" checklist. Never says "clean".

Full details: [LandGuard_AI_Concept.md](LandGuard_AI_Concept.md). Plan and contracts: [LandGuard_AI_Ideation_and_4hr_Execution_Plan.md](LandGuard_AI_Ideation_and_4hr_Execution_Plan.md).

## Architecture

```text
Upload ─► hash ─► preprocess ─► redact Aadhaar ─► vision-LLM extraction
      ─► validate + cross-check ─► per-field status (extracted | absent | unreadable)
                                          │
                       unreadable ─► Cline SDK review agent ─► human review
                                          │
      ─► rules engine (Class A / B, deterministic) ─► flags + evidence
      ─► disposition ─► signed, hash-chained decision log
```

Design rule: **the LLM only extracts; deterministic code decides.**

## Tech stack *(subject to the kickoff API check)*

- Python, Streamlit, SQLite/JSON files
- Vision LLM / Indic OCR for extraction (provider TBD), cached outputs for demo reliability
- `hashlib`, Ed25519 (`cryptography`/PyNaCl), `hmac` for the decision log
- Node.js 22+ and `@cline/sdk` for the in-product review agent
- `reportlab`/`fpdf2` + Pillow for synthetic deeds

## How Cline is used

**In the build:** the repo was built with Cline from the first commit: scaffolding, schema validator, rules-engine tests, synthetic data scripts. *(TODO: add task-history notes and screenshots; list places Cline got things wrong and how we fixed them.)*

**Inside the product:** a Cline SDK agent reviews fields the extractor marked `unreadable`. It can re-read the page and propose a value with a quoted snippet, or confirm the field is unreadable. It cannot run rules, create flags or touch the log, and the pipeline works with it switched off.

## Setup *(TODO)*

```text
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cd cline_agent && npm install      # Node 22+
streamlit run app/main.py
```

## Honest limitations

- Synthetic data: results show the pipeline logic works, not real-world OCR robustness.
- Languages tested: English and Hindi (typed, digital and scanned). **Assamese was not tested** (no native reader on the team and no sample available); Tesseract's Assamese pack is installed and the Bengali-Assamese digits are normalised, but accuracy there is unmeasured. Handwriting is read by the vision model alone.
- A deed-only view can't see inheritance, mutations or litigation, so we report coverage gaps, not verdicts.
- Double-sale detection needs registry-side access; the MVP simulates the index.
- Draft Registration Bill 2025 statements are presented as draft.

## Repo layout *(planned)*

`data/` · `extract/` · `rules/` · `ledger/` · `app/` · `eval/` · `cline_agent/` · `deck/`

## Deliverables checklist

- [ ] Public repo + README
- [ ] PPT
- [ ] Demo video (real user scenario + Cline in the build)
- [ ] Social post tagging Cline
