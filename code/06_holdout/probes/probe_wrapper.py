"""Probe the exact behaviour of babel.util.TextWrapper and pofile output under
base and gold, so the holdout assertions describe reality rather than guesses."""
import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
PROBE = r'''
import inspect
from io import BytesIO
from babel.messages import pofile
from babel.messages.catalog import Catalog
import babel.util as bu
B = chr(0x2068); E = chr(0x2069)

print("### TextWrapper signature")
sig = inspect.signature(bu.TextWrapper.__init__)
print(sig)

def show(label, fn):
    try:
        print("###", label, "=>", repr(fn()))
    except Exception as ex:
        print("###", label, "=> EXC", type(ex).__name__, ex)

def wrap(text, width):
    w = bu.TextWrapper(width=width)
    return w.wrap(text)

show("W1_enclosed_width8", lambda: wrap(B+"my long file.py"+E+":12", 8))
show("W2_two_enclosed_width6", lambda: wrap(B+"one two.py"+E+":1 "+B+"three four.py"+E+":2", 6))
show("W3_two_enclosed_width40", lambda: wrap(B+"one two.py"+E+":1 "+B+"three four.py"+E+":2", 40))
show("W4_longword_width10", lambda: wrap("supercalifragilisticexpialidocious", 10))
show("W5_enclosed_width6", lambda: wrap(B+"a b.py"+E+":1", 6))
show("W6_plain_width10", lambda: wrap("plain.py:7", 10))
show("W7_enclosed_no_lineno", lambda: wrap(B+"a b.py"+E, 6))
show("W8_enclosed_superlong", lambda: wrap(B+"averyveryverylongfilename.py"+E+":1", 8))

def render(locs, width=1):
    c = Catalog(); c.add("foo", locations=locs)
    b = BytesIO(); pofile.write_po(b, c, omit_header=True, include_lineno=True, width=width)
    return b.getvalue().decode()

show("P1_one", lambda: render([(B+"only file.py"+E, 42)]))
show("P2_two", lambda: render([(B+"x y.py"+E, 1), (B+"p q.py"+E, 2)]))
show("P3_plain", lambda: render([("plain.py", 7)]))
show("P4_plain_two", lambda: render([("a.py", 1), ("b.py", 2)]))
show("P5_wide", lambda: render([(B+"x y.py"+E, 1)], width=200))
'''

py = te.venv_python("python-babel/babel")
spec = ev.load_spec(TID)
gp = ev.resolve_dataset_path(spec["gold_patch_file"])
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"


def run_at(label, patches):
    wd, _ = te.workspace(TID)
    for p in patches:
        te.apply_patch(wd, p)
    r = subprocess.run([py, "-c", PROBE], cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    if r.stderr.strip():
        print(f"[{label}] ERR:", r.stderr[-300:])
    return r.stdout


base = run_at("BASE", [])
gold = run_at("BASE+GOLD", [gp])
open(r"C:\Users\Administrator\Desktop\TIFS\_resp_base.txt", "w", encoding="utf-8").write(base)
open(r"C:\Users\Administrator\Desktop\TIFS\_resp_gold.txt", "w", encoding="utf-8").write(gold)

import re
def parse(t):
    out, cur = {}, None
    for line in t.splitlines():
        m = re.match(r"### (\S+)", line)
        if m:
            cur = m.group(1); out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}

pb, pg = parse(base), parse(gold)
print(f"probed {len(pb)} cases\n")
for k in sorted(set(pb) | set(pg)):
    same = pb.get(k) == pg.get(k)
    print(f"--- {k} {'(same)' if same else '(DIFFERS)'}")
    print("  BASE:", (pb.get(k) or "")[:220])
    if not same:
        print("  GOLD:", (pg.get(k) or "")[:220])
