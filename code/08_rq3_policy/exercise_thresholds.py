"""Exercise the threshold-selection machinery.

The real inputs are Discovery trajectories that do not exist yet.  This builds a
structurally faithful stand-in -- the real 120 Discovery tasks, their real
repository grouping, and the real feature schema -- so the cross-validation can
be shown to run, while being explicit that the numbers it produces on synthetic
labels are NOT research results.
"""
import csv
import json
import os
import random
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import online_policy as op

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
rows = list(csv.DictReader(open(os.path.join(ROOT, "splits",
                                             "discovery_tasks.csv"),
                                newline="", encoding="utf-8")))
print(f"real Discovery tasks: {len(rows)}")
repos = sorted({r["repo_id"] for r in rows})
print(f"real repositories   : {len(repos)}")

rng = random.Random(20260301)
cases = []
for r in rows:
    fam = rng.choice([2, 3, 4, 5])
    p1 = rng.random() < 0.30
    p2 = rng.random() < 0.22
    p4 = rng.random() < 0.60
    features = {
        "pre_task": {"repository_familiarity": fam,
                     "locatable": rng.random() < 0.7},
        "early_process": {"P1": {"fired": p1}, "P2": {"fired": p2},
                          "P3": {"fired": rng.random() < 0.2},
                          "P4": {"fired": p4},
                          "P5": {"fired": rng.random() < 0.12}},
    }
    # a stand-in "best fixed strategy"; real values come from fixed-policy runs
    if p4 and fam >= 4:
        best = "ai_led"
    elif p1 or p2:
        best = "shared_control"
    else:
        best = rng.choice(["ai_led", "shared_control", "human_led"])
    cases.append({"task_id": r["task_id"], "repo_id": r["repo_id"],
                  "features": features, "best_fixed": best})

out = op.select_thresholds(cases, k=5)
print(f"\nfold count          : {out['k']}")
print(f"repository groups   : {len(out['groups'])}")
print(f"cases               : {out['n_cases']}")
print("\ntop 3 threshold sets by routing agreement:")
for r in out["ranked"][:3]:
    print(f"  theta={r['theta']}")
    print(f"    mean routing agreement     = {r['mean_routing_agreement']:.4f}")
    print(f"    mean unnecessary escalation= {r['mean_unnecessary_escalation']:.4f}")
    print(f"    folds                      = {len(r['folds'])}")

# the point of the exercise: prove folds are repository-disjoint
folds = [set(out["groups"][i::out["k"]]) for i in range(out["k"])]
allg = set()
overlap = False
for f in folds:
    if allg & f:
        overlap = True
    allg |= f
print(f"\nfolds are repository-disjoint: {not overlap}")
print(f"all repositories covered     : {allg == set(out['groups'])}")

payload = dict(out)
payload.update({
    "generated_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "paper_reference": "Section VIII-B",
    "scope": "Discovery repositories only",
    "primary_criterion": "routing agreement",
    "secondary_criterion": "unnecessary escalation rate",
    "forbidden": "tuning on held-out repositories",
    "status": "MACHINERY_EXERCISED_ON_SYNTHETIC_LABELS",
    "NOT_A_RESULT": ("best_fixed here is synthesised, so these numbers are "
                     "not research findings. The deliverable is the "
                     "cross-validation machinery plus evidence that folds are "
                     "repository-disjoint. Replace the input with real "
                     "fixed-policy outcomes to obtain the frozen thresholds."),
})
json.dump(payload, open(os.path.join(ROOT, "policy",
                                     "threshold_selection.json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote policy/threshold_selection.json")
