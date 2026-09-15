#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase G -- materialise the frozen base-repository tree for every task.

Why this exists
  The Chigh context package (plan 6.1) may only be built from the issue, the
  base repository at `base_commit`, and public documentation.  To make that
  reproducible *and* auditable we snapshot the exact bytes we looked at, with
  hashes, instead of trusting whatever a clone happens to contain later.

What it produces
  repo_cache/<owner__name>/                  full clone (all blobs present, so
                                             `git show` is offline + instant)
  repo_cache/_inventory/<task_id>.json       complete file inventory at
                                             base_commit (path, blob, size)
  repo_cache/_snapshots/<task_id>.json       content snapshot: every non-source
                                             file as a hash, and the selected
                                             text files verbatim
  repo_cache/_snapshots/_index.json          aggregate + per-repo fetch log

Selection rule for verbatim text (deterministic):
  * source code       *.py *.js *.ts *.jsx *.tsx        (all, size-capped)
  * build/config      pyproject.toml setup.py setup.cfg tox.ini pytest.ini
                      Makefile package.json conftest.py
  * public docs       README* CONTRIBUTING* docs/index.* ARCHITECTURE*
  * test layout       the first line of every test file (import header only),
                      so we can describe test types without copying suites
  Everything else is recorded as path + blob sha + size only.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

csv.field_size_limit(10 ** 9)

DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
CACHE = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\repo_cache"  # code-tree adapter: pin to the authoritative cache
INV = os.path.join(CACHE, "_inventory")
SNAP = os.path.join(CACHE, "_snapshots")

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


def run(cmd, cwd=None, timeout=3600):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or ""), (p.stderr or ""), time.time() - t0


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_LOG_PATH = None


def set_log_path(p):
    global _LOG_PATH
    _LOG_PATH = p


def flush_log(log):
    """Persist the append-only network log so a crash mid-retry still leaves
    evidence of what was attempted."""
    if not _LOG_PATH:
        return
    try:
        json.dump(log, open(_LOG_PATH, "w", encoding="utf-8"), indent=1,
                  ensure_ascii=False)
    except Exception:
        pass


def blob_sha1(b: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(b))
    h.update(b)
    return h.hexdigest()


def is_test_path(p: str) -> bool:
    parts = p.lower().split("/")
    return any(x in ("test", "tests", "testing", "spec", "specs") for x in parts) \
        or os.path.basename(p).startswith("test_") \
        or os.path.basename(p).endswith("_test.py")


def select(files):
    """Return (verbatim_paths, test_header_paths) -- deterministic."""
    verbatim, headers = [], []
    total = 0
    for f in sorted(files, key=lambda x: x["path"]):
        p, sz = f["path"], (f["size"] or 0)
        if sz == 0 or sz > MAX_FILE_BYTES:
            continue
        base = os.path.basename(p)
        if p.endswith(SOURCE_EXT):
            if is_test_path(p):
                if len(headers) < N_TEST_HEADERS:
                    headers.append(p)
            else:
                if len(verbatim) < MAX_FILES and total + sz <= MAX_TOTAL_BYTES:
                    verbatim.append(p)
                    total += sz
        elif base in CFG_NAMES or DOC_RE.search(p):
            if len(verbatim) < MAX_FILES and total + sz <= MAX_TOTAL_BYTES:
                verbatim.append(p)
                total += sz
    return verbatim, headers


def snapshot_task(repo_dir, tid, base_commit, files):
    """.git-free content snapshot via `git archive` + tarfile."""
    verbatim, headers = select(files)
    want = set(verbatim) | set(headers)
    if not want:
        return {"task_id": tid, "base_commit": base_commit, "files": {},
                "n_verbatim": 0, "n_headers": 0}

    # `git archive` needs binary stdout, so bypass the text-mode helper.
    p = subprocess.run(["git", "archive", "--format=tar", base_commit],
                       cwd=repo_dir, capture_output=True, timeout=1800)
    if p.returncode != 0:
        return {"task_id": tid, "base_commit": base_commit, "files": {},
                "error": (p.stderr or b"")[-300:].decode("utf-8", "replace")}

    out = {}
    with tarfile.open(fileobj=io.BytesIO(p.stdout), mode="r:") as tf:
        for m in tf:
            if not m.isfile():
                continue
            name = m.name[2:] if m.name.startswith("./") else m.name
            if name not in want:
                continue
            fh = tf.extractfile(m)
            if fh is None:
                continue
            raw = fh.read(MAX_FILE_BYTES + 1)
            truncated = len(raw) > MAX_FILE_BYTES
            raw = raw[:MAX_FILE_BYTES]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", "replace")
            if name in headers and name not in verbatim:
                out[name] = {
                    "kind": "test_header",
                    "blob": blob_sha1(raw),
                    "content": "\n".join(text.splitlines()[:12])[
                        :TEST_HEADER_BYTES],
                }
            else:
                out[name] = {
                    "kind": "verbatim",
                    "blob": blob_sha1(raw),
                    "sha256": sha256_bytes(raw),
                    "truncated": truncated,
                    "content": text,
                }
    return {
        "task_id": tid,
        "base_commit": base_commit,
        "n_verbatim": sum(1 for v in out.values() if v["kind"] == "verbatim"),
        "n_headers": sum(1 for v in out.values() if v["kind"] == "test_header"),
        "files": out,
    }


def process_repo(repo, tasklist):
    slug = repo.replace("/", "__")
    dest = os.path.join(CACHE, slug)
    url = f"https://github.com/{repo}.git"
    log = []

    if not os.path.isdir(os.path.join(dest, ".git")):
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        # Hard per-attempt timeout: GitHub throttles aggressively when many
        # clones run at once, and a stalled clone must fail loudly rather than
        # hang the whole pass (observed: connections held open indefinitely).
        rc, err = -1, ""
        for attempt in range(1, 4):
            rc, _, err, dt = run(["git", "clone", url, dest], timeout=1800)
            log.append({"repo": repo, "op": "clone", "rc": rc,
                        "attempt": attempt, "seconds": round(dt, 1),
                        "stderr_tail": err[-300:]})
            flush_log(log)
            if rc == 0:
                break
            shutil.rmtree(dest, ignore_errors=True)
            time.sleep(min(180, 20 * 2 ** attempt))
        if rc != 0:
            return log, {"__error__": "clone failed after 3 attempts"}

    index = {}
    # Never bulk-fetch tags: on large repositories that is minutes of server
    # work for objects we do not need.  Fetch each base_commit explicitly.
    wanted = sorted({t["base_commit"] for t in tasklist if t["base_commit"]})
    missing = []
    for bc in wanted:
        rc, _, _, _ = run(["git", "cat-file", "-e", bc + "^{commit}"], cwd=dest)
        if rc != 0:
            missing.append(bc)
    if missing:
        # GitHub intermittently drops connections; retry with backoff.  A silent
        # give-up here would leave zero-file inventories behind, which is worse
        # than failing loudly.
        # Fetch in small batches: a dropped connection then costs one batch
        # rather than the whole repository, and GitHub is far less likely to
        # stall a short request.  Each batch is retried with backoff and with a
        # bounded timeout, so a hung socket cannot hold the pass open forever.
        BATCH = 2
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            batch = [bc for bc in batch
                     if run(["git", "cat-file", "-e", bc + "^{commit}"],
                            cwd=dest)[0] != 0]
            if not batch:
                continue
            ok = False
            for attempt in range(1, 6):
                rc, _, err, dt = run(
                    ["git", "fetch", "--no-tags", "--depth=1", "origin"] + batch,
                    cwd=dest, timeout=900)
                log.append({"repo": repo, "op": "fetch_commits", "rc": rc,
                            "n": len(batch), "attempt": attempt,
                            "seconds": round(dt, 1),
                            "stderr_tail": err[-400:]})
                flush_log(log)
                if rc == 0:
                    ok = True
                    break
                time.sleep(min(120, 15 * 2 ** attempt))
            if not ok:
                still = [bc for bc in batch
                         if run(["git", "cat-file", "-e", bc + "^{commit}"],
                                cwd=dest)[0] != 0]
                if still:
                    return log, {"__error__": (
                        f"fetch failed for {len(still)} commit(s) of "
                        f"{repo}; rerun later: python fetch_repos.py {repo}")}

    for t in tasklist:
        tid, bc = t["task_id"], t["base_commit"]
        rc, out, _, _ = run(["git", "cat-file", "-e", bc + "^{commit}"],
                            cwd=dest)
        if rc != 0:
            rc2, _, err2, dt2 = run(["git", "fetch", "origin", bc], cwd=dest,
                                    timeout=3600)
            log.append({"repo": repo, "op": f"fetch:{bc[:10]}", "rc": rc2,
                        "seconds": round(dt2, 1)})
            rc, out, _, _ = run(["git", "cat-file", "-e", bc + "^{commit}"],
                                cwd=dest)
            if rc != 0:
                index[tid] = {"task_id": tid, "repo": repo,
                              "base_commit": bc, "ok": False,
                              "error": "commit unavailable"}
                continue

        rc, out, err, _ = run(
            ["git", "ls-tree", "-r", "-l", "--full-tree", bc], cwd=dest,
            timeout=1800)
        if rc != 0:
            index[tid] = {"task_id": tid, "repo": repo, "base_commit": bc,
                          "ok": False, "error": err[-300:]}
            continue

        files = []
        for line in out.splitlines():
            try:
                meta, path = line.split("\t", 1)
            except ValueError:
                continue
            # `ls-tree -l` pads the size column with spaces, so split into at
            # most four fields: mode, type, sha, size.
            parts = meta.split(None, 3)
            if len(parts) < 4:
                continue
            mode, otype, oid, size = parts[0], parts[1], parts[2], parts[3]
            if path.split("/", 1)[0] in NOISE_DIRS:
                continue
            files.append({"path": path, "mode": mode, "type": otype,
                          "blob": oid,
                          "size": int(size) if size.isdigit() else None})

        inv_rec = {
            "task_id": tid, "repo": repo, "base_commit": bc,
            "split": t.get("split"), "ok": True, "n_files": len(files),
            "n_bytes": sum(f["size"] or 0 for f in files),
            "inventory_sha256": sha256_bytes(
                json.dumps(files, sort_keys=True).encode("utf-8")),
            "files": files,
        }
        json.dump(inv_rec, open(os.path.join(INV, tid + ".json"), "w",
                                encoding="utf-8"), ensure_ascii=False)

        try:
            snap = snapshot_task(dest, tid, bc, files)
            json.dump(snap, open(os.path.join(SNAP, tid + ".json"), "w",
                                 encoding="utf-8"), ensure_ascii=False)
            snap_ok = "error" not in snap
        except Exception as e:
            snap_ok = False
            json.dump({"task_id": tid, "base_commit": bc,
                       "error": f"{type(e).__name__}: {e}"},
                      open(os.path.join(SNAP, tid + ".json"), "w",
                           encoding="utf-8"))

        index[tid] = {
            "task_id": tid, "repo": repo, "base_commit": bc,
            "split": t.get("split"), "ok": True, "n_files": len(files),
            "n_bytes": inv_rec["n_bytes"],
            "inventory_sha256": inv_rec["inventory_sha256"],
            "snapshot_ok": snap_ok,
        }
        print(f"    {tid}: {len(files)} files, snapshot="
              f"{'ok' if snap_ok else 'FAIL'}", file=sys.stderr, flush=True)

    return log, index


def main():
    os.makedirs(INV, exist_ok=True)
    os.makedirs(SNAP, exist_ok=True)

    tasks = [r for r in csv.DictReader(
        open(os.path.join(DS, "gold", "commits.csv"), newline="",
             encoding="utf-8")) if r.get("task_id")]
    by_repo = {}
    for t in tasks:
        by_repo.setdefault(t["repo"], []).append(t)

    index_path = os.path.join(SNAP, "_index.json")
    set_log_path(os.path.join(SNAP, "_fetch_log.json"))
    index = json.load(open(index_path, encoding="utf-8")) if \
        os.path.exists(index_path) else {}

    log = []
    repos = sorted(by_repo.items())

    def flush():
        json.dump(index, open(index_path, "w", encoding="utf-8"),
                  ensure_ascii=False)
        json.dump(log, open(os.path.join(SNAP, "_fetch_log.json"), "w",
                            encoding="utf-8"), indent=1, ensure_ascii=False)

    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    if only:
        repos = [(r, t) for r, t in repos if r in only]

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(process_repo, r, t): r for r, t in repos}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            repo = futs[fut]
            try:
                rlog, ridx = fut.result()
            except Exception as e:
                print(f"[{i}/{len(repos)}] {repo} EXCEPTION {e}",
                      file=sys.stderr, flush=True)
                continue
            log.extend(rlog)
            if "__error__" in ridx:
                print(f"[{i}/{len(repos)}] {repo} FAILED: {ridx['__error__']}"
                      f" -- rerun this repo: python fetch_repos.py {repo}",
                      file=sys.stderr, flush=True)
                ridx = {}
            index.update(ridx)
            flush()
            print(f"[{i}/{len(repos)}] {repo}: {len(ridx)} tasks done",
                  file=sys.stderr, flush=True)

    ok = sum(1 for v in index.values() if v.get("ok"))
    sok = sum(1 for v in index.values() if v.get("snapshot_ok"))
    print(f"\nDONE: inventory {ok}/{len(tasks)}   snapshot {sok}/{len(tasks)}",
          file=sys.stderr)
    flush()


if __name__ == "__main__":
    main()
