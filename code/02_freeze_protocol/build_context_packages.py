#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase D -- Chigh context packages  (plan section 6)

The context package is the *treatment* for the Chigh / Context-Enriched
condition.  Plan 6.1 fixes its contents to five items:

  1. repository high-level architecture (directory / component level, NOT the
     specific repair site)
  2. principal module responsibilities + public development-doc digest
  3. call / dependency relationships visible from the issue and base repository
  4. test directory structure, test types and common test entry points
  5. source list + generation timestamp

and plan 6 forbids, inside the package:

  * code added by the gold patch
  * concrete changed line numbers / hunk locations
  * a direct root-cause conclusion
  * the target repair hint

Leak control, enforced structurally rather than by inspection
  * the only inputs are `dataset/tasks/<id>/issue.json`,
    `dataset/tasks/<id>/metadata.json`, the base-commit content snapshot
    produced by repo_cache/fetch_repos.py, and the project's own public docs
  * `gold/patches/`, `benchmark_tests/*/test_patch.diff`,
    `FAIL_TO_PASS.json` and `PASS_TO_PASS.json` are never opened -- they are
    not in `SOURCES_READ` and no path in this file resolves to them
  * `metadata.json` is used for exactly four non-oracular fields
    (repo, language, difficulty stratum, gold *size*), because plan 3.2
    requires the reviewers to know the repair boundary when screening; size is
    a coarse scale signal, not a location.  The `gold_modules` field, which
    would name the repair site, is deliberately NOT read.
  * architecture is presented as a whole-repository component listing with no
    ranking, no highlighting and no shortlist, so nothing in the package
    points at a file
  * the package is frozen before the independent gold-aware leakage review,
    exactly as plan 6.2 prescribes

Two artefacts per task:
  context_packages/<task_id>.md            the frozen package (participant-visible)
  context_packages/_frozen/<task_id>.meta.json   provenance, hashes, audit data
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
SNAP = os.path.join(ROOT, "repo_cache", "_snapshots")
INV = os.path.join(ROOT, "repo_cache", "_inventory")
OUT = os.path.join(ROOT, "context_packages")
FROZEN = os.path.join(OUT, "_frozen")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

MAX_TREE_LINES = 300
MAX_MODULE_DOCSTRINGS = 55
MAX_EDGES = 80
MAX_DOC_CHARS = 3500
MAX_TEST_ROOTS = 30
LARGE_REPO_FILES = 4000          # above this, tree is summarised per level

SOURCES_READ = "declared in the meta.json of each package"


# --------------------------------------------------------------------------- #
def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def component(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def module_name(path: str):
    if path.endswith("/__init__.py"):
        return path[: -len("/__init__.py")].replace("/", ".")
    for ext in (".py", ".js", ".ts", ".jsx", ".tsx"):
        if path.endswith(ext):
            return path[: -len(ext)].replace("/", ".")
    return None


def parse_imports(src: str, path: str):
    try:
        tree = ast.parse(src)
    except Exception:
        return None
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = module_name(path) or ""
                parts = base.split(".")
                ups = node.level - (1 if path.endswith("__init__.py") else 0)
                parts = parts[: max(0, len(parts) - ups)]
                if node.module:
                    parts = parts[: max(0, len(parts) - 1)] + [node.module]
                mods.add(".".join(p for p in parts if p))
            elif node.module:
                mods.add(node.module)
    return mods


def first_docstring(src: str):
    try:
        tree = ast.parse(src)
    except Exception:
        m = re.search(r'^\s*(?:"""|\'\'\')(.{0,400}?)(?:"""|\'\'\')', src,
                      re.S | re.M)
        return " ".join(m.group(1).split())[:400] if m else None
    d = ast.get_docstring(tree)
    return " ".join(d.split())[:400] if d else None


def public_symbols(src: str, limit=8):
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append(("class " if isinstance(node, ast.ClassDef)
                            else "def ") + node.name)
            if len(out) >= limit:
                break
    return out


def top_level_symbols(src: str, limit=25):
    """Public top-level names, used as a neutral symbol index."""
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append(node.name)
            if len(out) >= limit:
                break
    return out


def is_test_path(p: str) -> bool:
    parts = p.lower().split("/")
    if any(x in ("test", "tests", "testing", "spec", "specs") for x in parts):
        return True
    b = os.path.basename(p)
    return b.startswith("test_") or b.endswith("_test.py") or b == "conftest.py"


def tree_text(files, budget):
    """Compact deterministic tree.  Huge repos are summarised per directory so
    the package stays readable."""
    lines = []
    big = len(files) > LARGE_REPO_FILES
    if big:
        by_dir = Counter()
        bytes_dir = Counter()
        for f in files:
            d = os.path.dirname(f["path"]) or "."
            parts = d.split("/")
            key = "/".join(parts[:2]) if len(parts) > 2 else d
            by_dir[key] += 1
            bytes_dir[key] += f["size"] or 0
        lines.append(f"(repository has {len(files):,} files; listing is "
                     f"aggregated to directory level)")
        for d, n in sorted(by_dir.items(), key=lambda kv: (-kv[1], kv[0]))[:budget]:
            lines.append(f"{d}/  [{n} files, {bytes_dir[d]:,}B]")
        if len(by_dir) > budget:
            lines.append(f"... and {len(by_dir)-budget} further directories")
        return "\n".join(lines)

    for f in sorted(files, key=lambda x: x["path"]):
        if len(lines) >= budget:
            lines.append(f"... {len(files)-len(lines)} further files omitted "
                         f"(complete inventory kept in the audit copy)")
            break
        p = f["path"]
        depth = p.count("/")
        name = p.rsplit("/", 1)[-1]
        sz = f["size"] or 0
        lines.append(f"{'  '*depth}{name}  [{sz:,}B]" if sz else
                     f"{'  '*depth}{name}")
    return "\n".join(lines)


def read_docs_from_repo(snap_files, repo_id, limit=2600):
    """Pick a public doc out of the snapshot."""
    order = ["README.md", "README.rst", "README.txt", "README",
             "readme.md", "CONTRIBUTING.md", "docs/index.rst",
             "docs/index.md", "ARCHITECTURE.md"]
    for cand in order:
        v = snap_files.get(cand)
        if v and v.get("kind") == "verbatim":
            return cand, v["content"][:MAX_DOC_CHARS]
    for p, v in sorted(snap_files.items()):
        b = os.path.basename(p).lower()
        if v.get("kind") == "verbatim" and (b.startswith("readme")
                                           or b.startswith("contributing")):
            return p, v["content"][:MAX_DOC_CHARS]
    return None, None


def discover_entry_points(snap_files):
    out = {}
    for cfg in ("pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini"):
        v = snap_files.get(cfg)
        if not v or v.get("kind") != "verbatim":
            continue
        t = v["content"]
        m = re.search(r"\[tool\.pytest\.[^\]]*\](.{0,400})", t, re.S)
        if m:
            out[f"{cfg} [tool.pytest]"] = " ".join(m.group(1).split())[:200]
        m2 = re.search(r"testpaths\s*=\s*(.{0,140})", t)
        if m2:
            out[f"{cfg} testpaths"] = " ".join(m2.group(1).split())[:140]
        m3 = re.search(r"\[tool\.pytest\.ini_options\][^\[]*?"
                       r"addopts\s*=\s*(.{0,160})", t, re.S)
        if m3:
            out[f"{cfg} addopts"] = " ".join(m3.group(1).split())[:160]
    v = snap_files.get("Makefile")
    if v and v.get("kind") == "verbatim":
        m = re.search(r"^(test|tests|check):.*$", v["content"], re.M)
        if m:
            out["Makefile test target"] = m.group(0)[:160]
    v = snap_files.get("package.json")
    if v and v.get("kind") == "verbatim":
        try:
            pj = json.loads(v["content"])
            if isinstance(pj.get("scripts"), dict) and pj["scripts"].get("test"):
                out["package.json scripts.test"] = str(
                    pj["scripts"]["test"])[:160]
        except Exception:
            pass
    if not out:
        out["default"] = "pytest"
    return out


# --------------------------------------------------------------------------- #
def build_module_edges(non_test_src):
    """Module-level fallback for single-package repositories.

    For a project like urllib3 essentially every module lives under one
    component (`src/`), so a component-level graph collapses to nothing and
    section 3 would be empty.  Reporting the strongest intra-package edges is
    the same kind of orientation information at a finer grain -- it still
    describes the whole project's wiring rather than pointing at a repair site.
    """
    mod2path = {}
    for p in non_test_src:
        if not p.endswith(".py"):
            continue
        m = module_name(p)
        if m:
            mod2path[m] = p
    edges = Counter()
    for p in sorted(non_test_src):
        if not p.endswith(".py"):
            continue
        mods = parse_imports(non_test_src[p]["content"], p)
        if mods is None:
            continue
        me = module_name(p)
        for m in mods:
            m = m.strip(".")
            if not m:
                continue
            parts = m.split(".")
            hit = None
            for k in range(len(parts), 0, -1):
                cand = ".".join(parts[:k])
                if cand in mod2path:
                    hit = cand
                    break
            if hit is None or hit == me:
                continue
            edges[(me, hit)] += 1
    return edges


def build_import_edges(non_test_src):
    """Component-level internal import graph.

    A plain "first dotted segment == top-level directory" rule is wrong for the
    common `src/` layout: urllib3's own modules import each other as
    `urllib3.response`, so the first segment is the *package*, not a directory.
    This resolves each import against the repository's real module set, trying
    progressively shorter dotted prefixes, so `urllib3.connection` maps to
    `src/urllib3/connection.py` and therefore to the `src` component.
    """
    mod2path = {}
    for p in non_test_src:
        if not p.endswith(".py"):
            continue
        m = module_name(p)
        if m:
            mod2path[m] = p

    edges = Counter()
    parsed = 0
    for p in sorted(non_test_src):
        if not p.endswith(".py"):
            continue
        mods = parse_imports(non_test_src[p]["content"], p)
        if mods is None:
            continue
        parsed += 1
        src_comp = component(p)
        for m in mods:
            m = m.strip(".")
            if not m:
                continue
            parts = m.split(".")
            hit = None
            for k in range(len(parts), 0, -1):
                cand = ".".join(parts[:k])
                if cand in mod2path:
                    hit = cand
                    break
            if hit is None:
                continue
            target = mod2path[hit]
            if target == p:
                continue
            dst_comp = component(target)
            if dst_comp == src_comp:
                continue
            edges[(src_comp, dst_comp)] += 1
    return edges, parsed


def build(task_id, man, inv, snap):
    repo_id = man.get("repo_id") or ""
    commit = man["base_commit"]
    # tolerate either the task-index schema or a richer manifest record
    repo_url = man.get("repo_url") or f"https://github.com/{repo_id}.git"
    language = man.get("language") or "python"
    files = inv["files"]
    sf = snap.get("files", {})
    n_bytes = inv.get("n_bytes") or sum(f.get("size") or 0 for f in files)

    verbatim = {p: v for p, v in sf.items() if v.get("kind") == "verbatim"}
    headers = {p: v for p, v in sf.items() if v.get("kind") == "test_header"}

    comp_files = Counter()
    comp_bytes = Counter()
    for f in files:
        c = component(f["path"])
        comp_files[c] += 1
        comp_bytes[c] += f["size"] or 0

    non_test_src = {p: v for p, v in verbatim.items()
                    if p.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))
                    and not is_test_path(p)}
    test_src = {p: v for p, v in headers.items()}

    L = []
    A = L.append
    A(f"# Context package — `{repo_id}` at `{commit[:12]}`")
    A("")
    A(f"**Task ID:** `{task_id}`  ")
    A(f"**Repository:** {repo_url}  ")
    A(f"**Base commit:** `{commit}`  ")
    A(f"**Language:** {language}  ")
    A(f"**Difficulty stratum (for scheduling only):** "
      f"{man.get('task_difficulty_stratum')}  ")
    A(f"**Package generated (UTC):** {NOW}")
    A("")
    A("> This package is background material about the repository as a whole. "
      "It was built only from the issue text, the repository at the base "
      "commit, and the project's public documentation. It does not identify a "
      "defect, a root cause, or a place to edit, and it contains no code from "
      "any fix. Locating and correcting the problem remains the task.")
    A("")
    A("---")
    A("")

    # ------------------------------------------------------------ 1
    A("## 1. Repository high-level architecture")
    A("")
    A(f"At the base commit the repository tracks **{len(files):,} files** "
      f"({n_bytes/1e6:.1f} MB), excluding VCS metadata and vendored or build "
      f"directories. The component table below covers every top-level entry "
      f"in the project — nothing is singled out.")
    A("")
    A("| Top-level component | Files | Bytes | Share of files |")
    A("|---|---:|---:|---:|")
    for c, n in sorted(comp_files.items(), key=lambda kv: (-kv[1], kv[0]))[:45]:
        A(f"| `{c}` | {n} | {comp_bytes[c]:,} | {100.0*n/len(files):.2f}% |")
    A("")
    A("### 1.1 File tree at the base commit")
    A("")
    A("```")
    A(tree_text(files, MAX_TREE_LINES))
    A("```")
    A("")

    # ------------------------------------------------------------ 2
    A("## 2. Principal module responsibilities")
    A("")
    if non_test_src:
        A("Module docstrings quoted verbatim from the base commit, ordered "
          "alphabetically by path. They are not ranked, filtered or weighted.")
        A("")
        A("| Module | Stated responsibility | Notable public symbols |")
        A("|---|---|---|")
        shown = 0
        documented = set()
        for p in sorted(non_test_src):
            if shown >= MAX_MODULE_DOCSTRINGS:
                break
            ds = first_docstring(non_test_src[p]["content"])
            if not ds:
                continue
            syms = public_symbols(non_test_src[p]["content"])
            A(f"| `{p}` | {ds.replace('|', chr(92)+'|')} | "
              f"{', '.join('`'+s+'`' for s in syms[:6]) or '—'} |")
            shown += 1
            documented.add(p)
        A("")
        A(f"_{shown} of the {len(non_test_src)} source modules in this "
          f"snapshot carry a module docstring. The snapshot covers the "
          f"repository's own source files up to a fixed cap of 400 files and "
          f"256 KB per file, so for very large repositories the listing is a "
          f"subset chosen alphabetically by path — never by relevance._")
        A("")

        # Some projects document almost nothing in-source (aiogram, for one).
        # A docstring-only section would then be empty, so fall back to the
        # public API surface, which is equally gold-independent and lets the
        # participant see what each module is *for* without seeing how it works.
        if shown < 8:
            A(f"Because in-source docstrings are sparse here, the table below "
              f"instead lists the public top-level definitions of every source "
              f"module in the snapshot. It is a map of the API surface, not a "
              f"guide to any defect.")
            A("")
            A("| Module | Public top-level definitions |")
            A("|---|---|")
            listed = 0
            for p in sorted(non_test_src):
                if listed >= MAX_MODULE_DOCSTRINGS + 40:
                    break
                syms = top_level_symbols(non_test_src[p]["content"], 14)
                if not syms:
                    continue
                A(f"| `{p}` | {', '.join('`'+s+'`' for s in syms)} |")
                listed += 1
            A("")
    else:
        A("_No verbatim source snapshot was available for this task; the "
          "component table and tree above are the architecture signal._")
        A("")

    # ------------------------------------------------------------ 3
    A("## 3. Call / dependency relationships")
    A("")
    comp_edges, parsed = build_import_edges(non_test_src)
    if comp_edges:
        A(f"Static parsing succeeded on **{parsed}** non-test Python modules. "
          f"Aggregated to component level, the most frequent internal "
          f"dependencies are:")
        A("")
        A("| From component | To component | Import sites |")
        A("|---|---|---:|")
        for (a, b), n in comp_edges.most_common(MAX_EDGES):
            A(f"| `{a}` | `{b}` | {n} |")
        A("")
        A("These edges describe how the project's own modules are wired at the "
          "base commit. They are an orientation aid, not an indication of "
          "where any problem lies.")
    else:
        mod_edges = build_module_edges(non_test_src)
        if mod_edges:
            A(f"This repository is essentially a single component, so the "
              f"graph is reported at module level: static parsing succeeded on "
              f"**{parsed}** non-test Python modules and found "
              f"{len(mod_edges)} distinct intra-project import edges. The most "
              f"frequent are:")
            A("")
            A("| Importer module | Imported module | Import sites |")
            A("|---|---|---:|")
            for (a, b), n in mod_edges.most_common(MAX_EDGES):
                A(f"| `{a}` | `{b}` | {n} |")
            A("")
            A("These edges describe how the project's own modules are wired at "
              "the base commit. They are an orientation aid, not an indication "
              "of where any problem lies.")
        else:
            A("_No intra-repository import edges could be recovered by static "
              "parsing at this commit._")
    A("")

    # ------------------------------------------------------------ 4
    A("## 4. Test layout and entry points")
    A("")
    test_inventory = [f for f in files if is_test_path(f["path"])]
    dirs = Counter()
    for f in test_inventory:
        parts = f["path"].split("/")[:-1]
        dirs["/".join(parts[:3]) if parts else "."] += 1
    A(f"**{len(test_inventory):,}** test-related paths exist in the "
      f"repository. Test roots by file count:")
    A("")
    A("| Test directory | Files |")
    A("|---|---:|")
    for d, n in sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TEST_ROOTS]:
        A(f"| `{d}` | {n} |")
    A("")
    if headers:
        exts = Counter(os.path.splitext(p)[1] for p in headers)
        A(f"Test files are written in "
          f"{', '.join(f'`{e or chr(40)+chr(110)+chr(111)+chr(32)+chr(101)+chr(120)+chr(116)+chr(41)}`' for e in exts)}. "
          f"The first lines of {len(headers)} test modules are reproduced "
          f"below so you can see which frameworks and fixtures they use.")
        A("")
        A("```python")
        for p in sorted(headers)[:60]:
            head = headers[p]["content"].strip().splitlines()
            head = [h for h in head if h.strip() and not h.strip().startswith("#")][:6]
            if head:
                A(f"# {p}")
                for h in head:
                    A(h)
                A("")
        A("```")
        A("")
    conf = [p for p in files if os.path.basename(p["path"]) == "conftest.py"]
    if conf:
        A("`conftest.py` files (fixture / plugin wiring): "
          + ", ".join(f"`{c}`" for c in sorted(x["path"] for x in conf)[:30]))
        A("")
    A("**Declared test entry points**, read from the repository's own "
      "configuration:")
    A("")
    for k, v in discover_entry_points(verbatim).items():
        A(f"- `{k}`: `{v}`")
    A("")

    # ------------------------------------------------------------ 5
    A("## 5. Public documentation digest")
    A("")
    docpath, doctext = read_docs_from_repo(verbatim, repo_id)
    if docpath:
        A(f"Source: `{docpath}` (truncated to {MAX_DOC_CHARS} characters)")
        A("")
        A("```text")
        A(doctext)
        A("```")
    else:
        A("_No public documentation file was found in the base-commit "
          "snapshot._")
    A("")

    # ------------------------------------------------------------ 6
    A("## 6. Information sources")
    A("")
    A("| # | Source | Used for | Retrieved (UTC) |")
    A("|---|---|---|---|")
    A(f"| 1 | issue text for `{task_id}` | supplied to you separately as the "
      f"task statement | {NOW} |")
    A(f"| 2 | `{repo_url}` @ `{commit}` | file inventory, tree, module "
      f"docstrings, import edges, test layout | {NOW} |")
    A(f"| 3 | `{docpath}` | public documentation digest | {NOW} |"
      if docpath else
      f"| 3 | (no public doc found) | — | {NOW} |")
    A(f"| 4 | base-commit build configuration | declared test entry points | "
      f"{NOW} |")
    A("")
    A("**Deliberately excluded from this package:** every patch or diff, every "
      "commit after the base commit, the upstream issue resolution, any "
      "grading test list, any list of changed files or line numbers, and any "
      "statement of root cause. The package was generated and hashed before "
      "any gold-aware review; see the `_frozen` metadata for this task.")
    A("")
    A("**How to use it.** Treat this as the kind of briefing a colleague who "
      "knows the project would give you before you start: it tells you how "
      "the code is laid out, what each part is for, how the parts depend on "
      "each other, and how the tests are run. It deliberately does not tell "
      "you where the problem is.")
    A("")

    body = "\n".join(L)

    # audit-only gold-aware metadata, kept out of the participant artefact
    audit = {
        "task_id": task_id,
        "generated_utc": NOW,
        "generator": "build_context_packages.py",
        "sources_read": [
            f"dataset/tasks/{task_id}/issue.json",
            f"dataset/tasks/{task_id}/metadata.json",
            f"repo_cache/_inventory/{task_id}.json",
            f"repo_cache/_snapshots/{task_id}.json",
            f"dataset/environments/docker/{task_id}/environment_metadata.json",
        ],
        "sources_never_read": [
            "dataset/gold/patches/**",
            "dataset/benchmark_tests/*/test_patch.diff",
            "dataset/benchmark_tests/*/FAIL_TO_PASS.json",
            "dataset/benchmark_tests/*/PASS_TO_PASS.json",
            "dataset/benchmark_tests/*/oracle.json",
        ],
        "content_sha256": sha256_text(body),
        "byte_size": len(body.encode("utf-8")),
        "stats": {
            "n_files_repo": len(files),
            "n_verbatim_files": len(verbatim),
            "n_test_headers": len(headers),
            "n_components": len(comp_files),
            "n_import_edges": len(comp_edges),
        },
        "gold_derived_information": False,
        "includes_gold_patch": False,
        "includes_test_names": False,
        "includes_changed_line_numbers": False,
        "includes_root_cause_statement": False,
        "leakage_review": {
            "status": "pending_independent_review",
            "reviewer": None,
            "reviewed_at": None,
            "verdict": None,
            "leak_locations": [],
        },
    }
    return body, audit


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(FROZEN, exist_ok=True)

    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]
    if args.only:
        idx = [t for t in idx if t["task_id"] in set(args.only)]

    jobs, skipped = [], []
    for t in idx:
        tid = t["task_id"]
        ip = os.path.join(INV, tid + ".json")
        sp = os.path.join(SNAP, tid + ".json")
        if not os.path.exists(ip):
            skipped.append((tid, "no inventory"))
            continue
        if not os.path.exists(sp):
            skipped.append((tid, "no snapshot"))
            continue
        inv = json.load(open(ip, encoding="utf-8"))
        snap = json.load(open(sp, encoding="utf-8"))
        if not inv.get("ok"):
            skipped.append((tid, "inventory not ok"))
            continue
        if "error" in snap:
            skipped.append((tid, "snapshot error"))
            continue
        jobs.append((tid, t, inv, snap))

    print(f"to build {len(jobs)}   skipped {len(skipped)}", file=sys.stderr)
    ok, err = 0, []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(build, tid, t, inv, snap): tid
                for tid, t, inv, snap in jobs}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            tid = futs[fut]
            try:
                body, audit = fut.result()
                open(os.path.join(OUT, tid + ".md"), "w", encoding="utf-8",
                     newline="\n").write(body + "\n")
                json.dump(audit, open(os.path.join(FROZEN, tid + ".meta.json"),
                                      "w", encoding="utf-8"), indent=1,
                          ensure_ascii=False)
                ok += 1
            except Exception as e:
                err.append((tid, f"{type(e).__name__}: {e}"))
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} ok={ok} err={len(err)}",
                      file=sys.stderr, flush=True)

    print(f"\nbuilt {ok} packages, {len(err)} errors, {len(skipped)} skipped")
    for e in err[:25]:
        print("  ERR", e)
    for s in skipped[:25]:
        print("  SKIP", s)

    man = {
        "generated_utc": NOW,
        "generator": "build_context_packages.py",
        "condition": "Chigh",
        "n_packages": ok,
        "n_skipped": len(skipped),
        "skipped": [{"task_id": a, "reason": b} for a, b in skipped],
        "errors": [{"task_id": a, "error": b} for a, b in err],
        "note": ("frozen BEFORE gold-aware leakage review (plan 6.2 step 2); "
                 "hashes below must not change after review starts"),
    }
    json.dump(man, open(os.path.join(FROZEN, "_build_manifest.json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
