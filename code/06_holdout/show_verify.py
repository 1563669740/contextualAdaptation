import json
import os

p = os.path.join(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests",
                 "python-babel__babel-1120", "verification.json")
d = json.load(open(p, encoding="utf-8"))
for lab in ("base", "gold"):
    r = d["attempts"][lab][0]
    print(f"--- {lab} rc={r['rc']} | {r['summary']}")
    print("    applied:", [(a.get("patch"), a.get("applied")) for a in r["applied"]])
    print("    stdout tail:")
    print(r["stdout_tail"][-1200:])
    print()
