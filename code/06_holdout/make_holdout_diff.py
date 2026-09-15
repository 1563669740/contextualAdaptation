"""Build holdout.diff for a task from its tests_holdout_task.py and verify it.

The holdout suite is stored as a patch so that the evaluation harness applies it
exactly like any other change, keeping the harness blind to how many tests there
are and where they live.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation")
import task_env as te
import evaluate as ev

TID = "python-babel__babel-1120"
HD = os.path.join(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests", TID)
SRC = os.path.join(HD, "tests_holdout_task.py")
DEST_REL = "tests/messages/test_holdout_task.py"
DIFF = os.path.join(HD, "holdout.diff")


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


wd, how = te.workspace(TID)
print("workspace:", how)
dest = os.path.join(wd, DEST_REL.replace("/", os.sep))
os.makedirs(os.path.dirname(dest), exist_ok=True)
shutil.copy(SRC, dest)

rc = sh(["git", "add", "-A"], cwd=wd)
diff = sh(["git", "diff", "--cached", "--binary"], cwd=wd).stdout
if not diff.strip():
    diff = sh(["git", "diff", "--binary"], cwd=wd).stdout
open(DIFF, "w", encoding="utf-8", newline="\n").write(diff)
print(f"holdout.diff written: {len(diff)} bytes")

# verify the patch applies cleanly to a fresh workspace
wd2, _ = te.workspace(TID)
print("reapply:", te.apply_patch(wd2, DIFF))
print("tests present:", os.path.exists(
    os.path.join(wd2, DEST_REL.replace("/", os.sep))))
