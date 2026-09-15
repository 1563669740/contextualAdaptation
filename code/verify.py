#!/usr/bin/env python
"""校验 code/ 与权威源 experiment_root/ 是否仍然一致（哈希 + 语法 + 归属）。

检查四件事：
  1. 每个副本的字节  ==  源文件字节（或 == 源文件套用 code_map.json 适配器后的字节）
  2. TARGET_DIVERGED  副本被就地改过（权威副本没变，镜像变了）
  3. SOURCE_CHANGED   源文件在上次 sync 之后被改过 —— 说明 experiment_root 有新的编辑，
                      code/ 需要重跑 sync.py 对齐（本脚本不会自动改，只报告）
  4. code/ 里出现了既不在 CODE_INDEX.json、也不是本次整理新建的 .py 文件

所有副本还会过一遍 ast.parse 语法检查（不写 .pyc，不执行任何业务逻辑）。

用法
----
    python code/verify.py            # 全部检查
    python code/verify.py --quiet    # 只打印问题
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TIFS = os.path.dirname(HERE)
INDEX_JSON = os.path.join(HERE, "CODE_INDEX.json")
MAP_PATH = os.path.join(HERE, "code_map.json")

AUTHORED = {
    "README.md", "code_map.json", "sync.py", "verify.py", "run.py",
    "requirements.txt", "CODE_INDEX.json", "CODE_INDEX.md",
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def apply_adapter(raw: bytes, adapter: dict, name: str) -> bytes:
    match = adapter["match"].encode("utf-8")
    repl = adapter["replace"].format(
        repo_cache=os.path.join(TIFS, "experiment_root", "repo_cache")).encode("utf-8")
    if raw.count(match) != 1:
        raise ValueError(f"adapter {name!r} no longer matches exactly once")
    return raw.replace(match, repl)


def all_py(root: str) -> list:
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(INDEX_JSON):
        print("CODE_INDEX.json not found -- run: python code/sync.py")
        return 2
    index = json.load(open(INDEX_JSON, encoding="utf-8"))
    adapters = json.load(open(MAP_PATH, encoding="utf-8")).get("adapters", {})

    ok = diverged = src_changed = missing = 0
    problems = []

    for r in index["files"]:
        src = os.path.join(TIFS, r["source"].replace("/", os.sep))
        dst = os.path.join(HERE, r["path"].replace("/", os.sep))

        if not os.path.isfile(dst):
            problems.append(f"MISSING TARGET   {r['path']}")
            missing += 1
            continue
        if not os.path.isfile(src):
            problems.append(f"MISSING SOURCE   {r['source']}  (target {r['path']} kept)")
            missing += 1
            continue

        raw = read_bytes(src)
        if sha256_bytes(raw) != r["source_sha256"]:
            problems.append(
                f"SOURCE_CHANGED   {r['source']}  "
                "-- experiment_root has newer edits; rerun sync.py")
            src_changed += 1

        expected = raw
        if r.get("adaptation"):
            try:
                expected = apply_adapter(raw, adapters[r["adaptation"]["adapter"]],
                                         r["adaptation"]["adapter"])
            except ValueError as exc:
                problems.append(f"ADAPTER_FAILED   {r['path']}: {exc}")
                continue

        if sha256_bytes(read_bytes(dst)) != sha256_bytes(expected):
            problems.append(f"TARGET_DIVERGED  {r['path']}  -- copy edited in place")
            diverged += 1
            continue
        ok += 1

    # 语法检查（纯解析，不执行、不写字节码）
    syntax_bad = 0
    for rel in all_py(HERE):
        p = os.path.join(HERE, rel)
        try:
            ast.parse(read_bytes(p).decode("utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append(f"SYNTAX_ERROR     {rel}: {exc}")
            syntax_bad += 1

    known = {r["path"] for r in index["files"]} | {
        "run.py", "sync.py", "verify.py"}
    extra = [p for p in all_py(HERE) if p not in known and os.path.basename(p) not in AUTHORED]
    for p in extra:
        problems.append(f"UNOWNED FILE     {p}  "
                        "-- not in CODE_INDEX.json and not authored here")

    print(f"code/ verify   authoritative={index['authoritative_root']}/   "
          f"(index built {index['generated_utc']})")
    print(f"  files checked  : {len(index['files'])}")
    print(f"  consistent     : {ok}")
    print(f"  source changed : {src_changed}")
    print(f"  target diverged: {diverged}")
    print(f"  missing        : {missing}")
    print(f"  syntax errors  : {syntax_bad}")
    print(f"  unowned files  : {len(extra)}")
    if problems:
        print("\nproblems:")
        for p in problems:
            print(f"  !! {p}")
        if src_changed and not (diverged or missing or syntax_bad or extra):
            print("\n  (SOURCE_CHANGED only: experiment_root has new edits -- "
                  "run `python code/sync.py` to realign)")
    elif not args.quiet:
        print("\n  OK: code/ is byte-identical to experiment_root, syntax clean")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
