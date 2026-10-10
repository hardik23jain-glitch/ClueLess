# Integration guide for P2 and P3

How the extraction (P1), rules/ledger (P2) and the app (P3) connect. All names below exist in the repo.

## 1. Get an extraction

```python
from extract import extract_deed
ex = extract_deed("data/raw/SAMPLE-1.pdf")       # DeedExtraction; also saved to data/extracted/SAMPLE-1.json
```
Cached JSON for the sample deeds is in `data/extracted/`, so the UI can work with no API key and no network. Load one with `extract.cache.load_extraction(Config.from_env(), "SAMPLE-1")`.

Each field is `{value, status, confidence, evidence{page, quote, bbox}, source, notes}`:

| status | Meaning | What the UI should do |
|---|---|---|
| `extracted` | Read confidently | show the value, link `evidence` |
| `absent` | Page is readable and the item is not stated | show as "not provided" (Class A rules may fire) |
| `unreadable` | Could not be read | show "needs review", let a human type it in; never treat as missing |

Never show the word "clean" or "safe". `value` is set only for `extracted`; `candidate` on an unreadable field is a hint for a human only.

## 2. Run the rules

```python
from integration import run_risk_analysis
result = run_risk_analysis(draft_extraction, [parent_extraction, ...])
result["class_a_flags"]   # registrability (hard stops)
result["class_b_flags"]   # advisories (not refusal grounds)
result["needs_review"]    # fields we could not read: shown separately, never a finding about the deed
```
Every flag has `flag_id`, `class`, `code`, `title`, `detail`, `mitigation`, `field_path` and `evidence: [{doc_id, field, page, quote, bbox}]`. Show the page and quote next to each flag.

Plain engine dicts (the old shape) still work for the draft/parent arguments. Parent deeds are linked automatically when the draft's `parent_ref.doc_ref` text contains the parent's registration number (e.g. "Deed No. 1187 of 2015" ↔ `1187/2015`).

## 3. Human correction (the "needs review" screen)

```python
from extract import apply_human_correction
apply_human_correction("SAMPLE-1", "property.area_value", "1200")
```
Validates the value, marks it `human_corrected`, recomputes the extraction hash and saves.

## 4. Advocate brief and request list

```python
from extract import build_request_list
from rules.advocate_brief import build_brief
brief_md = build_brief(result, build_request_list(draft_extraction))
```
The brief is built from a fixed wording library (no LLM), so it never implies a title conclusion.

## 5. Record the officer's decision

```python
from integration import commit_to_ledger
out = commit_to_ledger(parcel_ulpin, draft, parents, all_flags, dispositions, officer_id)
# dispositions = {"A1": {"action": "RETURN_FOR_CORRECTION", "reason": "..."},
#                 "A3": {"action": "REFUSE_RECORDED_GROUND", "reason": "...", "ground_ref": "s.58(…)"}}
```
Allowed actions: `ACK_PROCEED`, `PARTIES_INFORMED`, `REFER_REVENUE_AUTHORITY`, `RETURN_FOR_CORRECTION`, `REFUSE_RECORDED_GROUND` (Class A flags only, needs `ground_ref`). A reason is required. Invalid input raises `ValueError`.

The entry binds the SHA-256 of the original uploaded files, the extraction hashes, the ruleset and model versions and salted-HMAC commitments of the party names, then is Ed25519-signed. It returns `row_id`, `entry_hash`, `signature`, `public_key`.

Verify for the tamper demo:
```python
from ledger.signing import verify_signatures
verify_signatures()      # (True, None, "ok")  or  (False, row_idx, reason)
```

## Conventions

- **ULPIN:** 14 alphanumeric characters (e.g. `AS000000000104`). Short codes like `AS-104` are accepted by the registry as aliases, but the extractor only accepts 14-character values, so use that format in every synthetic deed.
- **Before the demo:** call `ledger.audit_log.reset_audit_log()` once so old unsigned rows don't fail signature verification.
- **Secrets:** `.env`, `ledger/signing_key.pem`, `ledger/commit_salt.bin` and `ledger/audit_log.db` are git-ignored.
- **Privacy:** use synthetic documents only. Handwritten ID numbers cannot be masked before the image reaches the model.
- **Quick end-to-end check:** `python -m scripts.demo_flow`.
