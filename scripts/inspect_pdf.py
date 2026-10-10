"""Describe PDFs: pages, whether they have a text layer, and the first words. Paths are arguments."""

import sys

import fitz

for p in sys.argv[1:]:
    doc = fitz.open(p)
    words = sum(len(pg.get_text("words")) for pg in doc)
    first = " ".join(doc[0].get_text().split())[:160]
    print(f"{p}\n  pages={doc.page_count} words={words} text_layer={'yes' if words > 20 else 'NO (scanned)'}\n  starts: {first}\n")
