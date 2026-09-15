"""Find widths where base and gold genuinely differ, so the holdout assertions
describe real behaviour rather than my expectation of it."""
import os
import re
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
PROBE = r'''
from babel.util import TextWrapper
B = chr(0x2068); E = chr(0x2069)
texts = {
  "enclosed_space": B+"a b.py"+E+":1",
  "enclosed_long":  B+"my long file.py"+E+":12",
  "two_enclosed":   B+"one two.py"+E+":1 "+B+"three four.py"+E+":2",
  "plain":          "plain.py:7",
}
for name, t in texts.items():
    for w in (12, 16, 20, 24, 30, 40, 60, 76):
        try:
            out = TextWrapper(width=w).wrap(t)
        except Exception as ex:
            out = ["EXC:"+type(ex).__name__]
        print(f"@@@ {name}|{w}|{out!r}")
'''

py = te.venv_python("python-babel/babel")
spec = ev.load_spec(TID)
gp = ev.resolve_dataset_path(spec["gold_patch_file"])
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"


def run_at(patches):
    wd, _ = te.workspace(TID)
    for p in patches:
        te.apply_patch(wd, p)
    r = subprocess.run([py, "-c", PROBE], cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.stdout


def parse(t):
    out = {}
    for line in t.splitlines():
        if line.startswith("@@@ "):
            _, key, val = line.split("|", 2)
            name, w = line[4:].split("|")[0], line.split("|")[1]
            out[(name, int(w))] = val
    return out


pb = parse(run_at([]))
pg = parse(run_at([gp]))
print(f"probed {len(pb)} (text,width) combinations\n")
print("=== combinations where base and gold DIFFER ===")
for k in sorted(pb):
    if pb[k] != pg.get(k):
        print(f"\n{k[0]} width={k[1]}")
        print("  BASE:", pb[k][:200])
        print("  GOLD:", (pg.get(k) or "")[:200])
print("\n=== combinations where they AGREE (rejected as holdout material) ===")
for k in sorted(pb):
    if pb[k] == pg.get(k):
        print(f"  {k[0]:16s} w={k[1]:3d}  {pb[k][:110]}")
