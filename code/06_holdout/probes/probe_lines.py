import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
HD = os.path.join(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests", TID)
CODE = r'''
import io
from babel.messages import pofile
from babel.messages.catalog import Catalog
B=chr(0x2068); E=chr(0x2069)

def lines(locs, width):
    c=Catalog(); c.add("foo", locations=locs)
    b=io.BytesIO(); pofile.write_po(b,c,omit_header=True,include_lineno=True,width=width)
    return [l for l in b.getvalue().decode().splitlines() if l.startswith("#:")]

print("@@ two", repr(lines([(B+"x y.py"+E,1),(B+"p q.py"+E,2)], 1)))
print("@@ three", repr(lines([(B+"a b.py"+E,3),(B+"name with spaces.py"+E,11),("plain.py",5)], 1)))
print("@@ one42", repr(lines([(B+"only file.py"+E,42)], 1)))
print("@@ roomy", repr(lines([(B+"x y.py"+E,1),(B+"p q.py"+E,2)], 76)))
'''

py = te.venv_python("python-babel/babel")
spec = ev.load_spec(TID)
gp = ev.resolve_dataset_path(spec["gold_patch_file"])
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

for lab, patches in (("BASE", []), ("GOLD", [gp])):
    wd, _ = te.workspace(TID)
    for p in patches:
        te.apply_patch(wd, p)
    if lab == "GOLD":
        te.apply_patch(wd, os.path.join(HD, "holdout.diff"))
    r = subprocess.run([py, "-c", CODE], cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    print("=====", lab)
    for line in r.stdout.splitlines():
        print("  ", line)
