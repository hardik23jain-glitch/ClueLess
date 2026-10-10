"""
Quick synthetic deed for P1 smoke tests (P3's full generator comes later).

Planted on purpose, so we know the right answers:
  * seller acts through an attorney but NO power-of-attorney registration number  -> poa_reg_no ABSENT
  * no ULPIN anywhere                                                            -> ABSENT
  * a valid-checksum fake Aadhaar number                                         -> must be redacted
  * boundaries, survey number, area, consideration, stamp duty all present
Run: python scripts/make_sample_deed.py
"""

from pathlib import Path

import fitz

from extract.redact import verhoeff_check_digit

base = "23456789012"
aadhaar = base + verhoeff_check_digit(base)
aadhaar_s = f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}"

PAGES = [
    [
        "SALE DEED",
        "Registration No: 4821/2021        Registered at Sub-Registrar Office, Kamrup (Metro), Guwahati",
        "",
        "This Deed of Sale is executed on 12/03/2021 at Guwahati between:",
        "SELLER: Ramesh Kumar, son of Mohan Kumar, resident of Beltola, Guwahati, acting through his",
        "duly constituted attorney Anil Sharma under a General Power of Attorney.",
        f"Seller's identity proof: Aadhaar {aadhaar_s}.",
        "BUYER: Sunita Devi, wife of Anil Devi, resident of Dispur, Guwahati.",
        "",
        "The seller acquired the property by Deed No. 1187 of 2015 dated 04/08/2015.",
        "The deed was presented for registration on 20/03/2021.",
    ],
    [
        "SCHEDULE OF PROPERTY",
        "Survey No 123, Khata No 45, situated at Beltola, Guwahati. Total area 1200 sq ft.",
        "Bounded by:",
        "North: Public road",
        "East: Land of Dilip Das",
        "South: Land of Rina Bora",
        "West: Drain",
        "",
        "Sale consideration: Rs 4,50,000 (Rupees four lakh fifty thousand only) paid in full.",
        "Stamp duty paid: Rs 31,500 by e-stamp.",
        "Signed by the executant and witnesses.",
    ],
]


def main() -> None:
    out = Path("data/raw")
    out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for lines in PAGES:
        page = doc.new_page()
        y = 80
        for line in lines:
            page.insert_text((50, y), line, fontsize=10)
            y += 24
    path = out / "SAMPLE-1.pdf"
    doc.save(str(path))
    print("wrote", path, "| planted Aadhaar:", aadhaar_s)


if __name__ == "__main__":
    main()
