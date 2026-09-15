"""Find tasks whose calibration gate passes, i.e. where the environment can
actually distinguish the defect from the fix.  Only those are worth authoring
holdout tests for."""
import json
import os
import sys
import traceback

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import holdout_author as ha
import evaluate as ev

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                     encoding="utf-8"))["tasks"]

# prefer repos whose venv already exists, smallest test suites first
repos = {}
for t in idx:
    repos.setdefault(t["repo_id"], []).append(t)

built = []
for repo in sorted(repos):
    slug = repo.replace("/", "__")
    if os.path.isdir(os.path.join(ROOT, "_envs", slug)):
        built.append(repo)
print("repos with a built venv:", built)

class A:
    pass

results = []
for repo in built:
    for t in repos[repo]:
        tid = t["task_id"]
        try:
            ha.cmd_calibrate(type("A", (), {"task_id": tid})())
            results.append((tid, "ok"))
        except SystemExit as e:
            results.append((tid, f"calibration_failed"))
        except Exception as e:
            results.append((tid, f"error:{type(e).__name__}"))
print()
for tid, st in results:
    print(f"  {tid:52s} {st}")
ok = [t for t, s in results if s == "ok"]
print(f"\nusable for authoring: {len(ok)}")
json.dump(ok, open(r"C:\Users\Administrator\Desktop\TIFS\_authorable.json", "w",
                   encoding="utf-8"), indent=1)
