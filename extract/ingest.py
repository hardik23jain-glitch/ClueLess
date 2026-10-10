"""
Step 1: load the uploaded deed (PDF, image, or a folder of page images) into
Page objects and hash the original bytes.

The SHA-256 of the ORIGINAL file is the first thing the ledger needs
(bundle_hash), so it is computed from raw bytes before anything touches them.

Digital PDFs (e.g. our synthetic deeds) carry a text layer. We keep those word
boxes: they are a free, perfectly accurate "second reader" used to cross-check
the vision model, and they let us find evidence boxes and redact Aadhaar
numbers without any OCR at all. Scanned PDFs and photos have no text layer and
go through Tesseract later (localtext.py).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .config import Config

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float = 100.0      # 0-100; text-layer words are 100


@dataclass
class Page:
    index: int                                # 1-based
    image: np.ndarray                         # BGR
    words: list[Word] = field(default_factory=list)
    has_text_layer: bool = False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode_image(path: Path) -> np.ndarray:
    # np.fromfile + imdecode: cv2.imread fails on non-ASCII Windows paths.
    arr = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not decode image: {path}")
    return img


def _load_pdf(path: Path, cfg: Config) -> tuple[list[Page], int]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    total = doc.page_count
    zoom = cfg.render_dpi / 72.0
    doc_words = sum(len(doc[i].get_text("words")) for i in range(total))
    doc_has_layer = doc_words >= 20           # the PDF as a whole is digital
    pages: list[Page] = []
    for i in range(min(total, cfg.max_pages)):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        words = [
            Word(text=w[4], x=w[0] * zoom, y=w[1] * zoom,
                 w=(w[2] - w[0]) * zoom, h=(w[3] - w[1]) * zoom)
            for w in page.get_text("words")
        ]
        # A page is digital if it has a real text layer, OR the PDF is digital and
        # this page is short/blank with no embedded picture (e.g. a signature page).
        # A page with a picture and no text in a digital PDF is a pasted scan: raster path.
        digital = len(words) >= 20 or (doc_has_layer and not page.get_images())
        pages.append(Page(index=i + 1, image=img, words=words, has_text_layer=digital))
    doc.close()
    return pages, total


def load_document(path: str | Path, cfg: Config) -> tuple[list[Page], str, int, list[str]]:
    """Returns (pages, sha256_of_original, total_pages_in_source, warnings)."""
    p = Path(path)
    warnings: list[str] = []
    if not p.exists():
        raise FileNotFoundError(p)

    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT)
        if not files:
            raise ValueError(f"No page images in folder {p}")
        digest = sha256_bytes("".join(sha256_file(f) for f in files).encode())
        pages = [Page(index=i + 1, image=_decode_image(f)) for i, f in enumerate(files[: cfg.max_pages])]
        total = len(files)
    elif p.suffix.lower() == ".pdf":
        digest = sha256_file(p)
        pages, total = _load_pdf(p, cfg)
    elif p.suffix.lower() in IMAGE_EXT:
        digest = sha256_file(p)
        pages, total = [Page(index=1, image=_decode_image(p))], 1
    else:
        raise ValueError(f"Unsupported file type: {p.suffix}")

    if total > cfg.max_pages:
        warnings.append(f"Document has {total} pages; only the first {cfg.max_pages} were processed.")
    return pages, digest, total, warnings
