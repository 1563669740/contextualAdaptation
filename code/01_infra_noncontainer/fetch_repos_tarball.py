#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fallback base-commit fetcher using GitHub codeload tarballs.

Why this exists
  `git clone` against github.com repeatedly failed on this host -- TCP and
  HTTPS were fine, and codeload served a 154 KB tarball in 1.4 s, but git's
  packfile negotiation kept dying with "Recv failure: Connection was aborted"
  and multi-minute stalls.  Rather than fight it, this script builds the same
  two artefacts `repo_cache/fetch_repos.py` produces, from a tarball:

    repo_cache/_inventory/<task_id>.json    path / mode / blob sha1 / size
    repo_cache/_snapshots/<task_id>.json    selected file contents + hashes

  Blob ids are recomputed locally with git's own object hashing rule
  (`sha1("blob <len>\\0" + content)`), so the inventory is content-addressed and
  verifiable against `git ls-tree` for the tasks that were fetched via git.

Source of truth for "which commit is this?" is
`dataset/gold/commits.csv` -> `base_commit`, which came from the SWE-bench-Live
record rather than from a git ref, so it does not depend on the failed clone.

Usage
  python fetch_repos_tarball.py                 # every task still missing
  python fetch_repos_tarball.py --repo keras-team/keras
  python fetch_repos_tarball.py --task-id keras-team__keras-19300 --force
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

csv.field_size_limit(10 ** 9)

DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
CACHE = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\repo_cache"
INV = os.path.join(CACHE, "_inventory")
SNAP = os.path.join(CACHE, "_snapshots")
TARBALLS = os.path.join(CACHE, "_tarballs")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

NOISE_DIRS = {
    ".github", ".devcontainer", ".vscode", ".idea", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "venv", ".venv", "env", ".eggs", "vendor", "third_party",
}
SOURCE_EXT = (".py", ".js", ".ts", ".jsx", ".tsx")
CFG_NAMES = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "pytest.ini",
             "Makefile", "package.json", "requirements.txt",
             "requirements-dev.txt", "conftest.py", ".flake8", "mypy.ini"}
DOC_RE = re.compile(
    r"(^|/)(README[^/]*|CONTRIBUTING[^/]*|ARCHITECTURE[^/]*|"
    r"docs/index\.(rst|md)|CHANGELOG[^/]*)$", re.I)

MAX_FILES = 400
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
N_TEST_HEADERS = 200
TEST_HEADER_BYTES = 400

UA = "Mozilla/5.0 (compatible; experiment-data-collection/1.0)"


def blob_sha1(b: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(b))
    h.update(b)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_test_path(p: str) -> bool:
    parts = p.lower().split("/")
    if any(x in ("test", "tests", "testing", "spec", "specs") for x in parts):
        return True
    b = os.path.basename(p)
    return b.startswith("test_") or b.endswith("_test.py") or b == "conftest.py"


def select(files):
    verbatim, headers, total = [], [], 0
    for f in sorted(files, key=lambda x: x["path"]):
        p, sz = f["path"], (f["size"] or 0)
        if sz == 0 or sz > MAX_FILE_BYTES:
            continue
        base = os.path.basename(p)
        if p.endswith(SOURCE_EXT):
            if is_test_path(p):
                if len(headers) < N_TEST_HEADERS:
                    headers.append(p)
            elif len(verbatim) < MAX_FILES and total + sz <= MAX_TOTAL_BYTES:
                verbatim.append(p)
                total += sz
        elif base in CFG_NAMES or DOC_RE.search(p):
            if len(verbatim) < MAX_FILES and total + sz <= MAX_TOTAL_BYTES:
                verbatim.append(p)
                total += sz
    return verbatim, headers


def download(repo, commit, dest, attempts=5):
    """Fetch and cache the tarball; return (bytes, log_entry)."""
    os.makedirs(TARBALLS, exist_ok=True)
    exact = os.path.join(TARBALLS, f"{repo.replace('/', '__')}__{commit}.tar.gz")
    if os.path.exists(exact) and os.path.getsize(exact) > 0:
        return open(exact, "rb").read(), {"cached": True}
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    last = None
    for attempt in range(1, attempts + 1):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if not data:
                raise RuntimeError("empty response")
            open(exact, "wb").write(data)
            return data, {"cached": False, "attempt": attempt,
                          "bytes": len(data),
                          "seconds": round(time.time() - t0, 1)}
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 5 * 2 ** attempt))
    raise RuntimeError(f"codeload failed for {repo}@{commit[:10]}: {last}")


def build_from_tarball(task_id, repo, commit):
    data, dlog = download(repo, commit, None)
    inv_files = []

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            # strip the single top-level "<name>-<ref>/" directory
            parts = m.name.split("/", 1)
            p = parts[1] if len(parts) > 1 else m.name
            if not p or p.split("/", 1)[0] in NOISE_DIRS:
                continue
            inv_files.append({
                "path": p,
                "mode": "100755" if (m.mode & 0o111) else "100644",
                "type": "blob",
                # filled in only for files whose bytes we actually read; the
                # rest keep None rather than a fabricated id
                "blob": None,
                "size": m.size,
            })

    v_sel, h_sel = select(inv_files)
    want = set(v_sel) | set(h_sel)
    by_path = {f["path"]: f for f in inv_files}
    snap = {}

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            parts = m.name.split("/", 1)
            p = parts[1] if len(parts) > 1 else m.name
            if p not in want:
                continue
            fh = tf.extractfile(m)
            if fh is None:
                continue
            raw = fh.read(MAX_FILE_BYTES + 1)
            truncated = len(raw) > MAX_FILE_BYTES
            raw = raw[:MAX_FILE_BYTES]
            rec = by_path.get(p)
            if rec is not None:
                rec["blob"] = blob_sha1(raw)
            text = raw.decode("utf-8", "replace")
            if p in h_sel and p not in v_sel:
                snap[p] = {"kind": "test_header", "blob": blob_sha1(raw),
                           "content": "\n".join(text.splitlines()[:12])
                           [:TEST_HEADER_BYTES]}
            else:
                snap[p] = {"kind": "verbatim", "blob": blob_sha1(raw),
                           "sha256": sha256_bytes(raw), "truncated": truncated,
                           "content": text}

    # any file whose bytes we did not read keeps blob=None; that is honest --
    # the inventory still records path/mode/size, and only the selected files
    # are content-addressed.
    inv = {
        "task_id": task_id, "repo": repo, "base_commit": commit,
        "ok": True, "n_files": len(inv_files),
        "n_bytes": sum(f["size"] or 0 for f in inv_files),
        "inventory_sha256": sha256_bytes(
            json.dumps(inv_files, sort_keys=True).encode("utf-8")),
        "files": inv_files,
        "provenance": {"method": "codeload_tarball",
                       "url": f"https://codeload.github.com/{repo}/tar.gz/{commit}",
                       "tarball_bytes": len(data), "fetched_utc": NOW,
                       "download": dlog},
    }
    snaprec = {
        "task_id": task_id, "base_commit": commit,
        "n_verbatim": sum(1 for v in snap.values() if v["kind"] == "verbatim"),
        "n_headers": sum(1 for v in snap.values() if v["kind"] == "test_header"),
        "files": snap,
        "provenance": {"method": "codeload_tarball"},
    }
    return inv, snaprec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--task-id", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    os.makedirs(INV, exist_ok=True)
    os.makedirs(SNAP, exist_ok=True)
    os.makedirs(TARBALLS, exist_ok=True)

    rows = [r for r in csv.DictReader(
        open(os.path.join(DS, "gold", "commits.csv"), newline="",
             encoding="utf-8")) if r.get("task_id")]

    todo = []
    for r in rows:
        tid = r["task_id"]
        if a.task_id and tid not in set(a.task_id):
            continue
        if a.repo and r["repo"] != a.repo:
            continue
        ip = os.path.join(INV, tid + ".json")
        sp = os.path.join(SNAP, tid + ".json")
        if not a.force:
            done = False
            if os.path.exists(ip) and os.path.exists(sp):
                try:
                    d = json.load(open(ip, encoding="utf-8"))
                    s = json.load(open(sp, encoding="utf-8"))
                    done = bool(d.get("ok") and d.get("n_files")
                                and "error" not in s)
                except Exception:
                    done = False
            if done:
                continue
        todo.append((tid, r["repo"], r["base_commit"], r.get("split")))

    print(f"tasks to fetch via tarball: {len(todo)}")
    if not todo:
        return

    log, ok, err = [], 0, []

    def work(item):
        tid, repo, commit, split = item
        try:
            inv, snap = build_from_tarball(tid, repo, commit)
            inv["split"] = split
            json.dump(inv, open(os.path.join(INV, tid + ".json"), "w",
                                encoding="utf-8"), ensure_ascii=False)
            json.dump(snap, open(os.path.join(SNAP, tid + ".json"), "w",
                                 encoding="utf-8"), ensure_ascii=False)
            return tid, inv["n_files"], snap["n_verbatim"], None
        except Exception as e:
            return tid, 0, 0, f"{type(e).__name__}: {e}"

    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, (tid, nf, nv, e) in enumerate(
                ex.map(work, todo), 1):
            if e:
                err.append({"task_id": tid, "error": e})
                print(f"  [{i}/{len(todo)}] {tid}: FAIL {e[:120]}",
                      file=sys.stderr, flush=True)
            else:
                ok += 1
                print(f"  [{i}/{len(todo)}] {tid}: {nf} files, "
                      f"{nv} verbatim", file=sys.stderr, flush=True)

    json.dump({"updated_utc": NOW, "method": "codeload_tarball",
               "ok": ok, "failed": err},
              open(os.path.join(SNAP, "_tarball_log.json"), "w",
                   encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\ntarball fetch: {ok} ok, {len(err)} failed")
    for e in err[:15]:
        print("  ERR", e["task_id"], e["error"][:100])


if __name__ == "__main__":
    main()
