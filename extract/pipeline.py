"""
The orchestrator: `extract_deed(path) -> DeedExtraction`. This is the function P2/P3 call.

    1 ingest        load PDF/image/folder, hash the ORIGINAL bytes
    2 preprocess    orient / deskew / size, measure quality
    3 local text    PDF text layer or Tesseract: the second, independent reader
    4 redact        black out Aadhaar/PAN BEFORE anything leaves the machine
    5 model         vision LLM (cached) -> raw JSON
    6 classify      per-field status + calibrated confidence
    7 review        optional Cline agent on still-unreadable fields
    8 seal          provenance + extraction_hash for the ledger, save to data/extracted/

Failure policy: nothing in here may turn an error into a guess. If the model
call fails, the reply cannot be parsed, or redaction cannot be verified, every
field becomes `unreadable` and the reason goes into provenance.warnings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .cache import (extraction_hash, load_extraction, load_raw, make_cache_key, save_extraction, save_raw)
from .classify import all_unreadable, build_fields, summarize
from .config import CONTRACT_VERSION, PROMPT_VERSION, Config
from .ingest import load_document
from .localtext import build_doctext
from .preprocess import preprocess_pages
from .prompts import RETRY_NOTE, SYSTEM_PROMPT, build_user_prompt
from .providers import ProviderError, get_provider, read_with_retry
from .redact import redact_pages
from .review import review_unreadable
from .schema import SPEC_BY_KEY, DeedExtraction, Evidence, Field, FieldStatus, Provenance, Source
from .validate import ModelOutputError, check_value, parse_model_json


def extract_deed(path: str | Path, doc_id: Optional[str] = None, cfg: Optional[Config] = None,
                 force: bool = False, save: bool = True) -> DeedExtraction:
    cfg = cfg or Config.from_env()
    path = Path(path)
    doc_id = doc_id or path.stem
    warnings: list[str] = []

    # 1-2 ingest + preprocess
    pages, sha, total_pages, w = load_document(path, cfg)
    warnings += w
    quality = preprocess_pages(pages, cfg)
    warnings += quality.pop("notes", [])

    # 3 local text, 4 redaction
    doc = build_doctext(pages, cfg)
    images, red = redact_pages(pages)

    provider = None
    fields = None
    language = "other"
    writing = "printed"
    method = "vision_llm"
    cache_key = ""
    model_id = cfg.model_name

    try:
        # External calls need verified redaction (the mock provider is offline).
        if cfg.provider != "mock" and not red.verified and not cfg.allow_unredacted_external:
            raise ProviderError(
                "redaction could not be verified (no text layer and Tesseract unavailable); "
                "external call blocked. Install Tesseract, or set LANDGUARD_ALLOW_UNREDACTED=1 for synthetic data only.")

        cache_key = make_cache_key(sha, cfg.provider, model_id, red.verified)

        model_json = None
        raw = None if force else load_raw(cfg, cache_key)
        if raw is not None:
            try:
                model_json = parse_model_json(raw)
                method = "cached_vision_llm"
            except ModelOutputError:
                model_json = None                      # unusable cache entry: ask again

        if model_json is None:
            provider = get_provider(cfg)
            model_id = provider.model or model_id
            last_err: Optional[Exception] = None
            for attempt in range(2):                   # one re-ask if the reply is not valid JSON
                user = build_user_prompt(len(images)) + (RETRY_NOTE if attempt else "")
                raw = read_with_retry(provider, images, SYSTEM_PROMPT, user, doc_id=doc_id)
                try:
                    model_json = parse_model_json(raw)
                    break
                except ModelOutputError as e:
                    last_err = e
            if model_json is None:
                # Keep the unparseable reply (never cached as valid) so it can be inspected.
                failed = Path(cfg.cache_dir) / "failed"
                failed.mkdir(parents=True, exist_ok=True)
                (failed / f"{doc_id}.txt").write_text(raw or "", encoding="utf-8")
                raise last_err
            if cfg.provider != "mock":                 # cache only replies that parsed
                save_raw(cfg, cache_key, raw)
        fields, language, writing = build_fields(model_json, doc, quality["acceptable"], cfg)
        if writing != "printed":
            warnings.append(
                f"{writing} document: read by the vision model"
                + (" alone" if writing == "handwritten" else " (local cross-check only on printed parts)")
                + "; handwritten ID numbers cannot be detected for redaction, so review before sharing.")
    except (ProviderError, ModelOutputError) as e:
        warnings.append(f"extraction failed, all fields need review: {e}")
        fields = all_unreadable(str(e)[:160])
    except Exception as e:  # network errors, SDK errors: never a guess, always a reason
        warnings.append(f"extraction failed, all fields need review: {type(e).__name__}: {str(e)[:160]}")
        fields = all_unreadable(f"{type(e).__name__}")

    extraction_failed = any(w.startswith("extraction failed") for w in warnings)
    needs, overall = summarize(fields)
    ex = DeedExtraction(
        doc_id=doc_id,
        provenance=Provenance(
            file_sha256=sha, file_name=path.name, pages=total_pages,
            extraction_method=method, provider=cfg.provider, model_version=model_id,
            prompt_version=PROMPT_VERSION, contract_version=CONTRACT_VERSION, cache_key=cache_key,
            extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            redaction=red.as_dict(), quality={k: v for k, v in quality.items() if k != "pages"},
            local_text=doc.source, warnings=warnings,
        ),
        fields=fields, needs_review=needs, language=language, writing=writing, overall_confidence=overall,
        retake_required=bool(quality["retake"]),
    )

    # 7 optional Cline review of fields still unreadable
    # (Skipped when the model call itself failed: the agent would only burn quota on a document we never read.)
    if extraction_failed:
        ex.provenance.review = "skipped: extraction failed"
    else:
        ex = review_unreadable(ex, pages, doc, cfg)

    # 8 seal
    ex.provenance.extraction_hash = extraction_hash(ex)
    if save:
        save_extraction(cfg, ex)
    return ex


def apply_human_correction(doc_id: str, key: str, value, cfg: Optional[Config] = None) -> DeedExtraction:
    """
    Human-in-the-loop (the "needs review" screen calls this). A human-entered
    value is trusted fully, marked `human_corrected`, and the extraction hash is
    recomputed so the ledger binds to the corrected data.
    """
    cfg = cfg or Config.from_env()
    ex = load_extraction(cfg, doc_id)
    if ex is None:
        raise FileNotFoundError(f"No extraction for {doc_id}")
    spec = SPEC_BY_KEY[key]
    norm_value, valid, note = check_value(spec, value)
    if not valid:
        raise ValueError(note)
    prev = ex.fields[key]
    ex.fields[key] = Field(
        value=norm_value,
        status=FieldStatus.EXTRACTED if norm_value is not None else FieldStatus.ABSENT,
        confidence=1.0, evidence=Evidence(page=prev.evidence.page, quote=prev.evidence.quote, bbox=prev.evidence.bbox),
        source=Source.HUMAN, notes=["entered or confirmed by a human reviewer"])
    ex.needs_review, ex.overall_confidence = summarize(ex.fields)
    ex.provenance.extraction_method = "human_corrected"
    ex.provenance.extraction_hash = extraction_hash(ex)
    save_extraction(cfg, ex)
    return ex
