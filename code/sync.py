#!/usr/bin/env python
"""Sync the reproduction code already present in the workspace into code/, by paper anchor (idempotent, copy only).

Why "copy" rather than "move"
------------------------------------------------
experiment_root/audit/freeze_manifest.json and splits/randomisation.json record the
tree digest of the reproduction artefacts and the SHA256 of the generator sources.
Moving experiment_root/tools/*.py away would directly change the content hash of the frozen manifest —— that frozen manifest is an already delivered, verifiable authoritative copy.
Therefore:

    authoritative copy = experiment_root/          (never modified: this script only reads)
    archive mirror     = code/                     (this script's write target)

For the edits still in progress in this workspace, sync.py is idempotent: rerun it at
any time and code/ is realigned with the current state of experiment_root, and the hashes in CODE_INDEX.json are updated.

Usage
----
    python code/sync.py                     # sync + write the file index
    python code/sync.py --check             # report differences only, write no files
    python code/sync.py --adopt-unmapped    # collect unmapped *_*.py into 99_scratch/_unmapped/
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

# Files created by hand by this script; they are not copies and take no part in hash comparison
AUTHORED = {
    "README.md", "code_map.json", "sync.py", "verify.py", "run.py",
    "requirements.txt", "CODE_INDEX.json", "CODE_INDEX.md",
}

# Search scope for unmapped scripts (paths relative to the workspace root)
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
    """Line-level adaptation: it must match exactly once, otherwise fail with an error rather than guess."""
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
                continue          # at the workspace root only temporary scripts such as _*.py are considered
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
            "role": "Unmapped: auto-adopted by sync.py (newly appeared temporary script)",
            "paper": "Not a paper artefact",
            "auto": True,
            "_bytes": raw,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report differences only, write no files")
    ap.add_argument("--adopt-unmapped", action="store_true",
                    help="copy unmapped temporary scripts into 99_scratch/_unmapped/")
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
        "schema": "project-code-index/1.0",
        "generated_utc": now(),
        "authoritative_root": m["authoritative"],
        "code_root": "code/",
        "note": [
            "code/ is a traceable archive mirror of experiment_root + the single entry point; the authoritative copy is always experiment_root.",
            "Files with byte_identical_to_source=false carry an adaptation field that states line by line what was changed.",
            "This directory takes no part in the frozen hashes of experiment_root, and tools/audit.py does not scan it.",
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
    L = ["# CODE_INDEX — code/ file index", "",
         f"Generated (UTC): `{index['generated_utc']}` · "
         f"Authoritative copy: `{index['authoritative_root']}/` · "
         f"This directory: `code/`", "",
         "> This file is generated by `code/sync.py`; do not edit it by hand.",
         "> For the full paper anchor ↔ file mapping see `code/README.md`.", ""]
    c = index["counts"]
    L += ["| Metric | Value |", "|---|---|",
          f"| Total files | {c['files']} |",
          f"| Byte-identical to source | {c['byte_identical']} |",
          f"| With explicit adaptation | {c['adapted']} |",
          f"| Auto-adopted (unmapped) | {c['auto_adopted']} |",
          f"| Groups | {c['groups']} |",
          f"| This sync | added {c['sync_added']} · updated {c['sync_updated']} · unchanged {c['sync_unchanged']} |",
          ""]
    by_path = {r["path"]: r for r in index["files"]}
    for g, v in sorted(index["groups"].items()):
        L += [f"## {g} ({v['n']})", "",
              "| # | File | Source | Bytes | SHA256(source) | Adaptation |", "|---|---|---|---|---|---|"]
        for i, path in enumerate(v["files"], 1):
            ref = by_path[path]
            p = path.split("/", 1)[1] if "/" in path else path
            L.append("| {} | `{}` | `{}` | {} | `{}…` | {} |".format(
                i, p, ref["source"], ref["bytes"],
                ref["source_sha256"][:12],
                "byte-identical" if ref["byte_identical_to_source"]
                else "`" + ref["adaptation"]["adapter"] + "`"))
        L.append("")
    if index.get("unmapped_not_copied"):
        L += ["## Unmapped, not copied (manual placement required)", ""]
        L += [f"- `{u}`" for u in index["unmapped_not_copied"]]
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
