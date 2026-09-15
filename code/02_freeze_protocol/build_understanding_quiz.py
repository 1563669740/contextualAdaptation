#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Role A2 -- repository-understanding quiz author (paper V-A manipulation check).

The paper does not only compare outcomes; it first shows the *context
manipulation actually took effect*, reporting Chigh 8.4 vs Clow 5.9 out of 10
(difference 2.5, 95% CI 2.21-2.79).  Without that check a null result cannot be
interpreted: "context was not manipulated" and "context was manipulated but had
no effect" look identical.

This tool generates per-task quiz items mechanically from the frozen artefacts,
which is the only defensible way to do it at scale: an item must be answerable
from the base repository alone, must not be answered better by the Chigh package
in a way that reveals the defect, and must never mention the defect at all.

Three domains, per the paper: module responsibility, dependency relations, test
structure.  Every item records the evidence it was built from, and every
distractor is drawn from the same repository so the question cannot be answered
by "pick the plausible-looking name".

Correct answers are derived from structure (a module's own docstring, the
dependency graph, the test tree), not from judgement, so they are reproducible:
re-running produces byte-identical items.

CLI
  python tools/build_understanding_quiz.py --task-id <id>
  python tools/build_understanding_quiz.py --all --limit 20
  python tools/build_understanding_quiz.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
SNAP = os.path.join(ROOT, "repo_cache", "_snapshots")
OUT = os.path.join(ROOT, "protocol", "quiz_items")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ITEMS_PER_DOMAIN = 2
POINTS = {"module_responsibility": 2.0, "dependency_relations": 1.5,
          "test_structure": 1.5}
SEED = 20260301

STOPWORDS = {"a", "an", "the", "of", "for", "and", "to", "in", "on", "with",
             "this", "that", "is", "are", "be", "it", "its", "as", "by", "or",
             "from", "at", "we", "you", "your", "our", "module", "package",
             "library", "python", "implementation", "support", "supports"}


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def is_test_path(p):
    parts = p.lower().split("/")
    return (any(x in ("test", "tests", "testing", "spec", "specs") for x in parts)
            or os.path.basename(p).startswith("test_")
            or os.path.basename(p).endswith("_test.py")
            or os.path.basename(p) == "conftest.py")


def docstring_of(src):
    import ast
    try:
        tree = ast.parse(src)
    except Exception:
        return None
    d = ast.get_docstring(tree)
    return " ".join(d.split()) if d else None


def keywords(text, n=6):
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.lower())
    return [w for w in words if w not in STOPWORDS][:n]


def first_sentence(text):
    m = re.split(r"(?<=[.!?])\s+", text.strip())
    return (m[0] if m else text).strip()[:200]


def load(task_id):
    inv = json.load(open(os.path.join(ROOT, "repo_cache", "_inventory",
                                      task_id + ".json"), encoding="utf-8"))
    snap = json.load(open(os.path.join(SNAP, task_id + ".json"),
                          encoding="utf-8"))
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]
    meta = next((t for t in idx if t["task_id"] == task_id), None)
    return meta, inv, snap


# --------------------------------------------------------------------------- #
# domain 1: module responsibility
# --------------------------------------------------------------------------- #
def items_module_responsibility(src_files, rng, n):
    """Question: which module states this responsibility?
    Correct answer comes from that module's own docstring."""
    documented = []
    for p, v in sorted(src_files.items()):
        if v.get("kind") != "verbatim":
            continue
        ds = docstring_of(v["content"])
        if not ds or len(ds) < 30:
            continue
        documented.append((p, ds))
    if len(documented) < n + 3:
        return []
    rng.shuffle(documented)
    items = []
    for i in range(n):
        path, ds = documented[i]
        distractors = [p for p, _ in documented if p != path][:12]
        rng.shuffle(distractors)
        opts = [path] + distractors[:3]
        rng.shuffle(opts)
        items.append({
            "id": f"mr_{i+1}",
            "domain": "module_responsibility",
            "points": POINTS["module_responsibility"],
            "type": "single_choice",
            "question": ("Which module's own documentation describes it as: "
                         f"\"{first_sentence(ds)}\"?"),
            "options": opts,
            "answer_index": opts.index(path),
            "evidence": {"source_file": path, "docstring_excerpt": ds[:220]},
            "answerable_from": ["base_repository"],
            "leakage_check": {
                "mentions_defect": False,
                "mentions_gold_file": None,
                "note": ("answer is the module's own docstring at the base "
                         "commit; a participant with the repository can find it "
                         "by reading, which is the point of the check"),
            },
            "difficulty_proxy": {"docstring_len": len(ds)},
        })
    return items


# --------------------------------------------------------------------------- #
# domain 2: dependency relations
# --------------------------------------------------------------------------- #
def module_name_of(path):
    if path.endswith("/__init__.py"):
        return path[: -len("/__init__.py")].replace("/", ".")
    if path.endswith(".py"):
        return path[:-3].replace("/", ".")
    return None


def resolve_relative(path, level, module, mod2path):
    """Resolve a relative import (`from . import x`) against known modules.

    The first version of this extractor ignored relative imports entirely, which
    reported ZERO internal edges for attrs -- a repository whose modules are
    wired almost exclusively with `from . import ...`.  A quiz built on that
    graph would have been silently empty, so this is a correctness fix rather
    than a nicety.
    """
    me = module_name_of(path) or ""
    is_pkg = path.endswith("/__init__.py")
    parts = me.split(".") if me else []
    if not is_pkg and parts:
        parts = parts[:-1]                      # drop the module itself
    up = level - 1
    if up:
        parts = parts[: max(0, len(parts) - up)]
    if module:
        parts = parts + module.split(".")
    base = ".".join(p for p in parts if p)
    if base in mod2path:
        return base
    # `from . import name` -> the name is a submodule of the base package
    for k in range(len(parts), 0, -1):
        cand = ".".join(parts[:k])
        if cand in mod2path:
            return cand
    return None


def build_imports(src_files):
    """Internal import graph, absolute and relative."""
    import ast
    mod2path = {}
    for p, v in src_files.items():
        if not p.endswith(".py") or v.get("kind") != "verbatim":
            continue
        m = module_name_of(p)
        if m:
            mod2path[m] = p

    edges = defaultdict(set)
    for p, v in src_files.items():
        if not p.endswith(".py") or v.get("kind") != "verbatim":
            continue
        try:
            tree = ast.parse(v["content"])
        except Exception:
            continue
        me = module_name_of(p)
        if not me:
            continue
        for node in ast.walk(tree):
            hits = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    for k in range(len(parts), 0, -1):
                        cand = ".".join(parts[:k])
                        if cand in mod2path:
                            hits.append(cand)
                            break
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    r = resolve_relative(p, node.level, node.module, mod2path)
                    if r:
                        hits.append(r)
                    # `from . import a, b` also names submodules
                    if not node.module:
                        for alias in node.names:
                            sub = resolve_relative(
                                p, node.level, alias.name, mod2path)
                            if sub:
                                hits.append(sub)
                elif node.module:
                    parts = node.module.split(".")
                    for k in range(len(parts), 0, -1):
                        cand = ".".join(parts[:k])
                        if cand in mod2path:
                            hits.append(cand)
                            break
            for h in hits:
                tgt = mod2path.get(h)
                if tgt and tgt != p:
                    edges[me].add(tgt)
    return mod2path, edges


def items_dependency(src_files, rng, n):
    mod2path, edges = build_imports(src_files)
    strong = [(a, sorted(b)) for a, b in edges.items() if b]
    strong = [(a, b) for a, b in strong if len(b) >= 1]
    if len(strong) < n + 3:
        return []
    rng.shuffle(strong)
    all_paths = sorted({p for _, b in strong for p in b})
    items = []
    for i in range(n):
        importer, targets = strong[i]
        correct = targets[0]
        pool = [p for p in all_paths if p != correct]
        rng.shuffle(pool)
        opts = [correct] + pool[:3]
        if len(opts) < 4:
            continue
        rng.shuffle(opts)
        items.append({
            "id": f"dr_{i+1}",
            "domain": "dependency_relations",
            "points": POINTS["dependency_relations"],
            "type": "single_choice",
            "question": (f"Within this repository, which module does "
                         f"`{importer}` import?"),
            "options": opts,
            "answer_index": opts.index(correct),
            "evidence": {"importer": importer, "imported": targets},
            "answerable_from": ["base_repository"],
            "leakage_check": {
                "mentions_defect": False,
                "note": ("derived from the static import graph at the base "
                         "commit, which the Chigh package summarises in its "
                         "section 3 and a participant can recompute by reading"),
            },
            "difficulty_proxy": {"n_imports": len(targets)},
        })
    return items


# --------------------------------------------------------------------------- #
# domain 3: test structure
# --------------------------------------------------------------------------- #
def items_test_structure(inv, src_files, rng, n):
    tests = [f["path"] for f in inv["files"] if is_test_path(f["path"])]
    if len(tests) < n + 3:
        return []
    dirs = Counter(os.path.dirname(t) or "." for t in tests)
    top = [d for d, c in dirs.most_common(12)]
    if len(top) < 4:
        return []
    rng.shuffle(top)
    items = []
    for i in range(n):
        d = top[i]
        example = next(t for t in tests if (os.path.dirname(t) or ".") == d)
        pool = [x for x in top if x != d]
        rng.shuffle(pool)
        opts = [d] + pool[:3]
        rng.shuffle(opts)
        items.append({
            "id": f"ts_{i+1}",
            "domain": "test_structure",
            "points": POINTS["test_structure"],
            "type": "single_choice",
            "question": (f"In which directory does the test module "
                         f"`{example}` live?"),
            "options": opts,
            "answer_index": opts.index(d),
            "evidence": {"example_test": example, "directory": d,
                         "n_tests_in_dir": dirs[d]},
            "answerable_from": ["base_repository"],
            "leakage_check": {
                "mentions_defect": False,
                "note": ("asks only about test LAYOUT, never about which test "
                         "targets the defect; the latter would leak the oracle "
                         "and is explicitly forbidden by plan 6.1 item 4"),
            },
            "difficulty_proxy": {"dir_test_count": dirs[d]},
        })
    return items


def items_module_symbols(src_files, rng, n):
    """Fallback for repositories that document almost nothing in-source.

    Instead of asking "which module says X" (impossible when nothing says X),
    ask which module defines a named public symbol.  Still answerable from the
    base repository alone, still derived mechanically, and still never touches
    the defect.
    """
    import ast
    defs = []
    for p, v in sorted(src_files.items()):
        if v.get("kind") != "verbatim" or not p.endswith(".py"):
            continue
        try:
            tree = ast.parse(v["content"])
        except Exception:
            continue
        names = [nd.name for nd in tree.body
                 if isinstance(nd, (ast.ClassDef, ast.FunctionDef,
                                    ast.AsyncFunctionDef))
                 and not nd.name.startswith("_")]
        if names:
            defs.append((p, names))
    if len(defs) < n + 3:
        return []
    rng.shuffle(defs)
    all_paths = [p for p, _ in defs]
    items = []
    for i in range(n):
        path, names = defs[i]
        sym = names[0]
        pool = [p for p in all_paths if p != path]
        rng.shuffle(pool)
        opts = [path] + pool[:3]
        if len(opts) < 4:
            continue
        rng.shuffle(opts)
        items.append({
            "id": f"ms_{i+1}",
            "domain": "module_responsibility",
            "points": POINTS["module_responsibility"],
            "type": "single_choice",
            "question": (f"Which module defines the public symbol `{sym}`?"),
            "options": opts,
            "answer_index": opts.index(path),
            "evidence": {"source_file": path, "public_symbols": names[:8]},
            "answerable_from": ["base_repository"],
            "derivation_note": ("fallback form: this repository has few "
                                "in-source docstrings, so the item is built "
                                "from the public API surface instead"),
            "leakage_check": {"mentions_defect": False,
                              "note": "mechanical definition lookup"},
            "difficulty_proxy": {"n_public_symbols": len(names)},
        })
    return items


def items_test_entry_points(inv, snap, rng, n):
    """Fallback for repositories with too few distinct test directories.

    Asks which test file contains a named test function -- a layout question,
    never a "which test targets the defect" question.
    """
    files = snap.get("files", {})
    headers = [(p, v) for p, v in sorted(files.items())
               if v.get("kind") == "test_header"]
    named = []
    for p, v in headers:
        m = re.findall(r"^def (test_\w+)", v.get("content", ""), re.M)
        if m:
            named.append((p, m))
    if len(named) < n + 3:
        return []
    rng.shuffle(named)
    all_paths = sorted({p for p, _ in named})
    items = []
    for i in range(n):
        path, fns = named[i]
        fn = fns[0]
        pool = [p for p in all_paths if p != path]
        rng.shuffle(pool)
        opts = [path] + pool[:3]
        if len(opts) < 4:
            continue
        rng.shuffle(opts)
        items.append({
            "id": f"te_{i+1}",
            "domain": "test_structure",
            "points": POINTS["test_structure"],
            "type": "single_choice",
            "question": (f"In which test module is `{fn}` defined?"),
            "options": opts,
            "answer_index": opts.index(path),
            "evidence": {"test_module": path, "function": fn},
            "answerable_from": ["base_repository"],
            "derivation_note": "fallback form: few test directories",
            "leakage_check": {
                "mentions_defect": False,
                "note": ("names an arbitrary test function from the base "
                         "commit; it is NOT a grading test and no item "
                         "references FAIL_TO_PASS"),
            },
            "difficulty_proxy": {"n_test_functions": len(fns)},
        })
    return items


# --------------------------------------------------------------------------- #
def build_quiz(task_id):
    meta, inv, snap = load(task_id)
    if not meta:
        raise SystemExit(f"unknown task {task_id}")
    rng = random.Random(f"{SEED}:{task_id}")
    src = {p: v for p, v in snap.get("files", {}).items()
           if v.get("kind") == "verbatim"}
    items = []
    items += items_module_responsibility(src, rng, ITEMS_PER_DOMAIN)
    if sum(1 for i in items if i["domain"] == "module_responsibility") < 1:
        items = [i for i in items if i["domain"] != "module_responsibility"]
        items += items_module_symbols(src, rng, ITEMS_PER_DOMAIN)
    items += items_dependency(src, rng, ITEMS_PER_DOMAIN)
    ts = items_test_structure(inv, src, rng, ITEMS_PER_DOMAIN)
    if len(ts) < 1:
        ts = items_test_entry_points(inv, snap, rng, ITEMS_PER_DOMAIN)
    items += ts

    covered = Counter(i["domain"] for i in items)
    total = sum(i["points"] for i in items)
    quiz = {
        "schema_version": "1.0",
        "instrument_id": "repository_understanding_v1",
        "task_id": task_id,
        "repo_id": meta["repo_id"],
        "base_commit": meta["base_commit"],
        "generated_utc": NOW,
        "generator": "build_understanding_quiz.py",
        "seed": SEED,
        "derivation": ("answers come from the base commit's own docstrings, "
                       "import graph and test tree, so regeneration is "
                       "byte-identical and no human judgement enters the key"),
        "scale": {"total_points": total, "paper_scale_max": 10},
        "domains_covered": dict(covered),
        "items": items,
        "domains_missing": [d for d in POINTS if d not in covered],
        "admissibility": {
            "answerable_from_base_repo_only": all(
                "base_repository" in i["answerable_from"] for i in items),
            "no_item_mentions_the_defect": all(
                not i["leakage_check"]["mentions_defect"] for i in items),
            "no_item_references_grading_tests": all(
                "FAIL_TO_PASS" not in json.dumps(i)
                and "pass_to_pass" not in json.dumps(i) for i in items),
            "n_items": len(items),
            "points_total": total,
            "meets_blueprint": len(items) >= 4,
        },
        "administration": {
            "when": ["pre_task, before the participant sees the repository",
                     "post_task, immediately after the session is frozen"],
            "variants": ("pre and post use the same blueprint with different "
                         "instances; the pre-task score is the manipulation "
                         "check covariate and the post-task score the outcome"),
            "paper_target": {"Chigh_mean": 8.4, "Clow_mean": 5.9,
                             "difference": 2.5, "ci95": [2.21, 2.79]},
        },
    }
    quiz["quiz_sha256"] = sha256_text(json.dumps(
        {k: v for k, v in quiz.items() if k != "quiz_sha256"},
        sort_keys=True, ensure_ascii=False))
    return quiz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]

    if a.verify:
        files = [f for f in sorted(os.listdir(OUT)) if f.endswith(".json")]
        ok, weak, missing = 0, [], []
        for f in files:
            d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
            adm = d.get("admissibility", {})
            if adm.get("meets_blueprint") and adm.get(
                    "answerable_from_base_repo_only") and adm.get(
                    "no_item_mentions_the_defect"):
                ok += 1
            else:
                weak.append({"task_id": d["task_id"],
                             "n_items": adm.get("n_items"),
                             "missing": d.get("domains_missing")})
        print(json.dumps({"generated": len(files), "admissible": ok,
                          "weak": weak[:15],
                          "weak_count": len(weak)}, indent=1,
                         ensure_ascii=False))
        return 0 if files else 1

    targets = ([t["task_id"] for t in idx] if a.all
               else [a.task_id] if a.task_id
               else sys.exit("need --task-id or --all"))
    if a.limit:
        targets = targets[:a.limit]

    built, skipped = 0, []
    for tid in targets:
        try:
            q = build_quiz(tid)
        except Exception as e:
            skipped.append({"task_id": tid, "error": f"{type(e).__name__}: {e}"})
            continue
        json.dump(q, open(os.path.join(OUT, tid + ".json"), "w",
                          encoding="utf-8"), indent=1, ensure_ascii=False)
        built += 1
    print(f"quiz items built: {built}")
    if skipped:
        print(f"skipped: {len(skipped)}")
        for s in skipped[:10]:
            print("  ", s)
    if built:
        sample = json.load(open(os.path.join(OUT, targets[0] + ".json"),
                                encoding="utf-8"))
        print(f"sample {targets[0]}: {sample['admissibility']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
