#!/usr/bin/env python
"""统一入口：在 code/ 里跑任何一个归档脚本，不改变脚本本身的定位方式。

为什么需要它
------------
副本全部依赖**绝对路径** ROOT = r"...\\TIFS\\experiment_root" 来读写数据，
因此复制到 code/ 之后仍然指向权威数据，这一点是好的。
但有跨模块 import 的脚本（simulate→online_policy/rq2_coding，
admission_gate/holdout_probe/holdout_author→task_env/evaluate）靠 sys.path
找兄弟模块，而 code/ 的目录分层和 experiment_root/{tools,evaluation} 不同。
本启动器把 code/ 的每个分组目录和 experiment_root 的三个源码目录都放进
sys.path，于是副本可以原样运行，不需要为了搬家而改任何一行逻辑。

用法
----
    python code/run.py --list
    python code/run.py 10_audit/audit.py
    python code/run.py audit.py --freeze
    python code/run.py 05_evaluation/aggregate_metrics.py
    python code/run.py 09_rq1_rq4_analysis/check_pipeline.py

注意：脚本的行为与在 experiment_root 下直接运行完全相同（同一 ROOT、同一数据），
它照旧会写 experiment_root 里的产物 —— code/ 只是入口，不是沙箱。
"""
from __future__ import annotations

import os
import runpy
import sys

# 不让 Python 在 code/ 里留下 __pycache__：本目录是归档镜像，
# 多出来的字节码会让 verify.py 的"归属检查"看上去像有陌生文件。
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
