import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
HD = os.path.join(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests", TID)
spec = ev.load_spec(TID)
tp = ev.resolve_dataset_path(spec["test_patch_file"])
gp = ev.resolve_dataset_path(spec["gold_patch_file"])
py = te.venv_python("python-babel/babel")
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

wd, _ = te.workspace(TID)
for p in (tp, gp, os.path.join(HD, "holdout.diff")):
    print("apply", os.path.basename(p), te.apply_patch(wd, p))

src = open(os.path.join(wd, "tests", "messages", "test_holdout_task.py"),
           encoding="utf-8").read()
print("\n=== installed Two test body ===")
i = src.find("def test_hd_two_enclosed")
print(src[i:i + 500])

r = subprocess.run([py, "-m", "pytest", "-q", "--no-header",
                    "-p", "no:cacheprovider",
                    "tests/messages/test_holdout_task.py",
                    "-k", "two_enclosed_locations_at_width_one"],
                   cwd=wd, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env)
print("\n=== test output ===")
print(r.stdout[-2500:])
