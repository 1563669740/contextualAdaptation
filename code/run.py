#!/usr/bin/env python
"""Unified launcher: run any archived script from inside code/, without changing
how that script locates itself.

Why it is needed
----------------
Every copy relies on the **absolute path** ROOT = r"<repository root>\\experiment_root" to
read and write data, so after being copied into code/ it still points at the
authoritative data -- which is exactly what we want.
But scripts with cross-module imports (simulate→online_policy/rq2_coding,
admission_gate/holdout_probe/holdout_author→task_env/evaluate) rely on sys.path
to find their sibling modules, and the directory layout of code/ differs from
that of experiment_root/{tools,evaluation}.
This launcher puts every group directory of code/ and the three source
directories of experiment_root onto sys.path, so the copies run as-is and no
line of logic has to change just because they moved.

Usage
-----
    python code/run.py --list
    python code/run.py 10_audit/audit.py
    python code/run.py audit.py --freeze
    python code/run.py 05_evaluation/aggregate_metrics.py
    python code/run.py 09_rq1_rq4_analysis/check_pipeline.py

Note: a script behaves exactly as if it were run directly under
experiment_root (same ROOT, same data), and it still writes its artefacts into
experiment_root -- code/ is only an entry point, not a sandbox.
"""
from __future__ import annotations

import os
import runpy
import sys

# Keep Python from leaving __pycache__ inside code/: this directory is an
# archive mirror, and the extra bytecode would make the verify.py "ownership
# check" look as though unknown files had appeared.
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
TIFS = os.path.dirname(HERE)
EXP = os.path.join(TIFS, "experiment_root")


def code_dirs() -> list:
    dirs = []
    for name in sorted(os.listdir(HERE)):
        p = os.path.join(HERE, name)
        if os.path.isdir(p) and not name.startswith(("_", ".")):
            dirs.append(p)
            for sub in sorted(os.listdir(p)):
                sp = os.path.join(p, sub)
                if os.path.isdir(sp) and not sub.startswith(("_", ".")):
                    dirs.append(sp)
    return dirs


def resolve(target: str) -> str | None:
    cand = os.path.join(HERE, target.replace("/", os.sep))
    if os.path.isfile(cand):
        return cand
    hits = []
    for d in code_dirs():
        p = os.path.join(d, target)
        if os.path.isfile(p):
            hits.append(p)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        sys.stderr.write(f"ambiguous: {target} matches multiple files\n")
        for h in hits:
            sys.stderr.write("    " + os.path.relpath(h, TIFS) + "\n")
        return None
    return None


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] == "--list":
        for d in code_dirs():
            files = sorted(f for f in os.listdir(d) if f.endswith(".py"))
            if not files:
                continue
            print(os.path.relpath(d, HERE).replace(os.sep, "/") + "/")
            for f in files:
                print("    " + f)
        return 0

    target = sys.argv[1]
    script = resolve(target)
    if not script:
        sys.stderr.write(f"script not found: {target}  (try --list)\n")
        return 2

    sys.path[:0] = code_dirs() + [
        os.path.join(EXP, "tools"),
        os.path.join(EXP, "evaluation"),
        os.path.join(EXP, "repo_cache"),
    ]
    sys.argv = [script] + sys.argv[2:]
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
