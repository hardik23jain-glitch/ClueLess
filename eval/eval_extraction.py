"""
Extraction accuracy report (P1, "Proof" slide).

Labels file: data/labels/extraction_labels.json
    [{"doc_id": "P1-D1", "condition": "clean|degraded", "language": "en|hi|as|mr",
      "fields": {"seller.name": "Ramesh Kumar", "acting_through_poa.poa_reg_no": null, ...}}]
A label of null means "genuinely not in the document" (the correct answer is ABSENT).
Write labels BEFORE looking at model output, and don't edit them afterwards.

Reports
  * field accuracy on fields we ACCEPTED (extracted), the number that matters
  * coverage (share extracted), absent precision, abstention (unreadable) rate
  * the same split by condition and language
  * a confidence-threshold sweep, to pick extract_threshold from data
Run:  python -m eval.eval_extraction [--labels path] [--target 0.95]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from extract.cache import load_extraction
from extract.config import ROOT, Config
from extract.schema import FieldStatus
from extract.textutil import norm


def same(pred, truth) -> bool:
    if truth is None or pred is None:
        return truth is pred
    if isinstance(truth, bool) or isinstance(pred, bool):
        return bool(truth) == bool(pred)
    if isinstance(truth, (int, float)) and not isinstance(truth, bool):
        try:
            return abs(float(pred) - float(truth)) < 1e-6
        except (TypeError, ValueError):
            return False
    return norm(str(pred)) == norm(str(truth))


def evaluate(labels: list[dict], cfg: Config) -> dict:
    rows = []   # one row per (doc, field)
    for lab in labels:
        ex = load_extraction(cfg, lab["doc_id"])
        if ex is None:
            continue
        for key, truth in lab["fields"].items():
            f = ex.fields.get(key)
            if f is None:
                continue
            rows.append({"doc": lab["doc_id"], "key": key, "cond": lab.get("condition", "?"),
                         "lang": lab.get("language", "?"), "truth": truth, "status": f.status,
                         "pred": f.value, "conf": f.confidence, "cand": f.candidate})
    return {"rows": rows}


def stats(rows: list[dict]) -> dict:
    n = len(rows)
    ext = [r for r in rows if r["status"] == FieldStatus.EXTRACTED]
    ab = [r for r in rows if r["status"] == FieldStatus.ABSENT]
    un = [r for r in rows if r["status"] == FieldStatus.UNREADABLE]
    return {
        "fields": n,
        "coverage": len(ext) / n if n else 0.0,
        "accuracy_on_extracted": (sum(same(r["pred"], r["truth"]) for r in ext) / len(ext)) if ext else None,
        "absent_precision": (sum(r["truth"] is None for r in ab) / len(ab)) if ab else None,
        "abstention_rate": len(un) / n if n else 0.0,
    }


def sweep(rows: list[dict], target: float) -> list[tuple]:
    """For each candidate threshold: coverage and accuracy among fields with conf >= t."""
    out = []
    readable = [r for r in rows if r["status"] in (FieldStatus.EXTRACTED, FieldStatus.UNREADABLE)]
    for t in [x / 100 for x in range(50, 100, 5)]:
        kept = [r for r in readable if r["conf"] >= t and (r["pred"] is not None or r["cand"] is not None)]
        if not kept:
            continue
        ok = sum(same(r["pred"] if r["pred"] is not None else r["cand"], r["truth"]) for r in kept)
        out.append((t, len(kept) / len(readable), ok / len(kept)))
    return out


def fmt(x):
    return "n/a" if x is None else f"{x:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(ROOT / "data" / "labels" / "extraction_labels.json"))
    ap.add_argument("--target", type=float, default=0.95, help="accuracy target for the suggested threshold")
    a = ap.parse_args()
    labels = json.loads(Path(a.labels).read_text(encoding="utf-8"))
    rows = evaluate(labels, Config.from_env())["rows"]
    if not rows:
        print("No matching extractions found. Run the pipeline first.")
        return

    print("\n=== OVERALL ===")
    s = stats(rows)
    print(f"fields={s['fields']}  coverage={fmt(s['coverage'])}  accuracy_on_extracted={fmt(s['accuracy_on_extracted'])}  "
          f"absent_precision={fmt(s['absent_precision'])}  abstention={fmt(s['abstention_rate'])}")

    for title, key in (("CONDITION", "cond"), ("LANGUAGE", "lang")):
        print(f"\n=== BY {title} ===")
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        for g, rs in sorted(groups.items()):
            s = stats(rs)
            print(f"{g:<10} fields={s['fields']:<4} coverage={fmt(s['coverage']):<7} "
                  f"accuracy={fmt(s['accuracy_on_extracted']):<7} abstention={fmt(s['abstention_rate'])}")

    print("\n=== THRESHOLD SWEEP (conf >= t) ===")
    best = None
    for t, cov, acc in sweep(rows, a.target):
        print(f"t={t:.2f}  coverage={cov:.1%}  accuracy={acc:.1%}")
        if acc >= a.target and best is None:
            best = t
    print(f"\nSuggested extract_threshold for >= {a.target:.0%} accuracy: {best if best is not None else 'none reached; collect more data or improve prompt'}")
    print("Note: labels are synthetic; these numbers show the pipeline logic, not real-world OCR robustness.")


if __name__ == "__main__":
    main()
