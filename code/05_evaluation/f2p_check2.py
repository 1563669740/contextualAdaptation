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
print("test_patch ->", tp, os.path.exists(tp))
print("gold_patch ->", gp, os.path.exists(gp))

py = te.venv_python("python-babel/babel")


def scenario(label, patches, nodeids):
    wd, how = te.workspace(tid)
    applied = [te.apply_patch(wd, p) for p in patches]
    p = subprocess.run([py, "-m", "pytest", "-q", "--no-header", "-p",
                        "no:cacheprovider"] + nodeids,
                       cwd=wd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [l for l in p.stdout.splitlines() if l.strip()][-2:]
    print(f"\n=== {label} === rc={p.returncode} applied={[a.get('applied') for a in applied]}")
    print("\n".join(tail))
    return p.returncode


rc1 = scenario("base + test_patch", [tp], f2p)
rc2 = scenario("base + test_patch + gold", [tp, gp], f2p)
print(f"\nVERDICT  fails_at_base={rc1 != 0}  passes_on_gold={rc2 == 0}")
