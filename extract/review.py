"""
Step 7: the Cline review agent, called from Python (bonus: Cline INSIDE the product).

Flow: fields still `unreadable` -> job.json (candidate + notes + redacted page
text) -> `node cline_agent/review_agent.mjs job.json` -> proposals -> Python
re-validates each one -> accepted or left for a human.

The agent is advisory. A proposal becomes `extracted` only if ALL hold:
  * the agent said status "read" with a value and a quote,
  * the value passes the same format check as everything else,
  * the quote is found on the page by the LOCAL reader at >= 90 similarity.
Otherwise the field stays `unreadable` (the candidate is updated as a hint).
If Node / the SDK / a key is missing, the review is skipped and recorded as
such, and the pipeline's output is unchanged. It must work with the agent off.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .classify import summarize
from .config import Config
from .ingest import Page
from .localtext import DocText, grounding_score, locate_quote
from .redact import redact_text
from .schema import SPEC_BY_KEY, DeedExtraction, Evidence, Field, FieldStatus, Source
from .validate import check_value

MARKER = "LANDGUARD_RESULT:"


def _page_texts(pages: list[Page]) -> dict[str, str]:
    out = {}
    for p in pages:
        if p.words:
            out[str(p.index)] = redact_text(" ".join(w.text for w in p.words))
    return out


def review_unreadable(ex: DeedExtraction, pages: list[Page], doc: DocText, cfg: Config) -> DeedExtraction:
    keys = list(ex.needs_review)
    if not keys:
        ex.provenance.review = "not_needed"
        return ex
    if not cfg.enable_cline_review:
        ex.provenance.review = "skipped: disabled"
        return ex
    node = shutil.which("node")
    if not node or not Path(cfg.cline_agent_script).exists():
        ex.provenance.review = "skipped: node or cline_agent not available"
        return ex

    job = {
        "doc_id": ex.doc_id,
        "keys": keys,
        "fields": {k: {"candidate": ex.fields[k].candidate, "notes": ex.fields[k].notes,
                       "seen_on_page": ex.fields[k].evidence.page} for k in keys},
        "pages": _page_texts(pages),
    }
    try:
        with tempfile.TemporaryDirectory() as td:
            jp = Path(td) / "job.json"
            jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            proc = subprocess.run([node, str(cfg.cline_agent_script), str(jp)], capture_output=True, text=True,
                                  timeout=cfg.cline_timeout_s, cwd=str(Path(cfg.cline_agent_script).parent))
        line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith(MARKER)), None)
        if line is None:
            ex.provenance.review = f"failed: no result (exit {proc.returncode})"
            return ex
        result = json.loads(line[len(MARKER):])
    except Exception as e:
        ex.provenance.review = f"failed: {type(e).__name__}"
        return ex

    if result.get("error"):
        ex.provenance.review = f"failed: {result['error'][:120]}"
        return ex

    accepted = 0
    proposals = [p for p in result.get("proposals", []) if p.get("key") in keys]
    for p in proposals:
        key = p["key"]
        f = ex.fields[key]
        spec = SPEC_BY_KEY[key]
        if p.get("status") != "read" or p.get("value") in (None, "") or not p.get("quote"):
            f.notes.append("review agent could not confirm a value")
            continue
        value, valid, vnote = check_value(spec, redact_text(p["value"]))
        quote = redact_text(p["quote"])
        page = p.get("page") if isinstance(p.get("page"), int) else None
        g = grounding_score(quote, doc, page)
        if not valid:
            f.candidate = value
            f.notes.append(f"review agent proposal rejected: {vnote}")
        elif g is None or g < 90:
            f.candidate = value
            f.notes.append("review agent proposal not confirmed by the local reader; left for a human")
        else:
            ev_page, bbox, _ = locate_quote(quote, doc, page)
            ex.fields[key] = Field(value=value, status=FieldStatus.EXTRACTED, confidence=0.8,
                                   evidence=Evidence(page=ev_page, quote=quote, bbox=bbox),
                                   source=Source.CLINE_REVIEW,
                                   notes=["value proposed by the Cline review agent and confirmed on the page"])
            accepted += 1

    ex.needs_review, ex.overall_confidence = summarize(ex.fields)
    ex.provenance.review = f"ran: {accepted}/{len(keys)} fields recovered"
    return ex
