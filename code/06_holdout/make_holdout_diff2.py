"""Build holdout.diff for any task that has tests_holdout_task.py."""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import task_env as te

HD_ROOT = r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests"


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build(task_id, dest_rel="tests/messages/test_holdout_task.py"):
    hd = os.path.join(HD_ROOT, task_id)
    src = os.path.join(hd, "tests_holdout_task.py")
    if not os.path.exists(src):
        return f"no test source for {task_id}"
    wd, how = te.workspace(task_id)
    dest = os.path.join(wd, dest_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy(src, dest)
    sh(["git", "add", "-A"], cwd=wd)
    diff = sh(["git", "diff", "--cached", "--binary"], cwd=wd).stdout
    if not diff.strip():
        diff = sh(["git", "diff", "--binary"], cwd=wd).stdout
    out = os.path.join(hd, "holdout.diff")
    open(out, "w", encoding="utf-8", newline="\n").write(diff)
    wd2, _ = te.workspace(task_id)
    ok = te.apply_patch(wd2, out).get("applied")
    return f"{task_id}: {len(diff)} bytes, reapply={ok} (source {how})"


if __name__ == "__main__":
    tids = sys.argv[1:]
    if not tids:
        tids = [d for d in sorted(os.listdir(HD_ROOT))
                if os.path.isdir(os.path.join(HD_ROOT, d))
                and os.path.exists(os.path.join(HD_ROOT, d,
                                                "tests_holdout_task.py"))]
    for t in tids:
        print(build(t))
