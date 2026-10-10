"""
End-to-end demo of P1 -> P2 on real extractions, using a throwaway ledger so P2's DB is untouched.
    python -m scripts.demo_flow                (uses data/extracted/SAMPLE-1.json)
It prints: flags with evidence, the advocate brief (written to the temp folder), the signed
ledger entry, a verification, then a tamper test.
"""

import os
import sqlite3
import tempfile

import ledger.audit_log as al
import ledger.signing as sg
from extract.cache import load_extraction
from extract.config import Config
from extract.request_list import build_request_list
from integration import commit_to_ledger, run_risk_analysis
from rules.advocate_brief import build_brief

tmp = tempfile.mkdtemp()
al.DB_PATH = os.path.join(tmp, "demo.db")
sg.KEY_PATH = type(sg.KEY_PATH)(tmp) / "key.pem"
os.environ.setdefault("LANDGUARD_COMMIT_SALT", "demo-salt")

ex = load_extraction(Config.from_env(), "SAMPLE-1")
res = run_risk_analysis(ex, [])
print("== FLAGS ==")
for k in ("class_a_flags", "class_b_flags", "needs_review"):
    for f in res[k]:
        ev = f["evidence"][0] if f.get("evidence") else {}
        print(f"{f['flag_id']:3} {f['code']:28} page={ev.get('page')} quote={str(ev.get('quote'))[:50]!r}")

brief = build_brief(res, build_request_list(ex))
brief_path = os.path.join(tmp, "advocate_brief.md")
open(brief_path, "w", encoding="utf-8").write(brief)
print(f"\n== advocate brief built from the static library (no LLM): {brief_path} ==")

flags = res["class_a_flags"] + res["class_b_flags"]
disp = {f["flag_id"]: {"action": "RETURN_FOR_CORRECTION" if f["class"] == "A" else "PARTIES_INFORMED",
                       "reason": "recorded for demo"} for f in flags}
out = commit_to_ledger("AS000000000104", ex, [], flags, disp, "MOCK-DSC-0001")
print("\n== LEDGER ==", {k: (str(v)[:18] + "..") if isinstance(v, str) else v for k, v in out.items()})
print("verify:", sg.verify_signatures())

c = sqlite3.connect(al.DB_PATH)
c.execute("UPDATE audit_log SET dispositions = '{}' WHERE idx = 1")
c.commit()
c.close()
print("after tampering with entry 1:", sg.verify_signatures())
