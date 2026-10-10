# LandGuard AI: Ideation Record and 4-Hour Execution Plan

**Team size:** 3 | **Time left:** ~4 hours | **Goal:** a working, demo-able MVP plus a bulletproof pitch

> Status caveats: the Registration Bill 2025 was still a **draft** in every source I found. TEAL India / Prava AI claims were **not verified**. Items marked **[VERIFY]** must be checked before you say them on stage.

---

## PART A: IDEATION RECORD

### A1. Original idea (v1)

AI-assisted pre-registration title-risk screening. An LLM + OCR pipeline parses scanned deeds, extracts entities (buyer, seller, plot dimensions, boundaries), and plots a chronological DAG to find missing links and boundary mismatches.

Users in v1: Sub-Registrars (B2G) and citizens (B2C "Title Health" check + "Land Lock" alerts on ULPIN).

### A2. Review findings on v1 (what was wrong)

| Issue | Why it matters |
|---|---|
| **Input-bias loophole** | The tool only sees what the uploader gives it. A fraudulent seller uploads a clean bundle. Double sales are only visible in the registry index. A green "Title Health" result creates false assurance and liability. |
| **"No data lake" defense backfires** | Govt direction is linked, API-accessible land records. The data link is the moat, so plug into it instead of claiming to avoid it. |
| **Muddled example** | An "unregistered 2012 deed contradicting a 1998 deed" is legally off: an unregistered sale deed generally doesn't convey title (TPA s.54; *Suraj Lamp* line of cases) **[VERIFY with law-literate teammate]**. It's a defective instrument, not a competing conveyance. |
| **Missing-link false alarms** | Inheritance, partition, wills, gifts and decrees often need no registered deed, so a deed-only DAG over-flags. |
| **Land Lock** | Needs a pending-deed feed you don't have, raises DPDP questions, and a public "pending deed" signal could itself cloud a title. |
| **Synthetic data circularity** | You wrote both the data and the detector, so accuracy numbers prove little. |

### A3. Market and regulatory facts (as of 10 Oct 2026)

- **DILRMP 3.0** guidelines launched 10 Sept 2026: ₹565.50 crore for 2026-31, GIS-based "land stack", states link databases via APIs, Bhu-Aadhaar (ULPIN) for every parcel, 75 high-footfall Sub-Registrar Offices upgraded into Registration Seva Kendras, NAKSHA urban mapping.
- Govt says earlier phases digitised ~99.9% of records of rights and ~97% of cadastral maps. Treat as government-reported.
- ULPIN rollout has been uneven: a 2024 report said only ~30% of rural parcels had it, with some states lagging. The figure is dated.
- **Draft Registration Bill 2025** would replace the 1908 Act: online presentation, e-registration certificates, digital records, **s.12(1)(g) compulsory registration of POAs authorising immovable-property transfer**, **s.58 objective refusal grounds** (denial of execution, late presentation, inadequate property description, etc.), recorded reasons for refusal (old s.71 → s.59), appeal to Registrar within 30 days, a proposed 4-month window to register after signing.
- **Critical:** the draft clarifies registering officers can't decide questions of title. Courts have repeatedly said refusal can't rest on title disputes.
- **OCR reality:** Sarvam Vision 2.1 (24 Sept 2026) claims Indic handwriting and structured extraction; benchmarks are vendor-reported, and stylised handwriting and low-resource languages degrade. Do not claim real-world robustness; show measured evidence.

### A4. Pivoted product (v2)

**LandGuard AI = pre-transaction risk-prevention intelligence layer on top of NGDRS/DILRMP-style land stacks.** It never certifies title.

**B2G: LandGuard Decision Record (formerly "Verified Transfer Ledger")**
- Hash-chained, signed, append-only decision log for Sub-Registrar approvals.
- Binds the bundle hash, extraction hash, ruleset and model version, risk-checklist state and the officer's per-flag dispositions to each registration event.

**B2C: citizen portal (four features, below).**

### A5. Review of the ledger

**What the ledger does NOT prove**
- "Officer was warned" is not "officer is at fault." The officer can't refuse on title grounds, so proceeding may be correct. Don't pitch it as incriminating officers.
- A hash of the checklist proves what the system produced, not what the officer read. Record the rendered view, per-flag acknowledgement and a disposition with a reason.

**Fix: split flags into two classes**

| Class | Meaning | Officer action |
|---|---|---|
| **A: Registrability** | Maps to objective refusal grounds | May refuse with recorded reasons |
| **B: Title-intelligence advisory** | Double sale, missing link, etc. Not a refusal ground | Records disposition, informs parties, refers |

**Design corrections**
- Bind **reproducibility inputs**: file hashes, extracted JSON hash, ruleset version, model version.
- Use a **signed, hash-chained log with published roots** (Certificate-Transparency style). Say "tamper-evident log", not "blockchain".
- **"Zero-knowledge" is overclaimed.** What you described is tokenisation. Say "pseudonymised, no Aadhaar stored".
- Record the officer's **digital signature / eSign reference** (held by the department), not "Chair 02" alone.
- Keep personal data **out** of the immutable log: use salted HMAC commitments, store documents in a deletable store (immutability vs correction/erasure).
- Likely only authorised entities can run Aadhaar authentication, so consume the department's result instead of performing it **[VERIFY]**.
- Pitch as protecting honest officers and giving the Inspector General oversight, and as supporting recorded reasons on appeal.

### A6. B2C features

**Safety rules for all of them**
- Use three evidence states only: **Supported by documents you uploaded** / **Contradiction between uploaded documents** / **No evidence provided**.
- Never use the words "clean", "safe", "verified title", or a numeric title score.
- Always show a **"What we did not check"** panel: encumbrance certificate, mutation/revenue records, litigation, succession, third-party deeds, prohibited-property lists.
- Every finding cites page + region. Legal explanations come from a curated static library, not free LLM text.
- Advocate boundary: document analysis and question lists, plus an "Ask an advocate" referral **[VERIFY with counsel]**.
- DPDP posture: auto-redact Aadhaar numbers on upload, explicit consent, process-and-delete by default.

**Features**
1. **NGDRS pre-flight (registrability check)**: Class A checks on the draft deed; "ready to present" / "fix these N things".
2. **Evidence gap map + "Ask your seller" checklist + advocate handoff brief**.
3. **Deed translator / clause explainer** (Hindi, Assamese, Marathi to plain English). *Stretch.*
4. **Owner record-hygiene check**: cross-document consistency for existing owners, plus an optional submission receipt linking the bundle hash to the ledger entry. *Slide only unless time allows.*

Drop Land Lock unless an official notification feed exists.

### A7. Judge Q&A cheat sheet

| Attack | Answer |
|---|---|
| "Can't a seller upload a clean bundle?" | Yes, so we never output "clean". The B2C tool shows coverage gaps and a request list. The B2G console cross-checks the registry index, where double sales are visible. |
| "Is this legal, given SROs can't decide title?" | Class A flags map to objective grounds. Class B are advisories with recorded dispositions, never refusal grounds. |
| "Does it work on real deeds?" | Here is measured accuracy on degraded and real specimen pages, with abstention below a confidence threshold. We don't claim more. |
| "Why not just buy from TEAL/Prava?" | **[VERIFY their current products first]** We're a different layer: registrar-side decision support plus citizen prep, integrating with whatever data the land stack provides. |
| "Is the ledger a blockchain gimmick?" | No. It's a signed hash-chain with externally witnessed roots, and you can see tampering fail live. |
| "Privacy?" | No Aadhaar stored, personal data kept out of the log (salted commitments), citizen documents processed then deleted. |
| "Your accuracy numbers?" | Planted defects were written by a teammate who didn't build the detector, with decoys. We report precision and recall, and say it's synthetic. |

---

## PART B: 4-HOUR EXECUTION PLAN (TEAM OF 3)

### B1. Scope decisions (don't relitigate these)

**MUST (demo can't exist without)**
1. Extraction pipeline: deed PDF/image → structured JSON.
2. Rules engine: Class A + Class B checks against a mock registry index.
3. Sub-Registrar console: flags, per-flag acknowledgement and disposition, signing into the log.
4. Hash-chained signed log with a **tamper-detection demo**.
5. Citizen pre-flight + evidence gap map with the "What we did not check" panel.
6. Pitch deck (5 min) + rehearsed demo.

**SHOULD:** accuracy table (extraction on clean vs degraded; rule precision/recall on planted defects), Hindi and Assamese examples.

**COULD (only if ahead of schedule):** translator, owner hygiene, advocate-brief PDF.

**CLINE (hackathon scoring; see B12):**
- MUST: build the repo with Cline from the first commit, keeping visible evidence (commit trail, task history, recorded demo footage).
- MUST: the four hackathon deliverables (public repo + README, PPT, demo video showing Cline in the build, social post tagging Cline).
- SHOULD (bonus points): Cline SDK **inside the product** as the extraction-review agent (B12.2).

**CUT:** Land Lock, real registry integration, auth/login, database beyond SQLite/JSON files, fancy UI.

**Data:** use **~20 synthetic documents across 8 parcels** (not 30-50: you can't label and test that many in 4 hours). Quality of planted defects beats quantity.

### B2. Stack (fastest path for 3 people)

- **Python everywhere.** **Streamlit** UI (one repo, no frontend build). **SQLite or JSON files** for the mock index and log.
- **Extraction:** a vision-capable LLM or Indic OCR API with a JSON schema prompt. Check **now** which API key and quota you have. Candidates: Sarvam Vision, Gemini, Claude vision. Add **cached extraction JSON per document** as a demo fallback so a network failure can't kill the demo.
- **Cline SDK sidecar:** `@cline/sdk` is TypeScript (Node.js 22+), so it runs as a small Node service/CLI called from Python (subprocess or localhost HTTP). Python stays the system of record. **[VERIFY]** package name, install and API against docs.cline.bot/sdk/overview before building on it; there is also a separate ACP-based `cline` package, so confirm which one you need.
- **Crypto:** `hashlib` (SHA-256), `cryptography` or `PyNaCl` (Ed25519), `hmac` for salted commitments.
- **Synthetic data:** Python script with templates, `reportlab` or `fpdf2` for PDFs (Noto Sans Devanagari and Noto Sans Bengali fonts; Assamese uses the Bengali-Assamese script), Pillow for degradation (blur, rotation, noise, stamp overlay).

### B3. Roles

| Person | Role | Owns |
|---|---|---|
| **P1** | AI / Extraction | OCR/LLM extraction (B11 pipeline), JSON schema v1.1, per-field confidence + abstention, Aadhaar redaction, extraction cache, accuracy eval, Cline SDK review agent (B12.2) |
| **P2** | Backend: Rules + Log | Rules engine (A1-A6, B1-B8), mock registry index, hash-chained signed log, verify/tamper function |
| **P3** | Frontend + Data + Pitch | Streamlit app, synthetic data generator, planted-defect labels, deck, demo script |

P3 has the heaviest load. P1 supports P3 on data generation after the extraction MVP works (see timeline).

### B4. Shared contract (write this in the first 20 minutes and don't change it)

> **Contract v1.1** (revised before any code exists). Changes from v1: per-field `status` separates *absent* from *unreadable* (so Class A rules can fire); evidence is page + quoted snippet with a best-effort bbox; provenance fields feed the ledger; cross-check agreement feeds confidence.

**Extracted deed JSON (per document).** Every leaf field under `fields` is a *field object*, not a bare value:

```json
{
  "doc_id": "P2-D3",
  "provenance": {
    "file_sha256": "hex",
    "pages": 3,
    "extraction_method": "vision_llm | ocr+llm | cached | human_corrected",
    "model_version": "string",
    "extracted_at": "ISO-8601"
  },
  "fields": {
    "doc_type": {"value": "sale_deed", "status": "extracted", "confidence": 0.97,
                 "evidence": {"page": 1, "quote": "SALE DEED", "bbox": null}},
    "seller.name": {"value": "Ramesh Kumar", "status": "extracted", "confidence": 0.93,
                    "evidence": {"page": 1, "quote": "Ramesh Kumar s/o ...", "bbox": [0,0,0,0]}},
    "acting_through_poa.poa_reg_no": {"value": null, "status": "absent", "confidence": 0.9,
                    "evidence": {"page": 1, "quote": "acting through his attorney ...", "bbox": null}},
    "property.boundaries.N": {"value": null, "status": "unreadable", "confidence": 0.3,
                    "evidence": {"page": 2, "quote": null, "bbox": null}}
  },
  "needs_review": ["property.boundaries.N"],
  "language": "en|hi|as|mr",
  "overall_confidence": 0.0
}
```

**Field keys (all required to be *present* as keys; values may be null):**
`doc_type` (`sale_deed | agreement_to_sell | poa | will | gift | partition | succession | other`), `registered`, `registration_no`, `execution_date`, `presentation_date` (`YYYY-MM-DD`), `seller.name`, `seller.relation_name`, `buyer.name`, `buyer.relation_name`, `party.id_type` (type only, never ID numbers), `acting_through_poa.is_attorney` (bool; added so rule A3 can tell "signs personally" from "attorney with no POA number"), `acting_through_poa.poa_reg_no`, `property.ulpin`, `property.survey_no`, `property.area_value`, `property.area_unit` (`sqft|katha|bigha|...`), `property.boundaries.{N,E,S,W}`, `parent_ref.doc_ref`, `parent_ref.claimed_acquisition_year`, `consideration`, `stamp_duty`.

**Field `status` semantics (the rule that makes Class A work):**

| status | Meaning | Rules engine does |
|---|---|---|
| `extracted` | Read with confidence ≥ threshold | Uses the value |
| `absent` | Document is readable here and the thing is genuinely not stated (e.g. no POA reference) | Treats as missing → Class A flag (A1, A3, A5, A6) |
| `unreadable` | Field likely exists but can't be read reliably (smudge, low-res, handwriting) | Treats as **unknown**: no flag, shown as "needs human review" |

Never collapse `absent` and `unreadable` into one "low confidence" bucket.

Implementation notes (see `extract/schema.py`, the source of truth): each field also carries `source` (`vision_llm | cline_review | human_corrected`), `notes`, and, for `unreadable` fields only, a `candidate` value (a hint for humans and the review agent; the rules engine must ignore it). `value` is set only when `status == extracted`. `provenance` additionally holds `redaction`, `quality`, `local_text`, `review`, `warnings` and `extraction_hash`.

**Flag object (from rules engine):**
```json
{
  "flag_id": "B2",
  "class": "A|B",
  "title": "Possible double sale",
  "explanation": "plain language",
  "evidence": [{"doc_id": "...", "page": 1, "bbox": [0,0,0,0]}],
  "status": "open|acknowledged"
}
```

**Disposition codes:** `ACK_PROCEED`, `PARTIES_INFORMED`, `REFER_REVENUE_AUTHORITY`, `RETURN_FOR_CORRECTION`, `REFUSE_RECORDED_GROUND` (Class A only, requires a ground reference).

### B5. Rules to implement

**Class A: Registrability (map to objective refusal grounds)**
- **A1** Property description completeness: area, unit, four boundaries, survey number.
- **A2** ULPIN/survey number consistent with the parent deed.
- **A3** Seller acts through POA, so a registered POA reference must be present (draft s.12(1)(g)).
- **A4** Presentation vs execution date within the window (draft: 4 months; mark as **draft**).
- **A5** Party identity fields present (name, relation name, ID type, never ID numbers).
- **A6** Consideration/stamp fields present.

**Class B: Advisories (not refusal grounds)**
- **B1** Seller is not the latest recorded buyer (broken link) *and* no explaining instrument (inheritance, decree, partition) is in the bundle.
- **B2** Double sale: the mock registry index shows another conveyance of the same parcel after the seller acquired it.
- **B3** Area conservation: subdivided parts sum to more than the parent.
- **B4** Boundary mismatch against the parent deed.
- **B5** Date-order anomalies.
- **B6** Party-name mismatch using fuzzy match across transliterations. Flag as "possible same person, confirm".
- **B7** An unregistered instrument (agreement to sell/GPA/will) sits in the chain: say "not a registered conveyance", never "conflicting deed".
- **B8** The mock index shows an encumbrance (e.g. mortgage).

**Rules-engine handling of field status (contract v1.1):** a rule reads `absent` as missing (Class A fires) and `unreadable` as unknown (no flag; surface "needs human review" in the UI). A flag never rests on an `unreadable` field.

**Decoy that must produce "supported", not a flag:** a chain gap explained by a legal-heir/succession document in the bundle.

### B6. Synthetic data set (P3 + P1)

| Parcel | Content | Expected output |
|---|---|---|
| P1 | Clean 3-deed chain | No flags, but the coverage panel still shows |
| P2 | Seller claims 2018 acquisition, no transfer to them | B1 |
| P3 | Same parcel sold twice (second deed in index) | B2 |
| P4 | Subdivision exceeds the parent area | B3 |
| P5 | Boundary differs from parent | B4 |
| P6 | Seller acts via unregistered POA | A3 |
| P7 | Gap explained by a succession document (decoy) | Supported, no B1 |
| P8 | Hindi deed (P1) and Assamese deed (P6 or P1) for OCR test | Extracted correctly or abstained |

Rules for fairness: **P2 (backend) or a teammate who didn't write the detector plants the defects blind**, with a one-page labels file written first and kept unchanged afterwards.

### B7. Hour-by-hour timeline (T = remaining time)

**T-4:00 → T-3:40 | Kickoff (all 3, 20 min)**
- Freeze scope (B1) and the JSON contract (B4). Create the repo and folders: `data/`, `extract/`, `rules/`, `ledger/`, `app/`, `eval/`, `deck/`.
- Check API keys and quota. Decide the extraction provider and the fallback.
- **Cline setup:** everyone installs Cline, first commit is made *through* Cline, and screen recording of the build starts (needed for the demo video). Smoke-test `@cline/sdk` (Node 22+) with a hello-world agent; if it fails in 15 minutes, fall back to B12.2's "Cline as build-only" plan.
- P3 writes the planted-defect labels file *before* any code.

**T-3:40 → T-2:30 | Parallel build (70 min)**
- **P1:** build the B11 pipeline on 3 sample docs: `extract(path) -> JSON` (contract v1.1) with per-field status/confidence/evidence, Aadhaar redaction before any external call, file hashing, and a cache in `data/extracted/*.json`. Minimal preprocessing only (rotate/deskew/page split).
- **P2:** rules engine against hand-written JSON (don't wait for P1): A1-A6, B1-B4 first, B5-B8 after. Then the mock registry index (SQLite/JSON).
- **P3:** synthetic data generator (templates, fonts, degradation), generate ~20 PDFs/images; Streamlit skeleton with three pages (Citizen, SRO console, Ledger verify) wired to stubs.

**T-2:30 | Checkpoint 1 (10 min, all 3)**
- P1 hands over real extracted JSON for ≥8 docs. P2 runs the rules on it. P3 confirms the UI reads both.
- If extraction is failing on ≥3 docs, switch to **cached/hand-corrected JSON for the demo** and report real accuracy honestly. Don't burn the remaining time on OCR tuning.

**T-2:30 → T-1:30 | Integrate and build the ledger (60 min)**
- **P2:** ledger (entry format below), Ed25519 signing, chain verification, tamper-detect function.
- **P3:** Citizen page (pre-flight Class A + evidence gap map with the three states + "What we did not check" + "Ask your seller" list). SRO console (flags, acknowledgement, dispositions, sign).
- **P1:** batch-run extraction on all docs; start the accuracy table; add Hindi/Assamese docs; set confidence thresholds from the eval data (not guessed); build the Cline SDK review agent (B12.2) on the `needs_review` fields; output a request-list generator.

**Ledger entry (P2)**
```json
{
  "idx": 12,
  "prev_hash": "...",
  "timestamp": "...",
  "parcel_ref": "mock-ULPIN",
  "bundle_hash": "SHA-256 of sorted original-file hashes",
  "extraction_hash": "...",
  "ruleset_version": "v1",
  "model_version": "...",
  "checklist_state": [{"flag_id": "B2", "class": "B"}],
  "dispositions": [{"flag_id": "B2", "action": "PARTIES_INFORMED", "reason": "..."}],
  "party_commitments": ["HMAC(salt, name) ..."],
  "officer_sig_ref": "mock DSC serial",
  "signature": "Ed25519 over canonical JSON",
  "entry_hash": "SHA-256(canonical JSON)"
}
```

**T-1:30 | Checkpoint 2 (10 min, all 3): end-to-end dry run**
- Walk one B2 case through the whole flow: upload → flags → disposition → signed entry → verify.
- Triage list: anything broken now is cut or faked with cached data. **No new features after this point.**

**T-1:30 → T-0:45 | Evaluation + polish (45 min)**
- **P1:** accuracy table: field-level extraction accuracy on clean vs degraded docs; abstention rate.
- **P2:** rule precision/recall on planted defects (including decoy P7), plus the tamper demo script.
- **P3:** UI polish for the three hero screens only; start the deck (see B8).
- **Feature freeze at T-0:45.** Everyone stops writing code except bug fixes.

**T-0:45 → T-0:15 | Pitch + rehearsal (30 min)**
- P3 finishes the deck. P1 and P2 prepare Q&A answers (A7) and a backup screen-recording of the demo.
- Rehearse twice, timed. Assign Q&A owners: P1 (AI/OCR), P2 (ledger/legal-design), P3 (market/product).

**T-0:15 → T-0:00 | Buffer and submission**
- Final run on the demo machine, **demo video** (real user scenario + Cline in action during the build + Cline agent inside the product), README, PPT, social post, submission upload. Keep the last 15 minutes free for things that go wrong.
- Hackathon deliverables checklist is in B12.1.

### B8. Pitch structure (5 minutes)

1. **Problem (30s):** Registration records what was presented; it doesn't guarantee title. Officers can't decide title, but advisory risks go unseen.
2. **Insight (30s):** DILRMP 3.0 is building the land stack; nobody is building the intelligence layer on top.
3. **Demo A, SRO console (90s):** upload bundle → Class A flag + Class B advisory → officer records dispositions → signed log entry.
4. **Demo B, tamper test (30s):** edit one log entry → verification fails.
5. **Demo C, citizen portal (60s):** pre-flight result + evidence gap map. **Hero screen: "No contradictions found among uploaded documents. Five categories not checked."**
6. **Proof (45s):** accuracy table, honest about synthetic data and the abstention behaviour.
7. **Cline (30s):** built with Cline end to end (show the commit/task trail); a Cline SDK agent runs *inside* the product to review uncertain extractions with evidence, and never decides flags.
8. **Why now / ask (30s):** draft Registration Bill, DILRMP 3.0, pilot with one registrar office.

Note: the hackathon PPT also needs challenges faced and future scope slides, and the AI models/tools used; the 5-minute pitch is the short version of it.

### B9. Risk register

| Risk | Mitigation |
|---|---|
| OCR/API quota or network fails during demo | Cached extraction JSON + backup screen recording |
| Extraction accuracy poor on Indic docs | Report honestly; show abstention; demo mostly on English docs plus 1-2 Hindi/Assamese |
| Scope creep (translator, hygiene) | Slide-only unless Checkpoint 2 is green |
| UI time sink | Streamlit defaults; polish 3 screens only |
| Merge conflicts | Separate folders per person; contract frozen at T-3:40 |
| Cline SDK doesn't work / API differs from docs | 15-minute smoke test at kickoff; fall back to build-only Cline use and say so honestly. The pipeline must work with the review agent switched off |
| Cline agent "fixes" a field wrongly | It only proposes corrections with a quoted evidence snippet; low-confidence results stay `needs_review`; every change is logged in `provenance` |
| Legal claims challenged | Use the Q&A sheet; mark draft-Bill claims as draft; avoid "title verified", "blockchain", "zero-knowledge" |

### B10. Definition of Done checklist

- [ ] ~20 synthetic docs + labels file
- [ ] `extract()` returns schema-valid JSON with confidence and abstention
- [ ] Rules A1-A6 and B1-B4 working (B5-B8 if time)
- [ ] SRO console with per-flag acknowledgement and dispositions
- [ ] Signed hash-chained log + live tamper-detection demo
- [ ] Citizen page with three evidence states and "What we did not check"
- [ ] Accuracy table (extraction + rule precision/recall)
- [ ] 5-minute deck, rehearsed twice, Q&A owners assigned
- [ ] Backup demo video recorded
- [ ] `absent` vs `unreadable` handled end to end (Class A fires on absent; unreadable shows "needs review")
- [ ] Cline used from first commit; build footage recorded
- [ ] Cline SDK review agent working inside the product (or honest fallback noted)
- [ ] Hackathon deliverables: public repo + full README (B12.1), PPT, demo video, social post tagging Cline
- [ ] README + submission uploaded with 15 minutes to spare

---

### B11. P1 extraction pipeline (corrected workflow)

```text
 1. Upload (PDF / image)  ──► hash original file (SHA-256) ──► provenance
          │
 2. Preprocess (minimal): rotate / deskew / page split. No OCR tuning.
          │
 3. Redact Aadhaar numbers BEFORE any external API call
          │
 4. Vision-LLM (or OCR+LLM) single pass with the JSON schema prompt
    ──► field objects: value, status, confidence, evidence{page, quote, bbox?}
          │         (cache result to data/extracted/<doc_id>.json)
          │
 5. Validate
    - schema + enums + formats (dates, ULPIN, numeric area)
    - cross-check pass (2nd prompt or OCR vs LLM) → agreement feeds confidence
    - confidence = f(validity, agreement, calibrated threshold), not LLM self-report
          │
 6. Classify each field, not the document:
    ├─ extracted   (confidence ≥ threshold)        → straight to rules + UI
    ├─ absent      (readable, genuinely not there) → rules + UI (Class A fires)
    └─ unreadable  (confidence < threshold)        → `needs_review`
                                                       │
                                  Cline SDK review agent (B12.2) re-reads the page,
                                  proposes a value + quoted evidence, or confirms
                                  "unreadable". Human can accept/edit in the UI
                                  (`human_corrected` in provenance).
          │
 7. Output: contract v1.1 JSON ──► rules engine (P2) + UI (P3) + ledger inputs
            (file_sha256, extraction hash, model_version)
```

**Sentence for P1:** turn deed documents into field-level structured data with status, confidence and quoted evidence, so the rules can check risk, and say "needs review" instead of guessing.

**Eval (P1, SHOULD):** field-level accuracy on clean vs degraded docs, abstention rate, and per-language results (en/hi/as). Thresholds are set from this data.

### B12. Hackathon requirements and Cline

**B12.1 Deliverables (from the Cline AI Builder Hackathon brief)**

| Deliverable | Status / owner |
|---|---|
| Public GitHub repo + README covering: problem, solution, architecture, tech stack, setup steps, **how Cline was used in the build** | P3 owns README; every person adds their Cline notes |
| PPT: problem, solution, architecture, AI models/tools, **how Cline was used (build + inside the solution)**, challenges, future scope | P3 |
| **Demo video (mandatory):** real user scenario + Cline in action during the build | All; record Cline sessions from kickoff |
| Social post tagging Cline (bonus) | Anyone, after submission |

The brief allows 8 hours; this plan is written for ~4. If you really have 8, add the COULD items (translator, hygiene check) after Checkpoint 2.

**B12.2 Cline inside the product (bonus points)**

- **What:** a Cline SDK agent, the *extraction review agent*, runs on fields marked `needs_review`.
- **Tools it gets** (via `createTool`): `read_page_text(doc_id, page)`, `get_extracted(doc_id)`, `validate_field(key, value)`, `propose_correction(key, value, quote, page)`.
- **What it can do:** re-read the evidence page, propose a value with a quoted snippet, or confirm the field is unreadable.
- **What it cannot do:** run rules, create or clear flags, touch the ledger, or write any legal explanation. This keeps "LLM only extracts; deterministic rules decide".
- **Guardrails:** its proposals are marked `extraction_method: cline_review` in provenance; fields below threshold stay `needs_review` for a human; the pipeline works with the agent switched off.
- **Optional second use (only if ahead):** a build-time Cline agent that generates and degrades synthetic deeds.
- **Integration:** Node 22+ sidecar called from Python; **[VERIFY]** against docs.cline.bot/sdk/overview.

**B12.3 Cline in the build (evidence to collect)**

- First commit made through Cline; keep task history and screenshots.
- Use Cline for scaffolding the repo, the schema validator, the rules engine unit tests and the synthetic data script.
- Record short clips of Cline working for the demo video; note challenges where Cline got something wrong and how you fixed it (good PPT material).

## PART C: VERIFY BEFORE YOU SAY IT ON STAGE

- Cline SDK: package name (`@cline/sdk` vs the separate `cline` ACP package), Node version, and the `Agent` / `createTool` API against the official docs.

- Registration Bill 2025 status (draft vs introduced vs enacted) and the exact section numbers cited here.
- TEAL India / Prava AI: what they currently offer.
- *Suraj Lamp* and TPA s.54 characterisation (ask a law-literate teammate).
- Aadhaar authentication entity rules, DPDP obligations for your design.
- Whether your state has prohibited-property lists or an existing registration-alert service.
- Your OCR provider's current Assamese/Hindi accuracy claims (vendor benchmarks are not your accuracy).
