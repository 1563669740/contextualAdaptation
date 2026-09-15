import json
import os
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import task_env as te

tid = "python-babel__babel-1120"
wd, how = te.workspace(tid)
print("workspace:", wd, "|", how)
print("files:", len(os.listdir(wd)))

py = te.venv_python("python-babel/babel")
p = subprocess.run([py, "-m", "pytest", "-q", "--no-header",
                    "tests/messages/test_pofile.py::test_iterable_of_strings"],
                   cwd=wd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print("rc:", p.returncode)
print("--- stdout ---")
print(p.stdout[-3000:])
print("--- stderr ---")
print(p.stderr[-2000:])

# what is importable?
for mod in ("babel", "pytz", "tzdata"):
    q = subprocess.run([py, "-c", f"import {mod}; print({mod}.__file__)"],
                       capture_output=True, text=True, errors="replace")
    print(f"{mod}: rc={q.returncode} {q.stdout.strip() or q.stderr.strip()[:120]}")
