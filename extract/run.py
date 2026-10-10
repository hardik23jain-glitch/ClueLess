"""
Command line:
    python -m extract.run data/raw/P2-D3.pdf                 one document
    python -m extract.run data/raw                           every PDF/image in a folder (batch)
    python -m extract.run data/raw --provider mock --no-review
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from .config import Config
from .ingest import IMAGE_EXT
from .pipeline import extract_deed
from .schema import FieldStatus


def _summary(ex) -> str:
    c = {s: sum(1 for f in ex.fields.values() if f.status == s) for s in FieldStatus}
    flag = " RETAKE" if ex.retake_required else ""
    return (f"{ex.doc_id:<14} extracted={c[FieldStatus.EXTRACTED]:>2} absent={c[FieldStatus.ABSENT]:>2} "
            f"unreadable={c[FieldStatus.UNREADABLE]:>2} overall={ex.overall_confidence:.2f} "
            f"review={ex.provenance.review}{flag}")


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--doc-id")
    ap.add_argument("--provider", choices=["gemini", "anthropic", "mock"])
    ap.add_argument("--force", action="store_true", help="ignore the raw-reply cache")
    ap.add_argument("--no-review", action="store_true", help="skip the Cline review agent")
    a = ap.parse_args()

    cfg = Config.from_env()
    if a.provider:
        cfg.provider = a.provider
    if a.no_review:
        cfg.enable_cline_review = False

    p = Path(a.path)
    # A folder of PDFs/images = a batch of single-file deeds (one deed per file).
    files = sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT | {".pdf"}) if p.is_dir() else [p]
    for f in files:
        ex = extract_deed(f, doc_id=a.doc_id if len(files) == 1 else None, cfg=cfg, force=a.force)
        print(_summary(ex))
        for w in ex.provenance.warnings:
            print("   warning:", w)


if __name__ == "__main__":
    main()
