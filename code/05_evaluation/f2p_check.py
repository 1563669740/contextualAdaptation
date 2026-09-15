import json
import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import task_env as te

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"

tid = "python-babel__babel-1120"
spec = json.load(open(os.path.join(ROOT, "evaluation_spec", tid + ".yaml"),
                      encoding="utf-8")) if False else None
import yaml
spec = yaml.safe_load(open(os.path.join(ROOT, "evaluation_spec", tid + ".yaml"),
                           encoding="utf-8"))
f2p = spec["fail_to_pass"]
print("F2P:", f2p)
tp = os.path.join(r"C:\Users\Administrator\Desktop\TIFS",
                  spec["test_patch_file"])
gp = os.path.join(r"C:\Users\Administrator\Desktop\TIFS", spec["gold_patch_file"])
print("test_patch:", tp, os.path.exists(tp))
print("gold_patch:", gp, os.path.exists(gp))

py = te.venv_python("python-babel/babel")


def scenario(label, patches, nodeids):
    wd, how = te.workspace(tid)
    applied = [te.apply_patch(wd, p) for p in patches]
    p = subprocess.run([py, "-m", "pytest", "-q", "--no-header", "-p",
                        "no:cacheprovider"] + nodeids,
                       cwd=wd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [l for l in p.stdout.splitlines() if l.strip()][-3:]
    print(f"\n=== {label} ({how}) rc={p.returncode} ===")
    print("patches:", applied)
    print("\n".join(tail))
    return p.returncode, p.stdout


# scenario 1: base + test patch only -> F2P must FAIL
rc1, out1 = scenario("base + test_patch", [tp], f2p)
# scenario 2: base + test patch + gold patch -> F2P must PASS
rc2, out2 = scenario("base + test_patch + gold", [tp, gp], f2p)
print("\nVERDICT: fails_at_base =", rc1 != 0, " passes_on_gold =", rc2 == 0)
