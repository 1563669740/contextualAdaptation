import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import online_policy as op

d = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\analysis\synthetic\sessions"
ex = op.OnlineExtractor()
sids = sorted(os.listdir(d))
fires = {"P1": 0, "P3": 0, "P4": 0}
n = 0
for s in sids:
    ev = [json.loads(l) for l in open(os.path.join(d, s, "events.jsonl"),
                                      encoding="utf-8") if l.strip()]
    sig = ex.extract(ev, planned_components=["src/module_1.py"])["signals"]
    n += 1
    for k in fires:
        if sig[k].get("fired"):
            fires[k] += 1
print(f"sessions={n}")
for k, v in fires.items():
    print(f"  {k}: {v/n:.4f}   (paper: P1 0.317, P3 0.242, P4 0.625)")
