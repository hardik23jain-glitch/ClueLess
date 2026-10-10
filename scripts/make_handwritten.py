"""
Handwriting-STYLE deed: cursive font (OFL, Google Fonts) in blue ink on ruled, noisy paper, then photographed
(tilt, blur, shadow, JPEG). It is a synthetic stand-in: real handwriting will be harder.

Planted: seller signs personally (no POA), no ULPIN, a handwritten Aadhaar-like number (valid checksum) that the
local redactor CANNOT see (the known gap for handwriting), so the final JSON must still not contain it.
Run: python -m scripts.make_handwritten <path-to-font.ttf>
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from extract.redact import verhoeff_check_digit
from scripts.make_degraded import degrade

rng = np.random.default_rng(11)
base = "34567890123"
AADHAAR = base + verhoeff_check_digit(base)
AADHAAR_S = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"

LINES = [
    "SALE DEED",
    "Reg. No. 5173/2022",
    "This deed of sale is made on 14/05/2022 at Guwahati between",
    "Mahesh Verma s/o Gopal Verma, resident of Maligaon (Seller),",
    "who signs personally, and Kavita Singh w/o Ravi Singh,",
    "resident of Ganeshguri (Buyer).",
    f"Seller ID proof: Aadhaar {AADHAAR_S}",
    "The seller bought this land in the year 2012.",
    "Presented for registration on 25/05/2022.",
    "Schedule: Survey No 214, area 900 sq ft, Maligaon, Guwahati.",
    "Boundaries:",
    "North: Main road",
    "East: Plot of Hari Das",
    "South: Plot of Meena Roy",
    "West: Nala",
    "Consideration: Rs 3,80,000 paid in full.",
    "Stamp duty paid: Rs 26,600 by e-stamp.",
    "Signed: Mahesh Verma",
]

LABELS = {
    "doc_type": "sale_deed", "registered": True, "registration_no": "5173/2022",
    "execution_date": "2022-05-14", "presentation_date": "2022-05-25",
    "seller.name": "Mahesh Verma", "seller.relation_name": "Gopal Verma",
    "buyer.name": "Kavita Singh", "buyer.relation_name": "Ravi Singh",
    "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
    "property.ulpin": None, "property.survey_no": "214", "property.area_value": 900, "property.area_unit": "sqft",
    "property.boundaries.N": "Main road", "property.boundaries.E": "Plot of Hari Das",
    "property.boundaries.S": "Plot of Meena Roy", "property.boundaries.W": "Nala",
    "parent_ref.claimed_acquisition_year": 2012, "consideration": 380000, "stamp_duty": 26600,
}


def paper(w, h):
    img = np.full((h, w, 3), (232, 238, 244), np.float32)          # warm paper (BGR)
    for y in range(120, h, 54):                                      # faint blue ruled lines
        img[y:y + 2, :, :] = (225, 205, 190)
    img += rng.normal(0, 3, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)[:, :, ::-1])


def main() -> None:
    font = ImageFont.truetype(sys.argv[1], 34)
    w, h = 1240, 1754
    page = paper(w, h).convert("RGBA")
    y = 110
    for line in LINES:
        layer = Image.new("RGBA", (w, 90), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((70 + int(rng.integers(-6, 7)), 14), line, font=font,
                                   fill=(28, 38, 120, int(rng.integers(215, 255))))
        layer = layer.rotate(float(rng.normal(0, 0.5)), resample=Image.BICUBIC)
        page.alpha_composite(layer, (0, y - 30))
        y += 54 if line != "Boundaries:" else 54
    bgr = cv2.cvtColor(np.array(page.convert("RGB")), cv2.COLOR_RGB2BGR)
    photo = degrade(bgr, tilt=2.0, blur=0.9, noise=5, contrast=0.9, shadow=0.25, jpeg=85)
    out = Path("data/raw/HANDWRITTEN-1.jpg")
    cv2.imencode(".jpg", photo, [int(cv2.IMWRITE_JPEG_QUALITY), 85])[1].tofile(str(out))
    print("wrote", out, "| handwritten Aadhaar planted:", AADHAAR_S)

    lp = Path("data/labels/extraction_labels.json")
    labels = [x for x in json.loads(lp.read_text(encoding="utf-8")) if x["doc_id"] != "HANDWRITTEN-1"]
    labels.append({"doc_id": "HANDWRITTEN-1", "condition": "handwritten", "language": "en", "fields": LABELS})
    lp.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
