import json
import os
import re

p = os.path.join(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests",
                 "python-babel__babel-1120", "verification.json")
d = json.load(open(p, encoding="utf-8"))
for lab in ("base", "gold"):
    r = d["attempts"][lab][0]
    print(f"===== {lab}  rc={r['rc']} | {r['summary']}")
    out = r["stdout_tail"]
    for line in out.splitlines():
        if line.startswith("FAILED") or line.startswith("PASSED") or "assert" in line:
            print("   ", line[:160])
    print()
