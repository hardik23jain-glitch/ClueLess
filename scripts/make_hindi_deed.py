"""
Synthetic HINDI sale deed (Devanagari, Hindi digits, planted Aadhaar) + a scanned copy + its labels.

Edge (headless) renders the HTML so conjuncts are shaped correctly (Pillow/PyMuPDF text drawing
here cannot shape Devanagari). Outputs:
  data/raw/HINDI-1.pdf        digital PDF with a Hindi text layer
  data/raw/HINDI-1-scan.pdf   image-only scan (mild blur/tilt/noise): exercises Tesseract 'hin'
  data/labels/extraction_labels.json  += both entries (answers written here, from the text below)
Run: python -m scripts.make_hindi_deed
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import fitz

from extract.redact import verhoeff_check_digit
from scripts.make_degraded import degrade, render

EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)

base = "23456789012"
aadhaar = base + verhoeff_check_digit(base)
DEV = str.maketrans("0123456789", "०१२३४५६७८९")
aadhaar_dev = f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}".translate(DEV)

HTML = f"""<!doctype html><html lang="hi"><head><meta charset="utf-8">
<style>body{{font-family:'Nirmala UI','Mangal',sans-serif;font-size:15pt;line-height:1.9;margin:40px}}
h1{{text-align:center;font-size:22pt}} .pb{{page-break-after:always}}</style></head><body>
<div class="pb">
<h1>विक्रय पत्र (बैनामा)</h1>
<p>पंजीकरण संख्या: ४८२१/२०२१ &nbsp; उप-पंजीयक कार्यालय, कामरूप (महानगर), गुवाहाटी में पंजीकृत।</p>
<p>यह विक्रय पत्र दिनांक १२/०३/२०२१ को गुवाहाटी में निम्नलिखित पक्षकारों के मध्य निष्पादित किया गया:</p>
<p>विक्रेता: श्री रमेश कुमार, पुत्र श्री मोहन कुमार, निवासी बेलटोला, गुवाहाटी, जो अपने विधिवत नियुक्त मुख्तार श्री अनिल शर्मा के माध्यम से कार्य कर रहे हैं।</p>
<p>विक्रेता का पहचान प्रमाण: आधार {aadhaar_dev}।</p>
<p>क्रेता: श्रीमती सुनीता देवी, पत्नी श्री अनिल कुमार, निवासी दिसपुर, गुवाहाटी।</p>
<p>विक्रेता ने यह संपत्ति विलेख संख्या ११८७/२०१५ दिनांक ०४/०८/२०१५ द्वारा प्राप्त की थी।</p>
<p>यह विलेख दिनांक २०/०३/२०२१ को पंजीकरण हेतु प्रस्तुत किया गया।</p>
</div>
<div>
<h1>संपत्ति की अनुसूची</h1>
<p>सर्वे नंबर १२३, खाता संख्या ४५, ग्राम बेलटोला, गुवाहाटी। कुल क्षेत्रफल १२०० वर्ग फुट।</p>
<p>चौहद्दी:<br>उत्तर: सार्वजनिक सड़क<br>पूर्व: दिलीप दास की भूमि<br>दक्षिण: रीना बोरा की भूमि<br>पश्चिम: नाला</p>
<p>विक्रय प्रतिफल: रुपये ४,५०,००० (चार लाख पचास हज़ार रुपये मात्र) का पूर्ण भुगतान प्राप्त हुआ।</p>
<p>स्टाम्प शुल्क: रुपये ३१,५०० ई-स्टाम्प द्वारा भुगतान किया गया।</p>
<p>निष्पादक एवं गवाहों के हस्ताक्षर।</p>
</div></body></html>"""

LABEL_FIELDS = {
    "doc_type": "sale_deed", "registered": True, "registration_no": "4821/2021",
    "execution_date": "2021-03-12", "presentation_date": "2021-03-20",
    "seller.name": "रमेश कुमार", "seller.relation_name": "मोहन कुमार",
    "buyer.name": "सुनीता देवी", "buyer.relation_name": "अनिल कुमार",
    "party.id_type": "aadhaar", "acting_through_poa.is_attorney": True, "acting_through_poa.poa_reg_no": None,
    "property.ulpin": None, "property.survey_no": "123", "property.area_value": 1200, "property.area_unit": "sqft",
    "property.boundaries.N": "सार्वजनिक सड़क", "property.boundaries.E": "दिलीप दास की भूमि",
    "property.boundaries.S": "रीना बोरा की भूमि", "property.boundaries.W": "नाला",
    "parent_ref.claimed_acquisition_year": 2015, "consideration": 450000, "stamp_duty": 31500,
}


def main() -> None:
    if not EDGE:
        raise SystemExit("Microsoft Edge not found: needed to render Devanagari")
    tmp = Path(tempfile.mkdtemp())
    html = tmp / "hindi.html"
    html.write_text(HTML, encoding="utf-8")
    out = Path("data/raw/HINDI-1.pdf")
    subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={tmp / 'h.pdf'}", html.as_uri()], check=True, timeout=90,
                   capture_output=True)
    shutil.copy(tmp / "h.pdf", out)
    words = sum(len(p.get_text("words")) for p in fitz.open(str(out)))
    print(f"wrote {out} (text-layer words: {words}, pages: {fitz.open(str(out)).page_count})")

    doc = fitz.open()
    for img in [degrade(p, 3, 0.8, 6) for p in render(out)]:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        page = doc.new_page(width=img.shape[1] * 72 / 150, height=img.shape[0] * 72 / 150)
        page.insert_image(page.rect, stream=buf.tobytes())
    scan = Path("data/raw/HINDI-1-scan.pdf")
    doc.save(str(scan))
    print(f"wrote {scan} (image only). Planted Aadhaar (Devanagari digits): {aadhaar_dev}")

    lp = Path("data/labels/extraction_labels.json")
    labels = [x for x in json.loads(lp.read_text(encoding="utf-8")) if not x["doc_id"].startswith("HINDI-1")]
    for doc_id, cond in (("HINDI-1", "clean"), ("HINDI-1-scan", "degraded")):
        labels.append({"doc_id": doc_id, "condition": cond, "language": "hi", "fields": LABEL_FIELDS})
    lp.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print("labels updated:", len(labels), "documents")


if __name__ == "__main__":
    main()
