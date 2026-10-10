"""
Step 6b: caching: the demo safety net.

Two layers, both keyed by SHA-256(file) + provider + model + prompt version +
redaction flag, so a stale answer is never served after the prompt changes:

  data/cache/<key>.json       the model's RAW reply. Re-running classification
                              (e.g. to sweep the confidence threshold in eval/)
                              costs no API calls.
  data/extracted/<doc_id>.json the final contract JSON. P2 and P3 read these.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from .config import PROMPT_VERSION, Config
from .schema import DeedExtraction


def make_cache_key(file_sha: str, provider: str, model: str, redaction_verified: bool) -> str:
    raw = "|".join([file_sha, provider, model, PROMPT_VERSION, f"redact={int(redaction_verified)}"])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def load_raw(cfg: Config, key: str) -> Optional[str]:
    f = Path(cfg.cache_dir) / f"{key}.json"
    return f.read_text(encoding="utf-8") if f.exists() else None


def save_raw(cfg: Config, key: str, raw: str) -> None:
    Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)
    (Path(cfg.cache_dir) / f"{key}.json").write_text(raw, encoding="utf-8")


def save_extraction(cfg: Config, ex: DeedExtraction) -> Path:
    Path(cfg.extracted_dir).mkdir(parents=True, exist_ok=True)
    out = Path(cfg.extracted_dir) / f"{ex.doc_id}.json"
    out.write_text(ex.model_dump_json(indent=2), encoding="utf-8")
    return out


def load_extraction(cfg: Config, doc_id: str) -> Optional[DeedExtraction]:
    f = Path(cfg.extracted_dir) / f"{doc_id}.json"
    if not f.exists():
        return None
    return DeedExtraction.model_validate_json(f.read_text(encoding="utf-8"))


def extraction_hash(ex: DeedExtraction) -> str:
    """
    Stable hash of the extraction for the ledger's `extraction_hash`. Excludes
    the timestamp and the hash itself, so re-running on a cache hit gives the
    same value.
    """
    d = json.loads(ex.model_dump_json())
    d["provenance"].pop("extracted_at", None)
    d["provenance"].pop("extraction_hash", None)
    canon = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
