"""Pretty-print one extraction: python -m scripts.show_extraction SAMPLE-1"""

import json
import sys
from pathlib import Path

doc_id = sys.argv[1] if len(sys.argv) > 1 else "SAMPLE-1"
d = json.loads((Path("data/extracted") / f"{doc_id}.json").read_text(encoding="utf-8"))
p = d["provenance"]
print(f"model={p['model_version']} local_text={p['local_text']} method={p['extraction_method']} lang={d['language']}")
print(f"redaction={p['redaction']}")
print(f"warnings={p['warnings']}\n")
for k, f in d["fields"].items():
    v = f["value"] if f["status"] == "extracted" else f["candidate"]
    ev = f["evidence"]
    box = "Y" if ev["bbox"] else "N"
    print(f"{k:38} {f['status']:10} {f['confidence']:.2f}  {str(v)[:26]:26} p{ev['page']} bbox={box}  {'; '.join(f['notes'])}")
print("\nneeds_review:", d["needs_review"])
