"""
Step 2: minimal preprocessing + a quality gate.

Deliberately small. The plan says "no OCR tuning": a vision LLM reads a
colour, upright, reasonably sharp page better than a heavily binarised one
(the MediKiosk code keeps a separate colour stream for the same reason). So we
only: fix orientation, deskew, normalise size, and MEASURE quality.

Text-layer PDF pages are left untouched: resizing or rotating them would
invalidate the word boxes we get from the PDF for free.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import Config
from .ingest import Page


# ---------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------
def assess_quality(gray: np.ndarray, cfg: Config) -> dict:
    """Sharpness (Laplacian variance), contrast, and a plain-language verdict."""
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(np.std(gray))
    reasons = []
    if sharp < cfg.min_sharpness:
        reasons.append(f"blurry (sharpness {sharp:.0f} < {cfg.min_sharpness:.0f})")
    if contrast < cfg.min_contrast:
        reasons.append(f"low contrast ({contrast:.0f} < {cfg.min_contrast:.0f})")
    return {
        "sharpness": round(sharp, 1),
        "contrast": round(contrast, 1),
        "acceptable": not reasons,
        # Severely bad: ask for a retake instead of guessing.
        "retake": sharp < cfg.min_sharpness * 0.4 or contrast < cfg.min_contrast * 0.5,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------
def fix_orientation(img: np.ndarray) -> tuple[np.ndarray, str]:
    """
    Upright the page. Tesseract OSD resolves all four rotations when available.
    When OSD fails (noisy or sparse pages) we do NOT rotate on a guess: a wrong
    90-degree turn on an upright page is worse than leaving a sideways one for
    the vision model, which copes with rotated pages. We only warn. (A first
    version rotated on a weak projection guess and turned an upright, heavily
    degraded scan sideways.)
    """
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        angle = int(osd.get("rotate", 0)) % 360
        code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(angle)
        return (cv2.rotate(img, code) if code is not None else img), f"osd:{angle}"
    except Exception:
        pass

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 900.0 / max(gray.shape))
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rows = float(np.var(ink.sum(axis=1)))
    cols = float(np.var(ink.sum(axis=0)))
    if cols > rows * 3.0:   # text lines look vertical: page may be sideways; warn, don't rotate
        return img, "uncertain"
    return img, "none"


# ---------------------------------------------------------------------
# Deskew
# ---------------------------------------------------------------------
def _score_angle(ink: np.ndarray, angle: float) -> float:
    h, w = ink.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rot = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST)
    return float(np.var(rot.sum(axis=1)))     # sharp peaks/valleys = straight text lines


def estimate_skew(gray: np.ndarray, max_deg: float = 8.0) -> float:
    """Projection-profile search: the angle that makes text rows most distinct."""
    scale = min(1.0, 800.0 / max(gray.shape))
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coarse = np.arange(-max_deg, max_deg + 0.01, 0.5)
    best = max(coarse, key=lambda a: _score_angle(ink, a))
    fine = np.arange(best - 0.5, best + 0.51, 0.1)
    return float(max(fine, key=lambda a: _score_angle(ink, a)))


def deskew(img: np.ndarray) -> tuple[np.ndarray, float]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = estimate_skew(gray)
    if abs(angle) < 0.3:
        return img, 0.0
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return out, angle


# ---------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------
def normalize_size(img: np.ndarray, cfg: Config) -> np.ndarray:
    h, w = img.shape[:2]
    short = min(h, w)
    if short == 0:
        return img
    scale = min(cfg.target_short_edge_px / float(short), cfg.max_upscale)
    if 0.9 <= scale <= 1.1:
        return img
    interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)


# ---------------------------------------------------------------------
def preprocess_pages(pages: list[Page], cfg: Config) -> dict:
    """Mutates pages in place. Returns a document-level quality summary."""
    notes: list[str] = []
    per_page = []
    for p in pages:
        if not p.has_text_layer:
            p.image, ori = fix_orientation(p.image)
            if ori == "uncertain":
                notes.append(f"page {p.index}: page may be sideways and could not be verified; left as is")
            p.image, angle = deskew(p.image)
            p.image = normalize_size(p.image, cfg)
        gray = cv2.cvtColor(p.image, cv2.COLOR_BGR2GRAY)
        q = assess_quality(gray, cfg)
        # A digital page is perfectly legible by construction.
        if p.has_text_layer:
            q.update(acceptable=True, retake=False, reasons=[])
        per_page.append(q)

    summary = {
        "pages": per_page,
        "acceptable": all(q["acceptable"] for q in per_page),
        "retake": any(q["retake"] for q in per_page),
        "reasons": sorted({r for q in per_page for r in q["reasons"]}),
        "notes": notes,
    }
    return summary
