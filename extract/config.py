"""
Tunable settings for the LandGuard extraction pipeline (Person 1).

Everything that could be a magic number lives here, so the eval script can
sweep a threshold and the team can change a provider without touching logic.
Values can be overridden with environment variables (see `Config.from_env`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bump when the prompt or contract changes: it is part of the cache key, so an
# old cached extraction is never served for a new prompt.
PROMPT_VERSION = "v1.1-5"
CONTRACT_VERSION = "1.1"


@dataclass
class Config:
    # ---- Provider ---------------------------------------------------
    # "gemini" | "anthropic" | "mock". Decide at kickoff after the API/quota check.
    provider: str = "gemini"
    gemini_model: str = "gemini-flash-latest"   # gemini-2.5-flash is closed to new API projects
    anthropic_model: str = "claude-sonnet-5-5"
    # Gemini 2.5 "thinking" tokens share the output budget. Uncapped, a long blank
    # form burned 15.7k of 16.4k tokens thinking and the JSON was cut off.
    # Transcription needs little reasoning; keep it small. (0 disables thinking.)
    gemini_thinking_budget: int = 1024
    temperature: float = 0.0          # extraction is factual; no creativity wanted
    max_output_tokens: int = 16384

    # ---- Ingest / preprocess ---------------------------------------
    render_dpi: int = 200             # PDF page -> image
    target_short_edge_px: int = 1600  # sweet spot for OCR and vision encoders
    max_upscale: float = 2.0
    max_pages: int = 12               # pages sent to the model per document
    jpeg_quality: int = 92

    # ---- Quality gate ----------------------------------------------
    min_sharpness: float = 25.0       # Laplacian variance
    min_contrast: float = 12.0        # luminance std-dev

    # ---- Local text (cross-check) ----------------------------------
    # Tesseract language packs; falls back to "eng" if a pack is missing.
    ocr_langs: str = "eng+hin+asm+mar"

    # ---- Classification thresholds (calibrate with eval/) ----------
    extract_threshold: float = 0.75   # >= this => status "extracted"
    absent_threshold: float = 0.70    # confidence needed to trust "not stated"
    ground_min_score: float = 80.0    # fuzzy score for "quote is really on the page"

    # ---- Privacy -----------------------------------------------------
    # Redaction needs word boxes (text layer or Tesseract). If neither is
    # available the redaction is "unverified" and the external call is
    # BLOCKED unless this is set. Only set it for synthetic data.
    allow_unredacted_external: bool = False

    # ---- Paths -------------------------------------------------------
    extracted_dir: Path = field(default_factory=lambda: ROOT / "data" / "extracted")
    cache_dir: Path = field(default_factory=lambda: ROOT / "data" / "cache")
    mock_dir: Path = field(default_factory=lambda: ROOT / "data" / "mock")

    # ---- Cline review agent (bonus) ---------------------------------
    enable_cline_review: bool = True
    cline_agent_script: Path = field(default_factory=lambda: ROOT / "cline_agent" / "review_agent.mjs")
    cline_timeout_s: int = 120

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.provider = os.getenv("LANDGUARD_PROVIDER", c.provider)
        c.gemini_model = os.getenv("LANDGUARD_GEMINI_MODEL", c.gemini_model)
        c.anthropic_model = os.getenv("LANDGUARD_ANTHROPIC_MODEL", c.anthropic_model)
        c.extract_threshold = float(os.getenv("LANDGUARD_EXTRACT_THRESHOLD", c.extract_threshold))
        c.allow_unredacted_external = os.getenv("LANDGUARD_ALLOW_UNREDACTED", "0") == "1"
        c.enable_cline_review = os.getenv("LANDGUARD_CLINE_REVIEW", "1") == "1"
        return c

    @property
    def model_name(self) -> str:
        return {"gemini": self.gemini_model, "anthropic": self.anthropic_model}.get(self.provider, "mock")
