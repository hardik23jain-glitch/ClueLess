"""Show where a cached raw model reply fails to parse: python -m scripts.show_raw DELHI-SALE"""

import json
import sys
from pathlib import Path

doc_id = sys.argv[1]
ex = json.loads((Path("data/extracted") / f"{doc_id}.json").read_text(encoding="utf-8"))
key = ex["provenance"]["cache_key"]
raw = (Path("data/cache") / f"{key}.json").read_text(encoding="utf-8")
print(f"cache_key={key} length={len(raw)}")
try:
    json.loads(raw, strict=False)
    print("parses fine")
except json.JSONDecodeError as e:
    print("ERROR:", e)
    lo = max(0, e.pos - 300)
    print("--- context before error ---")
    print(raw[lo:e.pos + 120])
print("--- tail ---")
print(raw[-200:])
