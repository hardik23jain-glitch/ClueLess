# ClueLess: Bhoomi Kaaval (भूमि காவல்)

*Bhoomi* (Sanskrit/Hindi: land) + *Kaaval* (Tamil: guard). The product was developed under the working name LandGuard AI, which still appears in some file names and code.

Pre-transaction risk-prevention layer for Indian property registration. Bhoomi Kaaval reads deed bundles, flags registrability problems and ownership-history advisories with page-level evidence, and records every Sub-Registrar decision in a tamper-evident, signed log. **It never certifies title.**

Built for the Cline AI Builder Hackathon (Round 2).

## Problem

India registers deeds, not title. Registration records that a document was presented and executed, not that the seller owns the property, and registering officers can't decide title. Risk signals (a broken ownership chain, a second sale of the same parcel, an area that doesn't add up) sit buried in scanned deeds in several languages, so preventable disputes happen and there is no record of what was visible at registration.

## Solution

One core engine, two faces:

1. **Core engine:** deed bundle (PDF/image) → structured extraction → deterministic rules → evidence-linked flags.
2. **Sub-Registrar console (B2G):** review flags, record a disposition per flag, sign; the decision goes into a hash-chained, Ed25519-signed log.
3. **Citizen portal (B2C):** registrability pre-flight, evidence-gap map, "ask your seller" checklist and an advocate hand-off brief. Never says "clean".

Design rules: **the LLM only extracts; deterministic code decides.** Legal wording comes from a fixed library, never from free LLM text. Three evidence states only (supported / contradicted / not provided) and an always-visible "what we did not check" list.

More: [LandGuard_AI_Concept.md](LandGuard_AI_Concept.md) · [plan and contracts](LandGuard_AI_Ideation_and_4hr_Execution_Plan.md) · [integration guide](docs/INTEGRATION.md)

## Architecture

```text
Upload (PDF / scan / photo)
  ─► hash original file ─► preprocess (orient, deskew, quality gate)
  ─► local text (PDF text layer or Tesseract)  ─► redact Aadhaar / PAN before anything leaves the machine
  ─► vision LLM reads page images ─► per-field {value, status, confidence, quote, page}
  ─► classify: extracted | absent | unreadable   (confidence = 40% model + 30% format + 30% "quote found on page")
        └─ unreadable ─► Cline SDK review agent (proposes only) ─► human review
  ─► extract/to_rules.py  (unreadable never becomes a flag; parent deeds linked; evidence attached)
  ─► rules engine: Class A registrability + Class B advisories (deterministic, no LLM)
  ─► officer dispositions (validated) ─► signed, hash-chained ledger entry
```

- **Extraction (`extract/`)** produces contract v1.1 JSON. The key distinction is `absent` (readable, genuinely not stated, so Class A rules may fire) versus `unreadable` (unknown; the rules never flag it, a human reviews it).
- **Rules (`rules/engine.py`)** are Class A (objective registrability: POA registration, area, boundaries, presentation window, party names, consideration, ULPIN vs parent) and Class B (advisories: registry cross-check, broken link, possible double sale, area conservation).
- **Ledger (`ledger/`)** is a SHA-256 hash chain in SQLite with Ed25519 signatures per entry and salted-HMAC party commitments (no names in the immutable log). Editing any entry makes verification fail.

## Tech stack

- Python 3.13, pydantic, OpenCV, PyMuPDF, Pillow, `cryptography`, SQLite
- **Vision LLM:** Gemini (`gemini-flash-latest`) behind a one-function provider interface (`extract/providers.py`); Claude is also supported. Swapping to a self-hosted model is a config change.
- **Local reader:** Tesseract 5 (`eng`, `hin`, `asm`, `mar`) and the PDF text layer, used as an independent cross-check and for redaction, not as the main extractor
- **Cline SDK** (`@cline/sdk`, Node 22+) for the in-product review agent
- Streamlit UI (P3), SQLite ledger (P2)

## How Cline was used

**In the build.** Cline (ClinePass, in VS Code) was used on these changes: (1) closing a prompt gap so the extractor must return an object for every field, with a version bump and a test that an omitted field becomes `unreadable` and never `absent`; (2) the `tests/test_request_list.py` suite for the "Ask your seller" list; (3) the "How Cline was used" write-up. *(Add the commit hashes of the Cline-made commits here.)*

The first version of the extraction pipeline, the rules bridge, the signed ledger entries and the Hindi/handwriting test documents were written with a separate AI coding assistant (Claude Code) in earlier sessions, and then tested and reviewed by the team. We state this plainly so the commit history matches the description: it shows what each tool contributed rather than attributing all of it to Cline.

**Inside the product.** A Cline SDK agent reviews the fields the extractor marked `unreadable` (`cline_agent/review_agent.mjs`, Node 22+, `@cline/sdk`). Python (`extract/review.py`) hands it the redacted page text and the low-confidence candidates, then calls `node review_agent.mjs <job.json>`. The agent exposes four tools (`get_field`, `read_page_text`, `validate_field`, `propose_correction`) and by design has **no** tool that runs rules, creates flags, or touches the ledger. It can only propose a value with a verbatim quote; Python re-validates every proposal (format check plus the quote must be found on the page by the local reader) before it is accepted, otherwise the field stays `unreadable` for a human. If Node, the SDK, or a key is missing the review is skipped and recorded as such, so the pipeline runs unchanged with the agent switched off. On our test documents it recovered 0 of the few fields it was given: it is deliberately conservative.

## Setup (Windows)

```powershell
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
```

1. **Tesseract:** install the UB Mannheim build and tick the Hindi, Assamese, Marathi and OSD language packs. If it isn't on PATH the code finds it in `C:\Program Files\Tesseract-OCR`, or set `TESSERACT_CMD`.
2. **Node 22+** (only for the Cline review agent): `cd cline_agent ; npm install ; cd ..` (open a fresh terminal so `node` is on PATH).
3. **Keys:** copy `.env.example` to `.env` and set `GEMINI_API_KEY` (a free key allows only about 20 requests per day per model, so results are cached). Set `LANDGUARD_CLINE_REVIEW=1` and `LANDGUARD_CLINE_API_KEY` to enable the review agent. Never commit `.env`.
4. **Use synthetic documents only.** Images are sent to the model provider.

```powershell
python -m extract.run data\raw\SAMPLE-1.pdf      # extract one deed -> data\extracted\SAMPLE-1.json
python -m scripts.show_extraction SAMPLE-1       # readable summary
python -m scripts.demo_flow                      # extraction -> rules -> brief -> signed ledger -> tamper test
python -m pytest tests -q                        # 75 offline tests (no network, Tesseract or Node needed)
python -m eval.eval_extraction                   # accuracy report against data/labels
```

Run the app (works offline from the cached sample extractions in `data/extracted/`):

```powershell
streamlit run app/main.py        # Citizen pre-flight · Sub-Registrar console · Ledger verify
python -m eval.eval_rules        # rule precision/recall on the planted-defect dataset (synthetic)
```

The app calls `integration.run_risk_analysis` and `integration.commit_to_ledger`. See [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Results (synthetic data, so read with care)

Measured on 8 documents / 161 labelled fields (prompt v1.1-5): clean and degraded English scans, a Hindi deed (digital and scanned, Devanagari digits) and a handwriting-style deed.

| Slice | Fields | Accuracy on accepted fields | Abstained (sent to review) |
|---|---|---|---|
| English | 115 | 99.0% | 1.7% |
| Hindi | 46 | 100% | 2.2% |
| Handwriting-style | 23 | 100% | 0% |
| **All** | **161** | **99.3%** | **1.9%** |

One wrong value was accepted (a heavily blurred "Rina Bora" read as "Boro"). Absent-field precision was 100%, but from only a few absent fields per document.

## Honest limitations

- **Synthetic data, one model.** I generated and labelled these documents myself. They show the pipeline logic works, not real-world OCR robustness; vendor benchmarks show vision models degrade on real Indic scans.
- **Languages:** English and Hindi tested (typed, digital and scanned). **Assamese was not tested** (no native reader on the team and no sample available); the Tesseract pack and digit handling are in place but accuracy is unmeasured.
- **Handwriting** is read by the vision model alone, and the test deed used a handwriting *font*, which is far more regular than real handwriting.
- **Privacy:** printed and scanned Aadhaar/PAN numbers are masked before any image is sent, but **handwritten ID numbers cannot be detected**, so they may reach the model provider. The pipeline warns when a document is handwritten. Production would use a self-hosted model so images never leave the department.
- A deed-only view can't see inheritance, mutations or litigation, so we report coverage gaps, never verdicts.
- Double-sale detection needs registry-side access; the MVP uses a simulated registry index (14-character ULPINs, short codes aliased).
- Name matching is exact (lower-cased); transliteration matching across scripts is future work.
- Rules are Indian-law heuristics, not legal conclusions. Draft Registration Bill 2025 statements are presented as draft and need counsel review.

## Repo layout

| Path | What |
|---|---|
| `extract/` | Extraction pipeline, schema (contract v1.1), redaction, review agent glue, bridge to the rules (`to_rules.py`) |
| `rules/` | Deterministic rules engine and the static-library advocate brief |
| `ledger/` | Mock registry, hash-chained audit log, Ed25519 signing |
| `integration.py` | API for the Streamlit app |
| `cline_agent/` | Cline SDK review agent (Node) |
| `eval/`, `data/labels/` | Accuracy report and ground-truth labels |
| `data/raw/`, `data/extracted/` | Synthetic sample documents and their cached extraction JSON |
| `scripts/` | Sample generators (English, scans, Hindi, handwriting-style) and diagnostics |
| `app/` | Streamlit app (citizen pre-flight, officer console, ledger verify) |
| `tests/` | 75 offline tests |

## Deliverables checklist

- [ ] Public repo + README (make the repository public before the deadline)
- [ ] PPT
- [ ] Demo video (real user scenario + Cline in the build)
- [ ] Social post tagging Cline
