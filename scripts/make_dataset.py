"""
Planted-defect dataset generator for LandGuard AI.
Generates ~20 synthetic documents covering Parcels P1 to P8.

Parcels:
  P1: Clean 3-deed chain -> no flags (coverage panel still shows)
  P2: Seller claims 2018 acquisition, no transfer to them -> B1
  P3: Same parcel sold twice (second deed only in registry) -> B2
  P4: Subdivision area exceeds parent -> B3
  P5: Boundary differs from parent -> B4
  P6: Seller via attorney, no POA reg no -> A1
  P7: Gap explained by succession document (DECOY) -> no B1
  P8: Hindi deed (Devanagari, planted facts) -> B4

Outputs:
  data/raw/<doc_id>.pdf
  data/mock/<doc_id>.json
  data/extracted/<doc_id>.json
  data/labels/extraction_labels.json (updated)
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import fitz
import numpy as np

from extract.config import Config
from extract.pipeline import extract_deed
from extract.redact import verhoeff_check_digit
from extract.schema import FIELD_KEYS
from scripts.make_degraded import degrade, render

EDGE = next((p for p in (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
) if Path(p).exists()), None)

rng = np.random.default_rng(42)


def _fake_aadhaar(seed_digits: str) -> str:
    base = (seed_digits * 3)[:11]
    cd = verhoeff_check_digit(base)
    full = base + cd
    return f"{full[:4]} {full[4:8]} {full[8:]}"


def _make_pdf(path: Path, pages_lines: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for lines in pages_lines:
        page = doc.new_page()
        y = 70
        for line in lines:
            if line == "":
                y += 12
                continue
            is_hdr = line.isupper() and len(line) < 40
            font_size = 11 if is_hdr else 9.5
            page.insert_text((50, y), line, fontsize=font_size)
            y += 20
    doc.save(str(path))


def _make_scan(src_pdf: Path, out_pdf: Path) -> None:
    pages = render(src_pdf)
    doc = fitz.open()
    for img in [degrade(p, 3, 0.8, 6) for p in pages]:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        page = doc.new_page(width=img.shape[1] * 72 / 150, height=img.shape[0] * 72 / 150)
        page.insert_image(page.rect, stream=buf.tobytes())
    doc.save(str(out_pdf))


def _make_hindi_pdf(html_content: str, out_pdf: Path) -> None:
    if not EDGE:
        raise RuntimeError("Microsoft Edge not found for rendering Hindi Devanagari HTML")
    tmp = Path(tempfile.mkdtemp())
    try:
        html_file = tmp / "hindi.html"
        html_file.write_text(html_content, encoding="utf-8")
        out_temp = tmp / "out.pdf"
        subprocess.run([
            EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={out_temp}", html_file.as_uri()
        ], check=True, timeout=90, capture_output=True)
        shutil.copy(out_temp, out_pdf)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_page_and_quote(doc_pdf: fitz.Document, candidate_quotes: List[str]) -> tuple[int, str]:
    """Find which 1-based page contains any of the candidate quotes."""
    for q in candidate_quotes:
        if not q:
            continue
        for page_idx in range(doc_pdf.page_count):
            text = doc_pdf[page_idx].get_text()
            if q in text:
                return page_idx + 1, q
    # Case-insensitive / partial fallback
    for q in candidate_quotes:
        if not q:
            continue
        for page_idx in range(doc_pdf.page_count):
            text = doc_pdf[page_idx].get_text()
            if q.lower() in text.lower():
                idx = text.lower().find(q.lower())
                return page_idx + 1, text[idx:idx + len(q)]
    return 1, candidate_quotes[0] if candidate_quotes else ""


def _build_model_reply(fields_dict: Dict[str, Any], pdf_path: Path, lang: str = "en") -> str:
    """Build canned model reply in the format expected by MockProvider and parse_model_json."""
    doc_pdf = fitz.open(str(pdf_path))
    fields_out = {}
    for k in FIELD_KEYS:
        val = fields_dict.get(k)
        if val is None:
            fields_out[k] = {
                "value": None,
                "state": "not_stated",
                "confidence": 0.95,
                "page": 1,
                "quote": None,
            }
        else:
            explicit_quote = fields_dict.get(f"_quote_{k}")
            candidates = []
            if explicit_quote:
                candidates.append(explicit_quote)
            if k == "registered":
                candidates.extend(["Registered at", "पंजीकृत", "Registration No:", "पंजीकरण संख्या:"])
            elif k == "acting_through_poa.is_attorney":
                if val is False:
                    candidates.extend(["signs personally", "व्यक्तिगत रूप", "SELLER:", "विक्रेता:"])
                else:
                    candidates.extend(["attorney", "मुख्तार", "Power of Attorney"])
            elif k == "property.area_unit":
                candidates.extend(["sq ft", "sqft", "वर्ग फुट", "वर्गफुट"])
            elif k == "consideration":
                candidates.extend([f"Rs {val:,}" if isinstance(val, (int, float)) else str(val), "consideration", "प्रतिफल", "Rs", "रुपये"])
            elif k == "stamp_duty":
                candidates.extend([f"Rs {val:,}" if isinstance(val, (int, float)) else str(val), "Stamp duty", "स्टाम्प शुल्क"])
            elif k == "property.survey_no":
                candidates.extend([f"Survey No: {val}", f"Survey No {val}", f"सर्वे नंबर {val}", "Survey No", "सर्वे नंबर"])
            elif k == "parent_ref.claimed_acquisition_year":
                candidates.extend([str(val), f"year {val}", f"वर्ष {val}"])
            candidates.append(str(val))

            explicit_page = fields_dict.get(f"_page_{k}")
            if explicit_page:
                page_num, quote_text = explicit_page, (explicit_quote or candidates[0])
            else:
                page_num, quote_text = _find_page_and_quote(doc_pdf, candidates)

            fields_out[k] = {
                "value": val,
                "state": "read",
                "confidence": 0.98,
                "page": page_num,
                "quote": quote_text,
            }
    return json.dumps({"language": lang, "fields": fields_out}, ensure_ascii=False, indent=2)


DOC_DEFINITIONS = [
    # -------------------------------------------------------------------------
    # P1: Clean 3-deed chain (P1-D1, P1-D2, P1-D3)
    # -------------------------------------------------------------------------
    {
        "doc_id": "P1-D1",
        "lang": "en",
        "lines": [
            [
                "DEED OF CONVEYANCE / SALE DEED",
                "Registration No: 101/2010      Sub-Registrar Office, Kamrup, Guwahati",
                "",
                "This Deed of Sale is made on 12/04/2010 between:",
                "SELLER: Jatin Borah, son of Mukul Borah, resident of Beltola, Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('101')}.",
                "BUYER: Bimal Das, son of Ramesh Das, resident of Dispur, Guwahati.",
                "The seller signs personally and conveys all rights title and interest.",
                "The deed was presented for registration on 20/04/2010.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000101",
                "Survey No: 401, Beltola. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Public Road",
                "East: Plot 2",
                "South: Drainage Lane",
                "West: Plot 4",
                "",
                "Sale consideration: Rs 2,50,000 paid in full.",
                "Stamp duty paid: Rs 15,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "101/2010",
            "execution_date": "2010-04-12", "presentation_date": "2010-04-20",
            "seller.name": "Jatin Borah", "seller.relation_name": "Mukul Borah",
            "buyer.name": "Bimal Das", "buyer.relation_name": "Ramesh Das",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000101", "property.survey_no": "401",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Public Road", "property.boundaries.E": "Plot 2",
            "property.boundaries.S": "Drainage Lane", "property.boundaries.W": "Plot 4",
            "consideration": 250000, "stamp_duty": 15000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 101/2010",
            "_quote_execution_date": "made on 12/04/2010",
            "_quote_presentation_date": "presented for registration on 20/04/2010",
            "_quote_seller.name": "SELLER: Jatin Borah",
            "_quote_buyer.name": "BUYER: Bimal Das",
            "_quote_property.ulpin": "ULPIN: AS000000000101",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Public Road",
            "_quote_property.boundaries.E": "East: Plot 2",
            "_quote_property.boundaries.S": "South: Drainage Lane",
            "_quote_property.boundaries.W": "West: Plot 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P1-D2",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 202/2016      Sub-Registrar Office, Kamrup, Guwahati",
                "",
                "This Deed of Sale is executed on 15/08/2016 between:",
                "SELLER: Bimal Das, son of Ramesh Das, resident of Dispur, Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('102')}.",
                "BUYER: Anil Sharma, son of Mohan Sharma, resident of Beltola, Guwahati.",
                "The seller acquired the property by Deed No. 101 of 2010 dated 12/04/2010.",
                "The deed was presented for registration on 25/08/2016.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000101",
                "Survey No: 401. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Public Road",
                "East: Plot 2",
                "South: Drainage Lane",
                "West: Plot 4",
                "",
                "Sale consideration: Rs 4,50,000 paid in full.",
                "Stamp duty paid: Rs 27,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "202/2016",
            "execution_date": "2016-08-15", "presentation_date": "2016-08-25",
            "seller.name": "Bimal Das", "seller.relation_name": "Ramesh Das",
            "buyer.name": "Anil Sharma", "buyer.relation_name": "Mohan Sharma",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000101", "property.survey_no": "401",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Public Road", "property.boundaries.E": "Plot 2",
            "property.boundaries.S": "Drainage Lane", "property.boundaries.W": "Plot 4",
            "parent_ref.doc_ref": "Deed No. 101 of 2010", "parent_ref.claimed_acquisition_year": 2010,
            "consideration": 450000, "stamp_duty": 27000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 202/2016",
            "_quote_execution_date": "executed on 15/08/2016",
            "_quote_presentation_date": "presented for registration on 25/08/2016",
            "_quote_seller.name": "SELLER: Bimal Das",
            "_quote_buyer.name": "BUYER: Anil Sharma",
            "_quote_parent_ref.doc_ref": "Deed No. 101 of 2010",
            "_quote_property.ulpin": "ULPIN: AS000000000101",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Public Road",
            "_quote_property.boundaries.E": "East: Plot 2",
            "_quote_property.boundaries.S": "South: Drainage Lane",
            "_quote_property.boundaries.W": "West: Plot 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P1-D3",
        "lang": "en",
        "has_scan": True,
        "lines": [
            [
                "SALE DEED",
                "Registration No: 303/2022      Sub-Registrar Office, Kamrup, Guwahati",
                "",
                "This Deed of Sale is executed on 10/03/2022 between:",
                "SELLER: Anil Sharma, son of Mohan Sharma, resident of Beltola, Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('103')}.",
                "BUYER: Sunita Roy, wife of Pradip Roy, resident of Dispur, Guwahati.",
                "The seller acquired the property by Deed No. 202 of 2016 dated 15/08/2016.",
                "The deed was presented for registration on 22/03/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000101",
                "Survey No: 401. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Public Road",
                "East: Plot 2",
                "South: Drainage Lane",
                "West: Plot 4",
                "",
                "Sale consideration: Rs 7,50,000 paid in full.",
                "Stamp duty paid: Rs 45,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "303/2022",
            "execution_date": "2022-03-10", "presentation_date": "2022-03-22",
            "seller.name": "Anil Sharma", "seller.relation_name": "Mohan Sharma",
            "buyer.name": "Sunita Roy", "buyer.relation_name": "Pradip Roy",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000101", "property.survey_no": "401",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Public Road", "property.boundaries.E": "Plot 2",
            "property.boundaries.S": "Drainage Lane", "property.boundaries.W": "Plot 4",
            "parent_ref.doc_ref": "Deed No. 202 of 2016", "parent_ref.claimed_acquisition_year": 2016,
            "consideration": 750000, "stamp_duty": 45000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 303/2022",
            "_quote_execution_date": "executed on 10/03/2022",
            "_quote_presentation_date": "presented for registration on 22/03/2022",
            "_quote_seller.name": "SELLER: Anil Sharma",
            "_quote_buyer.name": "BUYER: Sunita Roy",
            "_quote_parent_ref.doc_ref": "Deed No. 202 of 2016",
            "_quote_property.ulpin": "ULPIN: AS000000000101",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Public Road",
            "_quote_property.boundaries.E": "East: Plot 2",
            "_quote_property.boundaries.S": "South: Drainage Lane",
            "_quote_property.boundaries.W": "West: Plot 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P2: Seller claims 2018 acquisition, no transfer to them -> B1
    # -------------------------------------------------------------------------
    {
        "doc_id": "P2-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 112/2012      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/05/2012 between:",
                "SELLER: Dinesh Nath, son of Haren Nath, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('201')}.",
                "BUYER: Sunil Verma, son of O.P. Verma, resident of Guwahati.",
                "The deed was presented for registration on 18/05/2012.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000102",
                "Survey No: 502. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: Main Road",
                "East: Plot 5",
                "South: Private Lane",
                "West: Plot 7",
                "",
                "Sale consideration: Rs 3,00,000 paid in full.",
                "Stamp duty paid: Rs 18,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "112/2012",
            "execution_date": "2012-05-10", "presentation_date": "2012-05-18",
            "seller.name": "Dinesh Nath", "seller.relation_name": "Haren Nath",
            "buyer.name": "Sunil Verma", "buyer.relation_name": "O.P. Verma",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000102", "property.survey_no": "502",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "Main Road", "property.boundaries.E": "Plot 5",
            "property.boundaries.S": "Private Lane", "property.boundaries.W": "Plot 7",
            "consideration": 300000, "stamp_duty": 18000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 112/2012",
            "_quote_execution_date": "executed on 10/05/2012",
            "_quote_presentation_date": "presented for registration on 18/05/2012",
            "_quote_seller.name": "SELLER: Dinesh Nath",
            "_quote_buyer.name": "BUYER: Sunil Verma",
            "_quote_property.ulpin": "ULPIN: AS000000000102",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: Main Road",
            "_quote_property.boundaries.E": "East: Plot 5",
            "_quote_property.boundaries.S": "South: Private Lane",
            "_quote_property.boundaries.W": "West: Plot 7",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P2-D2",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 415/2022      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 15/06/2022 between:",
                "SELLER: Karan Johar, son of Yash Johar, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('202')}.",
                "BUYER: Rita Sen, wife of Amit Sen, resident of Guwahati.",
                "The seller claims to have acquired the property in year 2018.",
                "The deed was presented for registration on 25/06/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000102",
                "Survey No: 502. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: Main Road",
                "East: Plot 5",
                "South: Private Lane",
                "West: Plot 7",
                "",
                "Sale consideration: Rs 6,00,000 paid in full.",
                "Stamp duty paid: Rs 36,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "415/2022",
            "execution_date": "2022-06-15", "presentation_date": "2022-06-25",
            "seller.name": "Karan Johar", "seller.relation_name": "Yash Johar",
            "buyer.name": "Rita Sen", "buyer.relation_name": "Amit Sen",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000102", "property.survey_no": "502",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "Main Road", "property.boundaries.E": "Plot 5",
            "property.boundaries.S": "Private Lane", "property.boundaries.W": "Plot 7",
            "parent_ref.doc_ref": "Deed No. 112 of 2012", "parent_ref.claimed_acquisition_year": 2018,
            "consideration": 600000, "stamp_duty": 36000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 415/2022",
            "_quote_execution_date": "executed on 15/06/2022",
            "_quote_presentation_date": "presented for registration on 25/06/2022",
            "_quote_seller.name": "SELLER: Karan Johar",
            "_quote_buyer.name": "BUYER: Rita Sen",
            "_quote_property.ulpin": "ULPIN: AS000000000102",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: Main Road",
            "_quote_property.boundaries.E": "East: Plot 5",
            "_quote_property.boundaries.S": "South: Private Lane",
            "_quote_property.boundaries.W": "West: Plot 7",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P3: Same parcel sold twice -> B2
    # -------------------------------------------------------------------------
    {
        "doc_id": "P3-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 550/2015      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/02/2015 between:",
                "SELLER: Ravi Sharma, son of Mohan Sharma, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('301')}.",
                "BUYER: Meera Patel, wife of Rajesh Patel, resident of Guwahati.",
                "The deed was presented for registration on 18/02/2015.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000104",
                "Survey No: 603. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Road",
                "East: Plot 12",
                "South: Open Ground",
                "West: Canal",
                "",
                "Sale consideration: Rs 5,00,000 paid in full.",
                "Stamp duty paid: Rs 30,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "550/2015",
            "execution_date": "2015-02-10", "presentation_date": "2015-02-18",
            "seller.name": "Ravi Sharma", "seller.relation_name": "Mohan Sharma",
            "buyer.name": "Meera Patel", "buyer.relation_name": "Rajesh Patel",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000104", "property.survey_no": "603",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Road", "property.boundaries.E": "Plot 12",
            "property.boundaries.S": "Open Ground", "property.boundaries.W": "Canal",
            "consideration": 500000, "stamp_duty": 30000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 550/2015",
            "_quote_execution_date": "executed on 10/02/2015",
            "_quote_presentation_date": "presented for registration on 18/02/2015",
            "_quote_seller.name": "SELLER: Ravi Sharma",
            "_quote_buyer.name": "BUYER: Meera Patel",
            "_quote_property.ulpin": "ULPIN: AS000000000104",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Road",
            "_quote_property.boundaries.E": "East: Plot 12",
            "_quote_property.boundaries.S": "South: Open Ground",
            "_quote_property.boundaries.W": "West: Canal",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P3-D2",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 660/2022      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/04/2022 between:",
                "SELLER: Meera Patel, wife of Rajesh Patel, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('302')}.",
                "BUYER: Kavita Rao, wife of Suresh Rao, resident of Guwahati.",
                "The seller acquired the property by Deed No. 550 of 2015 dated 10/02/2015.",
                "The deed was presented for registration on 20/04/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000104",
                "Survey No: 603. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Road",
                "East: Plot 12",
                "South: Open Ground",
                "West: Canal",
                "",
                "Sale consideration: Rs 8,50,000 paid in full.",
                "Stamp duty paid: Rs 51,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "660/2022",
            "execution_date": "2022-04-10", "presentation_date": "2022-04-20",
            "seller.name": "Meera Patel", "seller.relation_name": "Rajesh Patel",
            "buyer.name": "Kavita Rao", "buyer.relation_name": "Suresh Rao",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000104", "property.survey_no": "603",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Road", "property.boundaries.E": "Plot 12",
            "property.boundaries.S": "Open Ground", "property.boundaries.W": "Canal",
            "parent_ref.doc_ref": "Deed No. 550 of 2015", "parent_ref.claimed_acquisition_year": 2015,
            "consideration": 850000, "stamp_duty": 51000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 660/2022",
            "_quote_execution_date": "executed on 10/04/2022",
            "_quote_presentation_date": "presented for registration on 20/04/2022",
            "_quote_seller.name": "SELLER: Meera Patel",
            "_quote_buyer.name": "BUYER: Kavita Rao",
            "_quote_parent_ref.doc_ref": "Deed No. 550 of 2015",
            "_quote_property.ulpin": "ULPIN: AS000000000104",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Road",
            "_quote_property.boundaries.E": "East: Plot 12",
            "_quote_property.boundaries.S": "South: Open Ground",
            "_quote_property.boundaries.W": "West: Canal",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P4: Subdivision area exceeds parent -> B3
    # -------------------------------------------------------------------------
    {
        "doc_id": "P4-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 210/2014      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 12/06/2014 between:",
                "SELLER: Gautam Bora, son of Tarun Bora, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('401')}.",
                "BUYER: Pradeep Das, son of Biren Das, resident of Guwahati.",
                "The deed was presented for registration on 20/06/2014.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000103",
                "Survey No: 704. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: Sector Road",
                "East: Plot 3",
                "South: Pathway",
                "West: Plot 1",
                "",
                "Sale consideration: Rs 3,50,000 paid in full.",
                "Stamp duty paid: Rs 21,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "210/2014",
            "execution_date": "2014-06-12", "presentation_date": "2014-06-20",
            "seller.name": "Gautam Bora", "seller.relation_name": "Tarun Bora",
            "buyer.name": "Pradeep Das", "buyer.relation_name": "Biren Das",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000103", "property.survey_no": "704",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "Sector Road", "property.boundaries.E": "Plot 3",
            "property.boundaries.S": "Pathway", "property.boundaries.W": "Plot 1",
            "consideration": 350000, "stamp_duty": 21000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 210/2014",
            "_quote_execution_date": "executed on 12/06/2014",
            "_quote_presentation_date": "presented for registration on 20/06/2014",
            "_quote_seller.name": "SELLER: Gautam Bora",
            "_quote_buyer.name": "BUYER: Pradeep Das",
            "_quote_property.ulpin": "ULPIN: AS000000000103",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: Sector Road",
            "_quote_property.boundaries.E": "East: Plot 3",
            "_quote_property.boundaries.S": "South: Pathway",
            "_quote_property.boundaries.W": "West: Plot 1",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P4-D2",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 710/2022      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/07/2022 between:",
                "SELLER: Pradeep Das, son of Biren Das, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('402')}.",
                "BUYER: Sanjay Gupta, son of M.L. Gupta, resident of Guwahati.",
                "The seller acquired the property by Deed No. 210 of 2014 dated 12/06/2014.",
                "The deed was presented for registration on 20/07/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000103",
                "Survey No: 704. Total area: 1500 sq ft.",
                "Boundaries:",
                "North: Sector Road",
                "East: Plot 3",
                "South: Pathway",
                "West: Plot 1",
                "",
                "Sale consideration: Rs 9,00,000 paid in full.",
                "Stamp duty paid: Rs 54,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "710/2022",
            "execution_date": "2022-07-10", "presentation_date": "2022-07-20",
            "seller.name": "Pradeep Das", "seller.relation_name": "Biren Das",
            "buyer.name": "Sanjay Gupta", "buyer.relation_name": "M.L. Gupta",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000103", "property.survey_no": "704",
            "property.area_value": 1500, "property.area_unit": "sqft",
            "property.boundaries.N": "Sector Road", "property.boundaries.E": "Plot 3",
            "property.boundaries.S": "Pathway", "property.boundaries.W": "Plot 1",
            "parent_ref.doc_ref": "Deed No. 210 of 2014", "parent_ref.claimed_acquisition_year": 2014,
            "consideration": 900000, "stamp_duty": 54000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 710/2022",
            "_quote_execution_date": "executed on 10/07/2022",
            "_quote_presentation_date": "presented for registration on 20/07/2022",
            "_quote_seller.name": "SELLER: Pradeep Das",
            "_quote_buyer.name": "BUYER: Sanjay Gupta",
            "_quote_parent_ref.doc_ref": "Deed No. 210 of 2014",
            "_quote_property.ulpin": "ULPIN: AS000000000103",
            "_quote_property.area_value": "1500 sq ft",
            "_quote_property.area_unit": "1500 sq ft",
            "_quote_property.boundaries.N": "North: Sector Road",
            "_quote_property.boundaries.E": "East: Plot 3",
            "_quote_property.boundaries.S": "South: Pathway",
            "_quote_property.boundaries.W": "West: Plot 1",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P5: Boundary differs from parent -> B4
    # -------------------------------------------------------------------------
    {
        "doc_id": "P5-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 330/2012      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/09/2012 between:",
                "SELLER: Chennai Corp, through authorised signatory S. Raman.",
                f"Identity proof: Aadhaar {_fake_aadhaar('501')}.",
                "BUYER: Sneha Reddy, daughter of K.V. Reddy, resident of Guwahati.",
                "The deed was presented for registration on 20/09/2012.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000105",
                "Survey No: 805. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: Public Road",
                "East: Plot 6",
                "South: Avenue 2",
                "West: Plot 4",
                "",
                "Sale consideration: Rs 4,00,000 paid in full.",
                "Stamp duty paid: Rs 24,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "330/2012",
            "execution_date": "2012-09-10", "presentation_date": "2012-09-20",
            "seller.name": "Chennai Corp", "seller.relation_name": "S. Raman",
            "buyer.name": "Sneha Reddy", "buyer.relation_name": "K.V. Reddy",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000105", "property.survey_no": "805",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "Public Road", "property.boundaries.E": "Plot 6",
            "property.boundaries.S": "Avenue 2", "property.boundaries.W": "Plot 4",
            "consideration": 400000, "stamp_duty": 24000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 330/2012",
            "_quote_execution_date": "executed on 10/09/2012",
            "_quote_presentation_date": "presented for registration on 20/09/2012",
            "_quote_seller.name": "SELLER: Chennai Corp",
            "_quote_buyer.name": "BUYER: Sneha Reddy",
            "_quote_property.ulpin": "ULPIN: AS000000000105",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: Public Road",
            "_quote_property.boundaries.E": "East: Plot 6",
            "_quote_property.boundaries.S": "South: Avenue 2",
            "_quote_property.boundaries.W": "West: Plot 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P5-D2",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 820/2022      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 15/08/2022 between:",
                "SELLER: Sneha Reddy, daughter of K.V. Reddy, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('502')}.",
                "BUYER: Manisha Iyer, wife of S. Iyer, resident of Guwahati.",
                "The seller acquired the property by Deed No. 330 of 2012 dated 10/09/2012.",
                "The deed was presented for registration on 25/08/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000105",
                "Survey No: 805. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: Canal and Waterway",
                "East: Plot 6",
                "South: Avenue 2",
                "West: Plot 4",
                "",
                "Sale consideration: Rs 7,00,000 paid in full.",
                "Stamp duty paid: Rs 42,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "820/2022",
            "execution_date": "2022-08-15", "presentation_date": "2022-08-25",
            "seller.name": "Sneha Reddy", "seller.relation_name": "K.V. Reddy",
            "buyer.name": "Manisha Iyer", "buyer.relation_name": "S. Iyer",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000105", "property.survey_no": "805",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "Canal and Waterway", "property.boundaries.E": "Plot 6",
            "property.boundaries.S": "Avenue 2", "property.boundaries.W": "Plot 4",
            "parent_ref.doc_ref": "Deed No. 330 of 2012", "parent_ref.claimed_acquisition_year": 2012,
            "consideration": 700000, "stamp_duty": 42000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 820/2022",
            "_quote_execution_date": "executed on 15/08/2022",
            "_quote_presentation_date": "presented for registration on 25/08/2022",
            "_quote_seller.name": "SELLER: Sneha Reddy",
            "_quote_buyer.name": "BUYER: Manisha Iyer",
            "_quote_parent_ref.doc_ref": "Deed No. 330 of 2012",
            "_quote_property.ulpin": "ULPIN: AS000000000105",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: Canal and Waterway",
            "_quote_property.boundaries.E": "East: Plot 6",
            "_quote_property.boundaries.S": "South: Avenue 2",
            "_quote_property.boundaries.W": "West: Plot 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P6: Seller via attorney, no POA reg no -> A1
    # -------------------------------------------------------------------------
    {
        "doc_id": "P6-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 440/2018      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 12/03/2018 between:",
                "SELLER: K. Rajan, son of S. Rajan, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('601')}.",
                "BUYER: Priya Nair, wife of M. Nair, resident of Guwahati.",
                "The deed was presented for registration on 20/03/2018.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000107",
                "Survey No: 906. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: East Road",
                "East: Plot 9",
                "South: Common Lane",
                "West: Plot 11",
                "",
                "Sale consideration: Rs 5,00,000 paid in full.",
                "Stamp duty paid: Rs 30,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "440/2018",
            "execution_date": "2018-03-12", "presentation_date": "2018-03-20",
            "seller.name": "K. Rajan", "seller.relation_name": "S. Rajan",
            "buyer.name": "Priya Nair", "buyer.relation_name": "M. Nair",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000107", "property.survey_no": "906",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "East Road", "property.boundaries.E": "Plot 9",
            "property.boundaries.S": "Common Lane", "property.boundaries.W": "Plot 11",
            "consideration": 500000, "stamp_duty": 30000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 440/2018",
            "_quote_execution_date": "executed on 12/03/2018",
            "_quote_presentation_date": "presented for registration on 20/03/2018",
            "_quote_seller.name": "SELLER: K. Rajan",
            "_quote_buyer.name": "BUYER: Priya Nair",
            "_quote_property.ulpin": "ULPIN: AS000000000107",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: East Road",
            "_quote_property.boundaries.E": "East: Plot 9",
            "_quote_property.boundaries.S": "South: Common Lane",
            "_quote_property.boundaries.W": "West: Plot 11",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P6-D2",
        "lang": "en",
        "has_scan": True,
        "lines": [
            [
                "SALE DEED",
                "Registration No: 930/2022      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/09/2022 between:",
                "SELLER: Priya Nair, wife of M. Nair, resident of Guwahati, acting through her",
                "duly appointed attorney Amit Joshi under a General Power of Attorney.",
                f"Identity proof: Aadhaar {_fake_aadhaar('602')}.",
                "BUYER: Tarun Das, son of B. Das, resident of Guwahati.",
                "The seller acquired the property by Deed No. 440 of 2018 dated 12/03/2018.",
                "The deed was presented for registration on 20/09/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000107",
                "Survey No: 906. Total area: 1000 sq ft.",
                "Boundaries:",
                "North: East Road",
                "East: Plot 9",
                "South: Common Lane",
                "West: Plot 11",
                "",
                "Sale consideration: Rs 8,00,000 paid in full.",
                "Stamp duty paid: Rs 48,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "930/2022",
            "execution_date": "2022-09-10", "presentation_date": "2022-09-20",
            "seller.name": "Priya Nair", "seller.relation_name": "M. Nair",
            "buyer.name": "Tarun Das", "buyer.relation_name": "B. Das",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": True, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000107", "property.survey_no": "906",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "East Road", "property.boundaries.E": "Plot 9",
            "property.boundaries.S": "Common Lane", "property.boundaries.W": "Plot 11",
            "parent_ref.doc_ref": "Deed No. 440 of 2018", "parent_ref.claimed_acquisition_year": 2018,
            "consideration": 800000, "stamp_duty": 48000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 930/2022",
            "_quote_execution_date": "executed on 10/09/2022",
            "_quote_presentation_date": "presented for registration on 20/09/2022",
            "_quote_seller.name": "SELLER: Priya Nair",
            "_quote_buyer.name": "BUYER: Tarun Das",
            "_quote_acting_through_poa.is_attorney": "acting through her duly appointed attorney Amit Joshi",
            "_quote_parent_ref.doc_ref": "Deed No. 440 of 2018",
            "_quote_property.ulpin": "ULPIN: AS000000000107",
            "_quote_property.area_value": "1000 sq ft",
            "_quote_property.area_unit": "1000 sq ft",
            "_quote_property.boundaries.N": "North: East Road",
            "_quote_property.boundaries.E": "East: Plot 9",
            "_quote_property.boundaries.S": "South: Common Lane",
            "_quote_property.boundaries.W": "West: Plot 11",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P7: Gap explained by succession document (DECOY) -> no B1
    # -------------------------------------------------------------------------
    {
        "doc_id": "P7-D1",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 150/2005      Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/04/2005 between:",
                "SELLER: Kamal Nath, son of P. Nath, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('701')}.",
                "BUYER: Late Harish Chandra, son of N. Chandra, resident of Guwahati.",
                "The deed was presented for registration on 20/04/2005.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000108",
                "Survey No: 1007. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Hill Road",
                "East: Plot 15",
                "South: Green Park",
                "West: Plot 13",
                "",
                "Sale consideration: Rs 2,00,000 paid in full.",
                "Stamp duty paid: Rs 12,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "150/2005",
            "execution_date": "2005-04-10", "presentation_date": "2005-04-20",
            "seller.name": "Kamal Nath", "seller.relation_name": "P. Nath",
            "buyer.name": "Late Harish Chandra", "buyer.relation_name": "N. Chandra",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000108", "property.survey_no": "1007",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Hill Road", "property.boundaries.E": "Plot 15",
            "property.boundaries.S": "Green Park", "property.boundaries.W": "Plot 13",
            "consideration": 200000, "stamp_duty": 12000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 150/2005",
            "_quote_execution_date": "executed on 10/04/2005",
            "_quote_presentation_date": "presented for registration on 20/04/2005",
            "_quote_seller.name": "SELLER: Kamal Nath",
            "_quote_buyer.name": "BUYER: Late Harish Chandra",
            "_quote_property.ulpin": "ULPIN: AS000000000108",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Hill Road",
            "_quote_property.boundaries.E": "East: Plot 15",
            "_quote_property.boundaries.S": "South: Green Park",
            "_quote_property.boundaries.W": "West: Plot 13",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P7-D2",
        "lang": "en",
        "lines": [
            [
                "SUCCESSION CERTIFICATE / DEED OF SUCCESSION",
                "Registration No: SC-2018-44     Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Succession is recorded on 12/11/2018:",
                "DECEASED / PREVIOUS OWNER: Late Harish Chandra, son of N. Chandra.",
                "LEGAL HEIR / BENEFICIARY: Gopal Chandra, son of Late Harish Chandra.",
                f"Identity proof of legal heir: Aadhaar {_fake_aadhaar('702')}.",
                "Pursuant to legal heir inquiry and registered succession declaration,",
                "full title and ownership devolves upon legal heir Gopal Chandra.",
                "Presented for registration on 20/11/2018.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000108",
                "Survey No: 1007. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Hill Road",
                "East: Plot 15",
                "South: Green Park",
                "West: Plot 13",
                "",
                "Transfer by inheritance / succession without monetary consideration.",
            ]
        ],
        "fields": {
            "doc_type": "succession", "registered": True, "registration_no": "SC-2018-44",
            "execution_date": "2018-11-12", "presentation_date": "2018-11-20",
            "seller.name": "Late Harish Chandra", "seller.relation_name": "N. Chandra",
            "buyer.name": "Gopal Chandra", "buyer.relation_name": "Late Harish Chandra",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000108", "property.survey_no": "1007",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Hill Road", "property.boundaries.E": "Plot 15",
            "property.boundaries.S": "Green Park", "property.boundaries.W": "Plot 13",
            "consideration": 0, "stamp_duty": 500,
            "_quote_doc_type": "SUCCESSION",
            "_quote_registration_no": "Registration No: SC-2018-44",
            "_quote_execution_date": "recorded on 12/11/2018",
            "_quote_presentation_date": "Presented for registration on 20/11/2018",
            "_quote_seller.name": "PREVIOUS OWNER: Late Harish Chandra",
            "_quote_buyer.name": "LEGAL HEIR / BENEFICIARY: Gopal Chandra",
            "_quote_property.ulpin": "ULPIN: AS000000000108",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Hill Road",
            "_quote_property.boundaries.E": "East: Plot 15",
            "_quote_property.boundaries.S": "South: Green Park",
            "_quote_property.boundaries.W": "West: Plot 13",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P7-D3",
        "lang": "en",
        "lines": [
            [
                "SALE DEED",
                "Registration No: 1050/2022     Sub-Registrar Office, Guwahati",
                "",
                "This Deed of Sale is executed on 10/10/2022 between:",
                "SELLER: Gopal Chandra, son of Late Harish Chandra, resident of Guwahati.",
                f"Identity proof: Aadhaar {_fake_aadhaar('703')}.",
                "BUYER: Bikash Roy, son of D. Roy, resident of Guwahati.",
                "The seller acquired the property by succession from Late Harish Chandra (SC-2018-44).",
                "The deed was presented for registration on 20/10/2022.",
            ],
            [
                "SCHEDULE OF PROPERTY",
                "ULPIN: AS000000000108",
                "Survey No: 1007. Total area: 1200 sq ft.",
                "Boundaries:",
                "North: Hill Road",
                "East: Plot 15",
                "South: Green Park",
                "West: Plot 13",
                "",
                "Sale consideration: Rs 9,50,000 paid in full.",
                "Stamp duty paid: Rs 57,000.",
            ]
        ],
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "1050/2022",
            "execution_date": "2022-10-10", "presentation_date": "2022-10-20",
            "seller.name": "Gopal Chandra", "seller.relation_name": "Late Harish Chandra",
            "buyer.name": "Bikash Roy", "buyer.relation_name": "D. Roy",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000108", "property.survey_no": "1007",
            "property.area_value": 1200, "property.area_unit": "sqft",
            "property.boundaries.N": "Hill Road", "property.boundaries.E": "Plot 15",
            "property.boundaries.S": "Green Park", "property.boundaries.W": "Plot 13",
            "parent_ref.doc_ref": "Deed No. 150 of 2005", "parent_ref.claimed_acquisition_year": 2018,
            "consideration": 950000, "stamp_duty": 57000,
            "_quote_doc_type": "SALE DEED",
            "_quote_registration_no": "Registration No: 1050/2022",
            "_quote_execution_date": "executed on 10/10/2022",
            "_quote_presentation_date": "presented for registration on 20/10/2022",
            "_quote_seller.name": "SELLER: Gopal Chandra",
            "_quote_buyer.name": "BUYER: Bikash Roy",
            "_quote_parent_ref.doc_ref": "Deed No. 150 of 2005",
            "_quote_property.ulpin": "ULPIN: AS000000000108",
            "_quote_property.area_value": "1200 sq ft",
            "_quote_property.area_unit": "1200 sq ft",
            "_quote_property.boundaries.N": "North: Hill Road",
            "_quote_property.boundaries.E": "East: Plot 15",
            "_quote_property.boundaries.S": "South: Green Park",
            "_quote_property.boundaries.W": "West: Plot 13",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },

    # -------------------------------------------------------------------------
    # P8: Hindi deed (Devanagari) -> B4 boundary mismatch
    # -------------------------------------------------------------------------
    {
        "doc_id": "P8-D1",
        "lang": "hi",
        "is_hindi": True,
        "html": f"""<!doctype html><html lang="hi"><head><meta charset="utf-8">
<style>body{{font-family:'Nirmala UI','Mangal',sans-serif;font-size:14pt;line-height:1.8;margin:40px}}
h1{{text-align:center;font-size:20pt}} .pb{{page-break-after:always}}</style></head><body>
<div class="pb">
<h1>विक्रय पत्र (बैनामा)</h1>
<p>पंजीकरण संख्या: 55/2015 &nbsp; उप-पंजीयक कार्यालय, लखनऊ।</p>
<p>दिनांक 10/06/2015 को निष्पादित:</p>
<p>विक्रेता: श्री दिनेश कुमार, पुत्र श्री राम कुमार, निवासी लखनऊ।</p>
<p>विक्रेता का पहचान प्रमाण: आधार {_fake_aadhaar('801')}।</p>
<p>क्रेता: श्री सुरेश वर्मा, पुत्र श्री प्रेम वर्मा, निवासी लखनऊ।</p>
<p>दिनांक 20/06/2015 को पंजीकरण हेतु प्रस्तुत किया गया।</p>
</div>
<div>
<h1>संपत्ति की अनुसूची</h1>
<p>ULPIN: AS000000000109</p>
<p>सर्वे नंबर 55, कुल क्षेत्रफल 1000 वर्ग फुट (sqft)।</p>
<p>चौहद्दी:<br>उत्तर: मुख्य मार्ग<br>पूर्व: भूखंड 2<br>दक्षिण: नाला<br>पश्चिम: भूखंड 4</p>
<p>विक्रय प्रतिफल: रुपये 3,50,000 पूर्ण भुगतान प्राप्त। स्टाम्प शुल्क: रुपये 21,000।</p>
</div></body></html>""",
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "55/2015",
            "execution_date": "2015-06-10", "presentation_date": "2015-06-20",
            "seller.name": "दिनेश कुमार", "seller.relation_name": "राम कुमार",
            "buyer.name": "सुरेश वर्मा", "buyer.relation_name": "प्रेम वर्मा",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000109", "property.survey_no": "55",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "मुख्य मार्ग", "property.boundaries.E": "भूखंड 2",
            "property.boundaries.S": "नाला", "property.boundaries.W": "भूखंड 4",
            "consideration": 350000, "stamp_duty": 21000,
            "_quote_doc_type": "विक्रय पत्र",
            "_quote_registration_no": "पंजीकरण संख्या: 55/2015",
            "_quote_execution_date": "10/06/2015",
            "_quote_presentation_date": "20/06/2015",
            "_quote_seller.name": "दिनेश कुमार",
            "_quote_buyer.name": "सुरेश वर्मा",
            "_quote_property.ulpin": "ULPIN: AS000000000109",
            "_quote_property.area_value": "1000 वर्ग फुट",
            "_quote_property.area_unit": "वर्ग फुट",
            "_quote_property.boundaries.N": "उत्तर: मुख्य मार्ग",
            "_quote_property.boundaries.E": "पूर्व: भूखंड 2",
            "_quote_property.boundaries.S": "दक्षिण: नाला",
            "_quote_property.boundaries.W": "पश्चिम: भूखंड 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
    {
        "doc_id": "P8-D2",
        "lang": "hi",
        "is_hindi": True,
        "has_scan": True,
        "html": f"""<!doctype html><html lang="hi"><head><meta charset="utf-8">
<style>body{{font-family:'Nirmala UI','Mangal',sans-serif;font-size:14pt;line-height:1.8;margin:40px}}
h1{{text-align:center;font-size:20pt}} .pb{{page-break-after:always}}</style></head><body>
<div class="pb">
<h1>विक्रय पत्र (बैनामा)</h1>
<p>पंजीकरण संख्या: 1160/2022 &nbsp; उप-पंजीयक कार्यालय, लखनऊ।</p>
<p>दिनांक 15/11/2022 को निष्पादित:</p>
<p>विक्रेता: श्री सुरेश वर्मा, पुत्र श्री प्रेम वर्मा, निवासी लखनऊ।</p>
<p>विक्रेता का पहचान प्रमाण: आधार {_fake_aadhaar('802')}।</p>
<p>क्रेता: श्री महेश शर्मा, पुत्र श्री आर. शर्मा, निवासी लखनऊ।</p>
<p>पूर्व विलेख संख्या 55/2015 दिनांक 10/06/2015 से प्राप्त।</p>
<p>दिनांक 25/11/2022 को पंजीकरण हेतु प्रस्तुत किया गया।</p>
</div>
<div>
<h1>संपत्ति की अनुसूची</h1>
<p>ULPIN: AS000000000109</p>
<p>सर्वे नंबर 55, कुल क्षेत्रफल 1000 वर्ग फुट (sqft)।</p>
<p>चौहद्दी:<br>उत्तर: नदी<br>पूर्व: भूखंड 2<br>दक्षिण: नाला<br>पश्चिम: भूखंड 4</p>
<p>विक्रय प्रतिफल: रुपये 7,50,000 पूर्ण भुगतान प्राप्त। स्टाम्प शुल्क: रुपये 45,000।</p>
</div></body></html>""",
        "fields": {
            "doc_type": "sale_deed", "registered": True, "registration_no": "1160/2022",
            "execution_date": "2022-11-15", "presentation_date": "2022-11-25",
            "seller.name": "सुरेश वर्मा", "seller.relation_name": "प्रेम वर्मा",
            "buyer.name": "महेश शर्मा", "buyer.relation_name": "आर. शर्मा",
            "party.id_type": "aadhaar", "acting_through_poa.is_attorney": False, "acting_through_poa.poa_reg_no": None,
            "property.ulpin": "AS000000000109", "property.survey_no": "55",
            "property.area_value": 1000, "property.area_unit": "sqft",
            "property.boundaries.N": "नदी", "property.boundaries.E": "भूखंड 2",
            "property.boundaries.S": "नाला", "property.boundaries.W": "भूखंड 4",
            "parent_ref.doc_ref": "55/2015", "parent_ref.claimed_acquisition_year": 2015,
            "consideration": 750000, "stamp_duty": 45000,
            "_quote_parent_ref.doc_ref": "55/2015",
            "_quote_doc_type": "विक्रय पत्र",
            "_quote_registration_no": "पंजीकरण संख्या: 1160/2022",
            "_quote_execution_date": "15/11/2022",
            "_quote_presentation_date": "25/11/2022",
            "_quote_seller.name": "सुरेश वर्मा",
            "_quote_buyer.name": "महेश शर्मा",
            "_quote_property.ulpin": "ULPIN: AS000000000109",
            "_quote_property.area_value": "1000 वर्ग फुट",
            "_quote_property.area_unit": "वर्ग फुट",
            "_quote_property.boundaries.N": "उत्तर: नदी",
            "_quote_property.boundaries.E": "पूर्व: भूखंड 2",
            "_quote_property.boundaries.S": "दक्षिण: नाला",
            "_quote_property.boundaries.W": "पश्चिम: भूखंड 4",
            "_page_property.ulpin": 2, "_page_property.area_value": 2,
            "_page_property.boundaries.N": 2, "_page_property.boundaries.E": 2,
            "_page_property.boundaries.S": 2, "_page_property.boundaries.W": 2,
        }
    },
]


def main():
    raw_dir = Path("data/raw")
    mock_dir = Path("data/mock")
    ext_dir = Path("data/extracted")
    labels_file = Path("data/labels/extraction_labels.json")

    raw_dir.mkdir(parents=True, exist_ok=True)
    mock_dir.mkdir(parents=True, exist_ok=True)
    ext_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config(provider="mock")

    # Load existing extraction labels
    if labels_file.exists():
        ext_labels = json.loads(labels_file.read_text(encoding="utf-8"))
    else:
        ext_labels = []

    # Filter out any prior entries for our new doc IDs
    known_doc_ids = {d["doc_id"] for d in DOC_DEFINITIONS} | {f"{d['doc_id']}-scan" for d in DOC_DEFINITIONS if d.get("has_scan")}
    ext_labels = [x for x in ext_labels if x.get("doc_id") not in known_doc_ids]

    print(f"Generating planted-defect dataset ({len(DOC_DEFINITIONS)} base documents)...")

    for d in DOC_DEFINITIONS:
        doc_id = d["doc_id"]
        pdf_path = raw_dir / f"{doc_id}.pdf"

        # 1. Generate PDF
        if d.get("is_hindi"):
            _make_hindi_pdf(d["html"], pdf_path)
        else:
            _make_pdf(pdf_path, d["lines"])
        print(f"  [PDF] Wrote {pdf_path}")

        # 2. Write canned model reply
        reply_json = _build_model_reply(d["fields"], pdf_path, lang=d.get("lang", "en"))
        mock_file = mock_dir / f"{doc_id}.json"
        mock_file.write_text(reply_json, encoding="utf-8")
        print(f"  [MOCK] Wrote {mock_file}")

        # 3. Add to extraction labels
        pure_fields = {k: v for k, v in d["fields"].items() if not k.startswith("_")}
        ext_labels.append({
            "doc_id": doc_id,
            "condition": "clean",
            "language": d.get("lang", "en"),
            "fields": pure_fields
        })

        # 4. Run extraction pipeline with MockProvider to create data/extracted/<doc_id>.json
        extract_deed(pdf_path, doc_id=doc_id, cfg=cfg, force=True, save=True)
        print(f"  [EXTRACTED] Saved extraction for {doc_id}")

        # 5. Handle degraded scan if specified
        if d.get("has_scan"):
            scan_id = f"{doc_id}-scan"
            scan_pdf = raw_dir / f"{scan_id}.pdf"
            _make_scan(pdf_path, scan_pdf)
            print(f"  [SCAN PDF] Wrote {scan_pdf}")

            # Scan model reply uses the same canned response
            scan_mock_file = mock_dir / f"{scan_id}.json"
            scan_mock_file.write_text(reply_json, encoding="utf-8")
            print(f"  [SCAN MOCK] Wrote {scan_mock_file}")

            ext_labels.append({
                "doc_id": scan_id,
                "condition": "degraded",
                "language": d.get("lang", "en"),
                "fields": pure_fields
            })

            extract_deed(scan_pdf, doc_id=scan_id, cfg=cfg, force=True, save=True)
            print(f"  [SCAN EXTRACTED] Saved extraction for {scan_id}")

    # Write updated extraction_labels.json
    labels_file.write_text(json.dumps(ext_labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Updated {labels_file} with {len(ext_labels)} total document labels.")
    print("Dataset generation complete!")


if __name__ == "__main__":
    main()
