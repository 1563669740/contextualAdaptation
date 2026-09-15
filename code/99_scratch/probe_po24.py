import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
CODE = r'''
from io import BytesIO
from babel.messages.catalog import Catalog
from babel.messages import pofile
B=chr(0x2068); E=chr(0x2069)
def show(label, locs, width):
    c=Catalog(); c.add("foo", locations=locs)
    b=BytesIO(); pofile.write_po(b,c,omit_header=True,include_lineno=True,width=width)
    ls=[l for l in b.getvalue().decode().splitlines() if l.startswith("#:")]
    print("@@", label, repr(ls))
show("two@24", [(B+"x y.py"+E,1),(B+"p q.py"+E,2)], 24)
show("one@24", [(B+"only file.py"+E,42)], 24)
show("one@1",  [(B+"only file.py"+E,42)], 1)
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
    r = subprocess.run([py, "-c", CODE], cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    print("=====", lab)
    print(r.stdout.strip() or r.stderr[-400:])
