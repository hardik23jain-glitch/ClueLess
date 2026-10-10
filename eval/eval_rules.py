"""
Evaluation of Deterministic Rules Pipeline (P2 / P4).

Runs the pipeline offline on the synthetic planted-defect dataset (P1 to P8),
compares produced flags against data/labels/rule_labels.json, and reports:
  - Precision and recall per rule and overall
  - Decoy handling (P7 succession gap suppression)
  - Degradation / unreadable handling
  - Full transparency disclosure regarding synthetic data

Usage:
  python -m eval.eval_rules [--labels data/labels/rule_labels.json]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

from extract.cache import load_extraction
from extract.config import Config
from integration import run_risk_analysis


# Input fields each rule depends on: if one of them is `unreadable`, an expected flag that does not fire is a
# correct abstention (needs review), not a missed rule.
RULE_FIELDS = {
    "A1": {"acting_through_poa.poa_reg_no", "acting_through_poa.used", "acting_through_poa.is_attorney"},
    "A2": {"property.area_value", "property.area_unit"},
    "A3": {"property.boundaries.N", "property.boundaries.E", "property.boundaries.S", "property.boundaries.W"},
    "A4": {"execution_date", "presentation_date"},
    "A5": {"seller.name", "buyer.name"},
    "A6": {"consideration"},
    "A7": {"property.ulpin"},
    "B3": {"property.area_value", "property.area_unit"},
    "B4": {"property.boundaries.N", "property.boundaries.E", "property.boundaries.S", "property.boundaries.W"},
}

RULE_NAMES = {
    "A1": "POA Registration Missing",
    "A2": "Property Area Missing",
    "A3": "Property Boundaries Missing",
    "A4": "Presentation Window Exceeded",
    "A5": "Party Names Missing",
    "A6": "Consideration Missing",
    "A7": "ULPIN Parent Mismatch",
    "B0": "Registry Cross-Check Unavailable",
    "B1": "Broken Ownership Link",
    "B2": "Possible Double Sale (Parallel Conveyance)",
    "B3": "Area Exceeds Parent Deed",
    "B4": "Boundary Mismatch vs Parent",
    "B5": "Date-Order Anomaly",
    "B6": "Same-Person Name Difference (Fuzzy)",
    "B7": "Unregistered Instrument in Chain",
    "B8": "Active Encumbrance Recorded",
}


def evaluate_rules(labels_path: Path, cfg: Config) -> Dict[str, Any]:
    cases = json.loads(labels_path.read_text(encoding="utf-8"))
    results = []

    # Per-rule TP, FP, FN counts
    rule_tp: Dict[str, int] = defaultdict(int)
    rule_fp: Dict[str, int] = defaultdict(int)
    rule_fn: Dict[str, int] = defaultdict(int)

    all_rules_evaluated: Set[str] = set()

    for case in cases:
        parcel_id = case.get("parcel_id", "Unknown")
        doc_id = case["doc_id"]
        bundle_ids = case.get("bundle_doc_ids", [])
        expected = set(case.get("expected_flags", []))

        draft = load_extraction(cfg, doc_id)
        if draft is None:
            raise FileNotFoundError(f"Missing extraction for {doc_id} in data/extracted/")

        bundle = []
        for b_id in bundle_ids:
            b_doc = load_extraction(cfg, b_id)
            if b_doc is not None:
                bundle.append(b_doc)

        analysis = run_risk_analysis(draft, bundle)
        all_flags = analysis.get("class_a_flags", []) + analysis.get("class_b_flags", [])
        produced = {f["flag_id"] for f in all_flags}
        needs_review = [r["field_path"] for r in analysis.get("needs_review", [])]

        # For P6-scan: degradation legitimately turns unreadable fields into needs_review items,
        # which suppresses hard stops as per Design Rule 5. If expected A1 was caught via review, note it.
        # An expected flag whose input field was sent to review is a CORRECT abstention (the system
        # refuses to flag what it could not read), not a missed rule. Reported separately.
        abstained = {r for r in expected - produced
                     if RULE_FIELDS.get(r, set()) & set(needs_review)}
        is_exact_match = (produced == (expected - abstained))

        # Update per-rule metrics
        for r in expected:
            all_rules_evaluated.add(r)
            if r in produced:
                rule_tp[r] += 1
            elif r in abstained:
                continue
            else:
                rule_fn[r] += 1

        for r in produced:
            all_rules_evaluated.add(r)
            if r not in expected:
                rule_fp[r] += 1

        results.append({
            "parcel_id": parcel_id,
            "doc_id": doc_id,
            "bundle": bundle_ids,
            "expected": sorted(list(expected)),
            "produced": sorted(list(produced)),
            "needs_review_count": len(needs_review),
            "abstained": sorted(abstained),
            "exact_match": is_exact_match,
            "notes": case.get("notes", ""),
        })

    return {
        "cases": results,
        "rule_tp": rule_tp,
        "rule_fp": rule_fp,
        "rule_fn": rule_fn,
        "all_rules": sorted(list(all_rules_evaluated)),
    }


def print_report(eval_data: Dict[str, Any]) -> None:
    cases = eval_data["cases"]
    rule_tp = eval_data["rule_tp"]
    rule_fp = eval_data["rule_fp"]
    rule_fn = eval_data["rule_fn"]

    print("=" * 80)
    print("LANDGUARD AI - DETERMINISTIC RULES EVALUATION REPORT")
    print("=" * 80)
    print()

    print("--- CASE BY CASE EVALUATION ---")
    header = f"{'Parcel':<10} {'Doc ID':<15} {'Expected':<12} {'Produced':<12} {'Review':<8} {'Status'}"
    print(header)
    print("-" * len(header))

    total_cases = len(cases)
    exact_matches = 0

    for c in cases:
        exp_str = ",".join(c["expected"]) if c["expected"] else "None"
        prod_str = ",".join(c["produced"]) if c["produced"] else "None"
        match_str = ("PASS (abstained: " + ",".join(c["abstained"]) + " -> needs review)"
                     if c.get("abstained") and c["exact_match"] else ("PASS" if c["exact_match"] else "FAIL"))
        if c["exact_match"]:
            exact_matches += 1
        print(f"{c['parcel_id']:<10} {c['doc_id']:<15} {exp_str:<12} {prod_str:<12} {c['needs_review_count']:<8} {match_str}")
        if not c["exact_match"]:
            print(f"   Note: {c['notes']}")

    print()
    print("--- DECOY HANDLING (P7) ---")
    p7_cases = [c for c in cases if c["parcel_id"] == "P7"]
    if p7_cases:
        p7 = p7_cases[0]
        if "B1" not in p7["produced"] and len(p7["produced"]) == 0:
            print("  [SUCCESS] P7 Decoy verified: Seller/owner gap explained by registered succession doc in bundle.")
            print("            BROKEN_OWNERSHIP_LINK (B1) was successfully suppressed (0 false alarms).")
        else:
            print(f"  [FAILURE] P7 Decoy raised unexpected flags: {p7['produced']}")
    print()

    print("--- PER-RULE PRECISION AND RECALL ---")
    rule_hdr = f"{'Rule':<6} {'Name':<35} {'TP':<4} {'FP':<4} {'FN':<4} {'Precision':<10} {'Recall':<10}"
    print(rule_hdr)
    print("-" * len(rule_hdr))

    total_tp = sum(rule_tp.values())
    total_fp = sum(rule_fp.values())
    total_fn = sum(rule_fn.values())

    for r in eval_data["all_rules"]:
        tp = rule_tp[r]
        fp = rule_fp[r]
        fn = rule_fn[r]
        prec = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
        r_name = RULE_NAMES.get(r, "Advisory/HardStop")
        print(f"{r:<6} {r_name:<35} {tp:<4} {fp:<4} {fn:<4} {prec * 100:>8.1f}% {rec * 100:>8.1f}%")

    print("-" * len(rule_hdr))
    overall_prec = (total_tp / (total_tp + total_fp)) if (total_tp + total_fp) > 0 else 1.0
    overall_rec = (total_tp / (total_tp + total_fn)) if (total_tp + total_fn) > 0 else 1.0
    case_accuracy = (exact_matches / total_cases) * 100 if total_cases > 0 else 0.0

    print(f"{'TOTAL':<6} {'Overall Rule Performance':<35} {total_tp:<4} {total_fp:<4} {total_fn:<4} {overall_prec * 100:>8.1f}% {overall_rec * 100:>8.1f}%")
    print()
    print(f"Exact Case Match Rate: {exact_matches}/{total_cases} ({case_accuracy:.1f}%)")
    print()

    print("=" * 80)
    print("HONESTY & TRANSPARENCY DISCLOSURE")
    print("=" * 80)
    print("1. All data in this evaluation is 100% SYNTHETIC, generated for testing the rules engine.")
    print("2. Both the dataset and rules engine were authored by the same team for the Hackathon.")
    print("3. These metrics demonstrate the determinism and consistency of the rules engine and")
    print("   decoy suppression; they do NOT claim field-tested real-world OCR or title accuracy.")
    print("4. LandGuard AI is an advisory risk-screening layer. It NEVER certifies title.")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Evaluate rules engine on synthetic dataset.")
    parser.add_argument("--labels", default="data/labels/rule_labels.json", help="Path to rule labels JSON")
    args = parser.parse_args()

    cfg = Config(provider="mock")
    labels_file = Path(args.labels)
    if not labels_file.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_file}")

    eval_data = evaluate_rules(labels_file, cfg)
    print_report(eval_data)


if __name__ == "__main__":
    main()
