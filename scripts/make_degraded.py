"""
Turn SAMPLE-1.pdf (digital) into SCANNED, degraded PDFs (images only, no text layer),
to exercise the Tesseract path, orientation, deskew, the quality gate and redaction.

  mild      3 deg tilt, light blur, light noise
  heavy     7 deg tilt, strong blur, heavy noise, low contrast, uneven shadow, JPEG artefacts
  sideways  page 1 rotated 90 deg (orientation fix), mild tilt

Run: python -m scripts.make_degraded
"""

from pathlib import Path

import cv2
import fitz
import numpy as np

rng = np.random.default_rng(7)


def render(pdf: Path, dpi: int = 150) -> list[np.ndarray]:
    out = []
    for page in fitz.open(str(pdf)):
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        out.append(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return out


def rotate(img, deg):
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=(235, 235, 235))


def degrade(img, tilt, blur, noise, contrast=1.0, shadow=0.0, jpeg=90):
    img = rotate(img, tilt)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    f = img.astype(np.float32)
    f = (f - 128) * contrast + 128
    if shadow:
        h, w = f.shape[:2]
        grad = np.linspace(1 - shadow, 1.0, w, dtype=np.float32)[None, :, None]
        f = f * grad
    if noise:
        f += rng.normal(0, noise, f.shape)
    img = np.clip(f, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


VARIANTS = {
    "mild": lambda pages: [degrade(p, 3, 0.8, 6) for p in pages],
    "heavy": lambda pages: [degrade(p, 7, 2.2, 22, contrast=0.55, shadow=0.45, jpeg=40) for p in pages],
    "sideways": lambda pages: [degrade(cv2.rotate(pages[0], cv2.ROTATE_90_CLOCKWISE), 2, 0.8, 6)]
                              + [degrade(p, 2, 0.8, 6) for p in pages[1:]],
}


def main() -> None:
    src = Path("data/raw/SAMPLE-1.pdf")
    pages = render(src)
    for name, fn in VARIANTS.items():
        doc = fitz.open()
        for img in fn(pages):
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            page = doc.new_page(width=img.shape[1] * 72 / 150, height=img.shape[0] * 72 / 150)
            page.insert_image(page.rect, stream=buf.tobytes())
        out = Path(f"data/raw/SAMPLE-1-scan-{name}.pdf")
        doc.save(str(out))
        words = sum(len(p.get_text("words")) for p in fitz.open(str(out)))
        print(f"wrote {out}  (text-layer words: {words})")


if __name__ == "__main__":
    main()
