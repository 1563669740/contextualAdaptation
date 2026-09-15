import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

tid = "python-babel__babel-1120"
spec = ev.load_spec(tid)
f2p = spec["fail_to_pass"]
tp = ev.resolve_dataset_path(spec["test_patch_file"])
gp = ev.resolve_dataset_path(spec["gold_patch_file"])
py = te.venv_python("python-babel/babel")

wd, how = te.workspace(tid)
print("workspace:", wd)
for p in (tp, gp):
    print("apply", os.path.basename(p), te.apply_patch(wd, p))

# where does babel actually come from?
q = subprocess.run([py, "-c", "import babel, babel.core; print(babel.__file__); print(babel.core.__file__)"],
                   cwd=wd, capture_output=True, text=True)
print("babel module:", q.stdout.strip(), q.stderr.strip()[:200])

# does the workspace source contain the gold change?
core = open(os.path.join(wd, "babel", "messages", "pofile.py"), encoding="utf-8").read()
print("pofile.py has 'enclosed' logic:", "enclosed" in core.lower())
gold = open(gp, encoding="utf-8", errors="replace").read()
print("gold patch targets:", [l.split(" b/")[-1] for l in gold.splitlines() if l.startswith("diff --git")])

p = subprocess.run([py, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"] + f2p,
                   cwd=wd, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("\n--- full output ---")
print(p.stdout[-3500:])
print("--- stderr ---")
print(p.stderr[-800:])
