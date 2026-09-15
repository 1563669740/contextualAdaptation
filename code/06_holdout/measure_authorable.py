"""Measure the real authoring denominator: how many tasks can this environment
actually distinguish defect from fix?

Authoring a holdout suite only makes sense where the oracle is reproducible.
Three of six babel calibrations failed for exactly that reason, so the size of
the authorable set is an empirical question and worth measuring rather than
assuming.
"""
import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import evaluate as ev
import task_env as te

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
CAL = r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests\_calibration"

rows = []
for f in sorted(os.listdir(CAL)):
    if not f.endswith(".json"):
        continue
    d = json.load(open(os.path.join(CAL, f), encoding="utf-8"))
    v = (d.get("verdict") or {}).get("oracle_reproduced")
    bw = d.get("base_without_gold") or {}
    bg = d.get("base_with_gold") or {}
    rows.append({
        "task_id": d["task_id"], "oracle_reproduced": bool(v),
        "base_rc": bw.get("rc"), "gold_rc": bg.get("rc"),
        "base_summary": bw.get("summary"), "gold_summary": bg.get("summary"),
        "gold_files": len(d.get("gold_files") or []),
    })

ok = [r for r in rows if r["oracle_reproduced"]]
print(f"calibrated tasks      : {len(rows)}")
print(f"oracle reproduced     : {len(ok)}")
print(f"cannot reproduce      : {len(rows) - len(ok)}")
print()
for r in rows:
    mark = "OK  " if r["oracle_reproduced"] else "FAIL"
    print(f"  [{mark}] {r['task_id']:32s} base_rc={r['base_rc']} "
          f"gold_rc={r['gold_rc']}  {r['base_summary']} / {r['gold_summary']}")

print()
print("failure modes among the non-reproducible ones:")
for r in rows:
    if r["oracle_reproduced"]:
        continue
    if r["base_rc"] == r["gold_rc"] == 4:
        print(f"  {r['task_id']}: collection error in BOTH revisions "
              f"-- environment cannot run the frozen tests")
    elif r["gold_rc"] != 0:
        print(f"  {r['task_id']}: gold does not pass -- the gold patch is "
              f"partial or needs companions the eval harness does not apply")

json.dump({
    "measured_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "why": ("holdout authoring is only meaningful where the environment can "
            "distinguish defect from fix; this measures that denominator so "
            "the remaining work is scoped honestly"),
    "n_calibrated": len(rows), "n_authorable": len(ok),
    "tasks": rows,
}, open(os.path.join(ROOT, "audit", "holdout_feasibility.json"), "w",
        encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote audit/holdout_feasibility.json")
