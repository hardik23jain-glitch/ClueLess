"""List every field that is wrong or unreadable against the labels. python -m scripts.eval_misses"""

import json
from pathlib import Path

from eval.eval_extraction import same
from extract.cache import load_extraction
from extract.config import Config
from extract.schema import FieldStatus

cfg = Config.from_env()
for lab in json.loads(Path("data/labels/extraction_labels.json").read_text(encoding="utf-8")):
    ex = load_extraction(cfg, lab["doc_id"])
    for k, truth in lab["fields"].items():
        f = ex.fields[k]
        if f.status == FieldStatus.UNREADABLE:
            print(f"{lab['doc_id']:24} {k:34} UNREADABLE cand={f.candidate!r} conf={f.confidence} notes={f.notes}")
        elif f.status == FieldStatus.EXTRACTED and not same(f.value, truth):
            print(f"{lab['doc_id']:24} {k:34} WRONG got={f.value!r} want={truth!r}")
        elif f.status == FieldStatus.ABSENT and truth is not None:
            print(f"{lab['doc_id']:24} {k:34} FALSE-ABSENT want={truth!r}")
