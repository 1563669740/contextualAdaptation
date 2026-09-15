#!/usr/bin/env python
"""把 TIFS 工作区里已有的复现代码，按论文位置同步到 code/ 下（幂等，只复制）。

为什么是"复制"而不是"移动"
------------------------------------------------
experiment_root/audit/freeze_manifest.json 与 splits/randomisation.json 记录了
复现产物的 tree digest 与生成器源码 SHA256。把 experiment_root/tools/*.py 移走
会直接改变冻结包的内容哈希 —— 那份冻结包是已经交付的、可核验的权威副本。
所以：

    权威副本 = experiment_root/          （永不改动：本脚本只读）
    归档镜像 = code/                     （本脚本的写入目标）

对这个工作区里仍在进行的编辑，sync.py 是幂等的：任何时候重跑一次，
code/ 就重新对齐到 experiment_root 的当前状态，并更新 CODE_INDEX.json 里的哈希。

用法
----
    python code/sync.py                     # 同步 + 写索引
    python code/sync.py --check             # 只报告差异，不写任何文件
    python code/sync.py --adopt-unmapped    # 把未登记的 *_*.py 收进 99_scratch/_unmapped/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))          # .../TIFS/code
TIFS = os.path.dirname(HERE)                               # .../TIFS
MAP_PATH = os.path.join(HERE, "code_map.json")
INDEX_JSON = os.path.join(HERE, "CODE_INDEX.json")
INDEX_MD = os.path.join(HERE, "CODE_INDEX.md")

# 由本脚本手工新建、不作为副本参与哈希比对的文件
AUTHORED = {
    "README.md", "code_map.json", "sync.py", "verify.py", "run.py",
    "requirements.txt", "CODE_INDEX.json", "CODE_INDEX.md",
}

# 未登记脚本的搜索范围（相对 TIFS）
SCAN_DIRS = ["", "experiment_root", "experiment_root/tools",
             "experiment_root/evaluation", "experiment_root/repo_cache"]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def write_bytes(p: str, b: bytes) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(b)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_adapter(raw: bytes, adapter: dict, name: str) -> tuple[bytes, dict]:
    """行级适配：必须恰好命中一次，否则报错而不是猜。"""
    match = adapter["match"].encode("utf-8")
    repl = adapter["replace"].format(
        repo_cache=os.path.join(TIFS, "experiment_root", "repo_cache")
    ).encode("utf-8")
    n = raw.count(match)
    if n != 1:
        raise SystemExit(
            f"adapter {name!r} expected exactly 1 match, found {n} -- "
            "source changed; review the adapters section of code_map.json")
    out = raw.replace(match, repl)
    return out, {"adapter": name, "line": match.decode("utf-8"),
                 "replaced_with": repl.decode("utf-8"), "n_matches": n}


def mapped_sources(m: dict) -> set:
    return {os.path.normpath(e["source"]) for e in m["files"]}


def scan_unmapped(m: dict) -> list:
    known = mapped_sources(m)
    found = []
    for d in SCAN_DIRS:
        abs_d = os.path.join(TIFS, d) if d else TIFS
        if not os.path.isdir(abs_d):
            continue
        for fn in sorted(os.listdir(abs_d)):
            if not fn.endswith(".py"):
                continue
            if d == "" and not fn.startswith("_"):
                continue          # TIFS 根目录只看 _*.py 这类临时脚本
            rel = os.path.normpath(os.path.join(TIFS, d, fn)) if d \
                else os.path.normpath(os.path.join(TIFS, fn))
            rel = os.path.relpath(rel, TIFS)
            if rel not in known:
                found.append(rel)
    return found


def collect_unmapped_bodies(paths: list) -> list:
    out = []
    for rel in paths:
        src = os.path.join(TIFS, rel)
        if not os.path.isfile(src):
            continue
        raw = read_bytes(src)
        out.append({
            "source": rel.replace(os.sep, "/"),
            "target": "99_scratch/_unmapped/" + os.path.basename(rel),
            "role": "未登记：sync.py 自动收拢（新出现的临时脚本）",
            "paper": "非论文产物",
            "auto": True,
            "_bytes": raw,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="只报告差异，不写任何文件")
    ap.add_argument("--adopt-unmapped", action="store_true",
                    help="把未登记的临时脚本复制进 99_scratch/_unmapped/")
    args = ap.parse_args()

    m = json.load(open(MAP_PATH, encoding="utf-8"))
    adapters = m.get("adapters", {})
    entries, problems = [], []
    changed = added = same = 0

    work = [(e, None) for e in m["files"]]
    unmapped = scan_unmapped(m)
    if args.adopt_unmapped and unmapped:
        work += [(e, e.pop("_bytes")) for e in collect_unmapped_bodies(unmapped)]

    for e, preloaded in work:
        src_rel = e["source"]
        dst_rel = e["target"]
        src = os.path.join(TIFS, src_rel.replace("/", os.sep))
        dst = os.path.join(HERE, dst_rel.replace("/", os.sep))

        if preloaded is not None:
            raw = preloaded
        elif os.path.isfile(src):
            raw = read_bytes(src)
        else:
            problems.append(f"MISSING SOURCE  {src_rel}")
            continue

        src_sha = sha256_bytes(raw)

        adapt = None
        body = raw
        if e.get("adapter"):
            try:
                body, adapt = apply_adapter(raw, adapters[e["adapter"]], e["adapter"])
            except SystemExit as exc:
                problems.append(str(exc))
                continue

        dst_sha = sha256_bytes(body)
        old_sha = sha256_bytes(read_bytes(dst)) if os.path.isfile(dst) else None

        if old_sha is None:
            added += 1
        elif old_sha == dst_sha:
            same += 1
        else:
            changed += 1

        if not args.check:
            write_bytes(dst, body)

        rec = {
            "path": dst_rel,
            "source": src_rel,
            "bytes": len(body),
            "source_sha256": src_sha,
            "target_sha256": dst_sha,
            "byte_identical_to_source": adapt is None,
            "role": e.get("role", ""),
            "paper": e.get("paper", ""),
        }
        if e.get("note"):
            rec["note"] = e["note"]
        if adapt:
            rec["adaptation"] = adapt
        if e.get("auto"):
            rec["auto"] = True
        entries.append(rec)

    entries.sort(key=lambda r: r["path"])
    groups = {}
    for r in entries:
        groups.setdefault(r["path"].split("/")[0], []).append(r)

    index = {
        "schema": "tifs-code-index/1.0",
        "generated_utc": now(),
        "authoritative_root": m["authoritative"],
        "code_root": "code/",
        "note": [
            "code/ 是 experiment_root 的可追溯归档镜像 + 统一入口；权威副本始终是 experiment_root。",
            "byte_identical_to_source=false 的文件带 adaptation 字段，逐字说明改了什么。",
            "本目录不参与 experiment_root 的冻结哈希，也不被 tools/audit.py 扫描。",
        ],
        "counts": {
            "files": len(entries),
            "byte_identical": sum(1 for r in entries if r["byte_identical_to_source"]),
            "adapted": sum(1 for r in entries if not r["byte_identical_to_source"]),
            "auto_adopted": sum(1 for r in entries if r.get("auto")),
            "groups": len(groups),
            "sync_added": added, "sync_updated": changed, "sync_unchanged": same,
        },
        "groups": {g: {"n": len(v),
                       "files": [r["path"] for r in v]} for g, v in sorted(groups.items())},
        "unmapped_not_copied": [] if args.adopt_unmapped else unmapped,
        "files": entries,
    }

    if not args.check:
        with open(INDEX_JSON, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        with open(INDEX_MD, "w", encoding="utf-8") as fh:
            fh.write(render_md(index))

    print(f"code/ sync  {index['generated_utc']}   "
          f"{'CHECK ONLY' if args.check else 'written'}")
    print(f"  mapped files   : {len(entries)}"
          f"  (identical {index['counts']['byte_identical']}"
          f" / adapted {index['counts']['adapted']}"
          f" / auto {index['counts']['auto_adopted']})")
    print(f"  this run       : +{added} new, ~{changed} updated, ={same} unchanged")
    for g, v in sorted(groups.items()):
        print(f"    {g:<26} {len(v):>3} files")
    if unmapped:
        print(f"  unmapped ({len(unmapped)})"
              + (" -- copied to 99_scratch/_unmapped/" if args.adopt_unmapped
                 else " -- NOT copied (rerun with --adopt-unmapped):"))
        for u in unmapped:
            print(f"    ? {u}")
    for p in problems:
        print(f"  !! {p}")
    if not args.check:
        print(f"  wrote {os.path.relpath(INDEX_JSON, TIFS)}  and  "
              f"{os.path.relpath(INDEX_MD, TIFS)}")
    return 1 if problems else 0


def render_md(index: dict) -> str:
    L = ["# CODE_INDEX — code/ 文件索引", "",
         f"生成时间（UTC）：`{index['generated_utc']}`　·　"
         f"权威副本：`{index['authoritative_root']}/`　·　"
         f"本目录：`code/`", "",
         "> 本文件由 `code/sync.py` 生成，请勿手改。",
         "> 论文位置 ↔ 文件的完整对照另见 `code/README.md`。", ""]
    c = index["counts"]
    L += ["| 统计 | 值 |", "|---|---|",
          f"| 文件总数 | {c['files']} |",
          f"| 与源逐字节一致 | {c['byte_identical']} |",
          f"| 带显式适配 | {c['adapted']} |",
          f"| 自动收拢（未登记） | {c['auto_adopted']} |",
          f"| 分组 | {c['groups']} |",
          f"| 本次同步 | 新增 {c['sync_added']} · 更新 {c['sync_updated']} · 未变 {c['sync_unchanged']} |",
          ""]
    by_path = {r["path"]: r for r in index["files"]}
    for g, v in sorted(index["groups"].items()):
        L += [f"## {g}（{v['n']}）", "",
              "| # | 文件 | 源 | 字节 | SHA256(源) | 适配 |", "|---|---|---|---|---|---|"]
        for i, path in enumerate(v["files"], 1):
            ref = by_path[path]
            p = path.split("/", 1)[1] if "/" in path else path
            L.append("| {} | `{}` | `{}` | {} | `{}…` | {} |".format(
                i, p, ref["source"], ref["bytes"],
                ref["source_sha256"][:12],
                "逐字节一致" if ref["byte_identical_to_source"]
                else "`" + ref["adaptation"]["adapter"] + "`"))
        L.append("")
    if index.get("unmapped_not_copied"):
        L += ["## 未登记、未复制（需要人工归位）", ""]
        L += [f"- `{u}`" for u in index["unmapped_not_copied"]]
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
