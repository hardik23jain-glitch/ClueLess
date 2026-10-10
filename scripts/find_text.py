"""Show text around a phrase in a PDF: python scripts/find_text.py <pdf> "stamp duty" """

import re
import sys

import fitz

pdf, phrase = sys.argv[1], sys.argv[2]
doc = fitz.open(pdf)
for n, page in enumerate(doc, 1):
    t = " ".join(page.get_text().split())
    for m in re.finditer(re.escape(phrase), t, re.I):
        print(f"p{n}: ...{t[max(0, m.start() - 60): m.end() + 120]}...")
