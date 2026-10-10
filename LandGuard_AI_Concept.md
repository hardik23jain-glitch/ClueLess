# LandGuard AI: Concept Document

**One-line pitch:** LandGuard AI is a pre-transaction risk-prevention layer for Indian property registration. It reads deed bundles, flags registrability problems and ownership-history advisories with page-level evidence, and records every Sub-Registrar decision in a tamper-evident log. It never certifies title.

---

## 1. Problem

- India registers **deeds**, not **title**. Registration records that a document was presented and executed; it doesn't guarantee the seller owns the property.
- Registering officers can't decide questions of title. The draft Registration Bill 2025 says so explicitly, and courts have repeatedly held that refusal can't rest on title disputes.
- Risk signals (a broken ownership chain, a second sale of the same parcel, an area that doesn't add up) sit buried in scanned historical deeds in several languages. Officers and buyers rarely have the time or tooling to read them across a whole chain.
- Result: preventable disputes, and no structured record of what risks were visible at the moment of registration.

## 2. Solution

A decision-support engine with two faces on one core:

1. **Core engine:** deed bundle (PDF/image) → structured extraction → deterministic rules → evidence-linked flags.
2. **B2G console (Sub-Registrar):** reviews flags, records a disposition for each, signs; the decision is written to a tamper-evident log.
3. **B2C portal (citizens):** a preparation and understanding tool: registrability pre-flight, evidence-gap map, and a "what to ask for next" list.

**Design principle:** *show what the documents support, what they contradict, and what nobody has checked, and never say "clean".*

## 3. Positioning

| Layer | Existing | LandGuard's role |
|---|---|---|
| System of record | DILRMP / land stack, ULPIN (Bhu-Aadhaar) | Consumes it via API (mocked in the MVP) |
| Procedural compliance | NGDRS: stamp duty, e-KYC, workflow | Adds an intelligence layer on top; doesn't replace it |
| Post-facto due diligence | Lawyers, bank title searches, data vendors | We're earlier in the flow: at presentation and during buyer preparation |

DILRMP 3.0 (launched 10 Sept 2026, ₹565.5 crore for 2026-31) is building a GIS-based land stack with API-linked state systems. LandGuard is the intelligence layer that sits on top of it, not a competitor to it.

## 4. Users

| User | Need | What they get |
|---|---|---|
| **Sub-Registrar (B2G)** | Spot registrability issues; record why a decision was taken | Class A / Class B flags, per-flag dispositions, signed decision record |
| **Inspector General / oversight** | Consistent, auditable decisions | Verifiable log; structured recorded reasons for refusals and appeals |
| **Buyer (B2C)** | Know what's missing before paying | Pre-flight check, evidence-gap map, request list for the seller, advocate hand-off brief |
| **Existing owner (B2C)** | Keep records consistent before a future sale | Cross-document consistency check *(stretch)* |

## 5. Core engine

### 5.1 Pipeline

`Upload bundle → OCR/vision extraction → schema validation + confidence → rules engine (vs. mock registry index) → flags with evidence → disposition → signed log entry`

### 5.2 Extraction

- A vision-capable LLM or Indic OCR service converts each deed into JSON: document type, registration status, dates, parties, POA reference, property details (ULPIN/survey number, area, four boundaries), parent-deed reference, consideration, language. Aadhaar numbers are redacted before any external call.
- Every field carries a **status** (`extracted`, `absent`, `unreadable`), a **confidence score** and an **evidence pointer** (page plus a quoted snippet; a region box when available).
- **Absent** (readable, genuinely not stated) feeds the Class A rules; **unreadable** (can't be read reliably) makes the system **abstain** ("needs human review") instead of guessing. The two are never merged.
- Confidence comes from schema validity, cross-check agreement and a threshold calibrated on the eval set, not from the LLM's self-reported score.
- **Cline inside the product:** a Cline SDK review agent re-reads the evidence page for `unreadable` fields and proposes a value with a quoted snippet, or confirms it is unreadable. It cannot run rules, create flags or touch the log.
- The LLM only extracts. The reasoning below is **deterministic code**, so every flag is explainable and reproducible.

### 5.3 Rules engine

**Class A: Registrability.** These map to objective refusal grounds the officer can legitimately act on.

| ID | Check |
|---|---|
| A1 | Property description complete: area, unit, four boundaries, survey number |
| A2 | ULPIN / survey number consistent with parent deed |
| A3 | Seller acting through POA, so a registered POA reference must be present (draft Bill s.12(1)(g)) |
| A4 | Presentation within the allowed window after execution (draft Bill: 4 months) |
| A5 | Party identity fields present (names, relation names, ID type; never ID numbers) |
| A6 | Consideration / stamp fields present |

**Class B: Title-intelligence advisories.** Not refusal grounds; the officer records a disposition.

| ID | Check |
|---|---|
| B1 | Seller isn't the latest recorded buyer, and no explaining instrument (succession, decree, partition) is in the bundle |
| B2 | Possible double sale: the mock registry index shows another conveyance of the parcel after the seller acquired it |
| B3 | Area conservation: subdivided parts exceed the parent |
| B4 | Boundary mismatch against the parent deed |
| B5 | Date-order anomalies |
| B6 | Possible same-person name mismatch across transliterations (fuzzy match, "confirm") |
| B7 | An unregistered instrument (agreement to sell, GPA, will) sits in the chain: reported as "not a registered conveyance" |
| B8 | Mock index shows an encumbrance (e.g. mortgage) |

**Decoy handling:** a chain gap explained by a succession document in the bundle must resolve to *Supported*, not a flag. This demonstrates the system doesn't over-flag legitimate non-deed transfers.

## 6. B2G: LandGuard Decision Record

A signed, hash-chained, append-only log of Sub-Registrar decisions. It is a **tamper-evident decision record**, not a disciplinary tool.

**Each entry binds:**
- SHA-256 of the original document bundle (sorted file hashes)
- Hash of the extracted JSON
- Ruleset version and model version (reproducibility)
- The resolved checklist state
- Per-flag dispositions with reasons
- A reference to the officer's digital signature (held by the department)
- Salted HMAC commitments for party names (no personal data in the immutable log)
- Previous entry hash, timestamp, and an Ed25519 signature

**Disposition codes:** `ACK_PROCEED`, `PARTIES_INFORMED`, `REFER_REVENUE_AUTHORITY`, `RETURN_FOR_CORRECTION`, `REFUSE_RECORDED_GROUND` (Class A only; requires a ground reference).

**What it does and doesn't prove**
- It proves what the system produced, what the officer acknowledged, and that the record has not been altered.
- It does **not** prove fault. For Class B advisories the officer has no power to refuse on title grounds, so proceeding may be correct.
- It supports **recorded reasons for refusal and appeals**: structured Class A findings give objective, defensible reasons.
- It protects honest officers: there is a verifiable record of what they were shown and what they decided.

**Demo hook:** edit one log entry and the chain verification fails visibly.

**Privacy posture:** no Aadhaar or biometric data stored; identity is consumed from the department's e-sign result, not performed by LandGuard; personal data stays out of the immutable log (commitments only); documents sit in a deletable store.

## 7. B2C: citizen portal

**Safety rules (non-negotiable)**
- Three evidence states only: **Supported by documents you uploaded**, **Contradiction between uploaded documents**, **No evidence provided**.
- Never use "clean", "safe", "verified title", or a numeric title score.
- A persistent **"What we did not check"** panel: encumbrance certificate, mutation/revenue records, litigation, succession, third-party deeds, prohibited-property lists.
- Every finding cites page and region. Legal explanations come from a curated static library, not free LLM text.
- Document analysis and question lists only, plus an "Ask an advocate" referral.
- Auto-redact Aadhaar numbers on upload; explicit consent; process-and-delete by default.

**Features**
1. **NGDRS pre-flight:** Class A checks on the draft deed → "ready to present" or "fix these N things".
2. **Evidence-gap map + "Ask your seller" checklist + advocate hand-off brief.**
3. **Deed translator / clause explainer** (Hindi, Assamese, Marathi to plain English). *Stretch.*
4. **Owner record-hygiene check** and optional submission receipt linking the bundle hash to the log entry. *Stretch / slide.*

**Hero screen:** "No contradictions found among uploaded documents. Five categories not checked."

## 8. Legal and regulatory design

- **Registration Bill 2025 (draft)** aligns on: electronic presentation, e-registration certificates and digital records; objective refusal grounds (denial of execution, late presentation, inadequate property description); recorded reasons for refusal; appeal to the Registrar; compulsory registration of transfer POAs; and the explicit statement that registering officers don't decide title.
- Class A / Class B split exists specifically so the product never pushes an officer to refuse on title grounds.
- An unregistered instrument generally doesn't convey title (TPA s.54; *Suraj Lamp* line of cases), so such documents are reported as *not a registered conveyance*, not as a conflicting deed. **[Verify with a law-literate reviewer.]**
- The product is positioned as document analysis plus question lists, not a title opinion. **[Verify with counsel.]**
- All draft-Bill statements should be presented as *draft* unless enactment is confirmed.

## 9. Hackathon MVP scope

**In scope**
- ~20 synthetic documents across 8 parcels with planted defects and a benign decoy; Hindi and Assamese examples included.
- Extraction → rules (A1-A6, B1-B4 at minimum) → flags with evidence.
- SRO console with dispositions and signing; hash-chained signed log with tamper-detection demo.
- Citizen pre-flight and evidence-gap map with the "What we did not check" panel.
- Measured results: extraction accuracy on clean vs degraded documents; rule precision and recall on planted defects.

**Mocked**
- Registry index (stand-in for NGDRS/land-stack APIs).
- Officer digital signature reference.

**Out of scope**
- Real registry integration, authentication, production database, Land Lock alerts, any title certification.

## 10. Honest limitations

- Synthetic data: results show the pipeline logic works, not real-world OCR robustness. Real Indian deeds (handwriting, stamps, folds, mixed scripts, regional formats) are harder, and vendor OCR benchmarks are not our accuracy.
- A deed-only chain can't see inheritance without documents, mutations, litigation, or deeds the uploader didn't include. This is why the product reports coverage gaps instead of verdicts.
- True double-sale detection needs registry-side index access; the MVP simulates it.
- Rules are Indian-law heuristics, not legal conclusions; state-specific rules and formats will need localisation.

## 11. Roadmap beyond the hackathon

1. Pilot with a single Sub-Registrar Office using a real or sandbox index feed.
2. State-specific rule packs (area units, document formats, prohibited-property lists).
3. Indic handwriting evaluation set built from consented real specimens.
4. Externally witnessed log roots (department or third-party).
5. Advocate-network referral for citizen hand-off.

## 12. Key talking points

- **"Intelligence layer on the land stack,"** not a replacement for it.
- **"We never say clean."** Three evidence states and an explicit coverage gap.
- **"Deterministic rules, LLM only extracts."** Explainable and reproducible.
- **"Tamper-evident decision record that protects honest officers."** Not a blame tool, and not a blockchain.
- **"Measured, honest accuracy"** with abstention instead of guesses.
