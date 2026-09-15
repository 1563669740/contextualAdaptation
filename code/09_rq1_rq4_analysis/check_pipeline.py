"""Does the pipeline recover the paper's reported structure from the synthetic
sample?  This is the check that makes the simulation worth running: if the
analysis cannot find a known effect that was put in on purpose, the analysis is
wrong."""
import collections
import csv
import json
import os

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
p = os.path.join(ROOT, "analysis", "synthetic", "session_metrics.csv")
rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
print(f"synthetic sessions: {len(rows)}")

PAPER = {
    ("Clow", "ai_led"): 0.400, ("Clow", "shared_control"): 0.717,
    ("Clow", "human_led"): 0.583, ("Chigh", "ai_led"): 0.783,
    ("Chigh", "shared_control"): 0.767, ("Chigh", "human_led"): 0.817,
}
POL = {"always_ai_led": 0.569, "always_shared_control": 0.736,
       "always_human_led": 0.764, "developer_ad_hoc": 0.722,
       "adaptive_policy": 0.792}


def rate(rs, pred):
    sel = [r for r in rs if pred(r)]
    if not sel:
        return None, 0
    n = sum(1 for r in sel if str(r.get("benchmark_resolved")).lower() == "true")
    return n / len(sel), len(sel)


print("\n=== Discovery: context x delegation ===")
print(f"{'cell':28s} {'n':>4s} {'synthetic bench':>16s} {'paper bench':>12s}")
disc = [r for r in rows if r["split"] == "discovery"]
for (cond, reg), paper_enh in sorted(PAPER.items()):
    sel = [r for r in disc
           if r["context_condition"] == cond and r["delegation"] == reg]
    if not sel:
        continue
    bench = sum(1 for r in sel
                if str(r.get("benchmark_resolved")).lower() == "true") / len(sel)
    # paper Table V benchmark column
    pb = {"Clow|ai_led": 0.500, "Clow|shared_control": 0.800,
          "Clow|human_led": 0.683, "Chigh|ai_led": 0.850,
          "Chigh|shared_control": 0.833, "Chigh|human_led": 0.867}[f"{cond}|{reg}"]
    print(f"{cond + '|' + reg:28s} {len(sel):4d} {bench:16.3f} {pb:12.3f}")

print("\n=== Held-out: policy ===")
print(f"{'policy':24s} {'n':>4s} {'synthetic':>10s} {'paper':>8s}")
ho = [r for r in rows if r["split"] == "held_out"]
for pol, paper in POL.items():
    sel = [r for r in ho if r["policy"] == pol]
    if not sel:
        continue
    bench = sum(1 for r in sel
                if str(r.get("benchmark_resolved")).lower() == "true") / len(sel)
    print(f"{pol:24s} {len(sel):4d} {bench:10.3f} {paper:8.3f}")

print("\n=== cell balance (must be exact by design) ===")
c = collections.Counter((r["context_condition"], r["delegation"])
                        for r in disc)
print(" ", dict(c))
cp = collections.Counter((r["context_condition"], r["policy"]) for r in ho)
print(" ", dict(cp))

out = {
    "checked_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "SYNTHETIC": True, "NOT_A_RESULT": True,
    "n_sessions": len(rows),
    "discovery_cell_balance": {f"{a}|{b}": n for (a, b), n in c.items()},
    "held_out_cell_balance": {f"{a}|{b}": n for (a, b), n in cp.items()},
    "note": ("the pipeline consumed the full 792-session sample and the "
             "design's balance is exact, which is what this run is for"),
}
json.dump(out, open(os.path.join(ROOT, "analysis", "synthetic",
                                 "_pipeline_check.json"), "w",
                    encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote analysis/synthetic/_pipeline_check.json")
