"""Probe candidate holdout behaviours for babel-1120, using only inputs the
public API actually accepts (integers for line numbers)."""
import os
import re as _re
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"

PROBE = r'''
from io import BytesIO
from babel.messages.catalog import Catalog
from babel.messages import pofile
from babel.util import wraptext
B = chr(0x2068); E = chr(0x2069)
cases = {}

def render(locs, width=1):
    c = Catalog()
    c.add("foo", locations=locs)
    b = BytesIO()
    pofile.write_po(b, c, omit_header=True, include_lineno=True, width=width)
    return b.getvalue().decode()

cases["A_two_locations"] = render([(B+"x y.py"+E, 1), (B+"p q.py"+E, 2)])
cases["B_one_location_lineno"] = render([(B+"only file.py"+E, 42)])
cases["C_wide_width"] = render([(B+"wide name.py"+E, 5)], width=200)
cases["D_no_enclosure"] = render([("plain.py", 7)])
cases["E_long_word"] = repr(wraptext("supercalifragilisticexpialidocious", width=10))
cases["F_wraptext_enclosed"] = repr(wraptext(B+"my long file.py"+E+":12", width=8))
cases["G_hyphenated"] = repr(wraptext(B+"a-b-c-file.py"+E+":7", width=6))
cases["H_plain_enclosed"] = repr(wraptext(B+"plain.py"+E+":1", width=4))
cases["I_two_enclosed_wrap"] = repr(wraptext(B+"one two.py"+E+":1 "+B+"three four.py"+E+":2", width=6))

for k in sorted(cases):
    print("###", k)
    print(cases[k])
'''

py = te.venv_python("python-babel/babel")
spec = ev.load_spec(TID)
gp = ev.resolve_dataset_path(spec["gold_patch_file"])


def run_at(label, patches):
    wd, _ = te.workspace(TID)
    for p in patches:
        te.apply_patch(wd, p)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run([py, "-c", PROBE], cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    if r.stderr.strip():
        print(f"[{label}] STDERR:", r.stderr[-400:])
    return r.stdout


def parse(t):
    out, cur = {}, None
    for line in t.splitlines():
        m = _re.match(r"### (\S+)", line)
        if m:
            cur = m.group(1); out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


pb = parse(run_at("BASE", []))
pg = parse(run_at("BASE+GOLD", [gp]))

print(f"cases probed: {len(pb)}")
print("\n=== cases that DIFFER between base and gold ===")
ndiff = 0
for k in sorted(set(pb) | set(pg)):
    if pb.get(k) != pg.get(k):
        ndiff += 1
        print(f"\n--- {k} ---")
        print("  BASE :", repr(pb.get(k))[:300])
        print("  GOLD :", repr(pg.get(k))[:300])
print(f"\n{ndiff} differing cases")
print("\n=== full base output ===")
for k in sorted(pb):
    print(f"--- {k} ---\n{pb[k]}")
