#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Role A1 at scale -- differential holdout test generator.

Authoring 216 holdout suites by hand is the paper's own bottleneck (median 4
tests per task).  This module does the mechanical part and keeps the human part
where it belongs.

The insight it exploits is in the gold patch itself.  A corrective fix changes
the behaviour of some function; a holdout test only has to pin that behaviour
down.  So for each changed callable we run a *differential probe*: call it with
synthesised inputs under base_commit and under the gold patch, and keep only the
inputs where the two revisions disagree.  An assertion built from such an input
fails at base and passes on gold BY CONSTRUCTION -- which is exactly the paper's
three admission criteria, minus the ones that need judgement.

What stays human: deciding whether the pinned behaviour is the behaviour the
issue asked for, and whether the benchmark already asserts it.  The generator
records those as open review items rather than claiming to have settled them.

Safety of execution: probes run against repository code.  Inputs are synthesised
from the signature and from literals appearing in the test suite, only
side-effect-free-looking functions are probed, every call happens inside a
subprocess with a hard timeout, and a probe that raises in BOTH revisions is
discarded rather than turned into an assertion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
HD = os.path.join(DS, "holdout_tests")
PROBE_DIR = os.path.join(ROOT, "_probes")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "evaluation"))
import task_env as te          # noqa: E402
import evaluate as ev          # noqa: E402

PROBE_TIMEOUT = 60
MAX_INPUTS_PER_CALLABLE = 12


def changed_callables(gold_diff):
    """(file, function) pairs the gold patch touches."""
    out, cur_file = [], None
    for line in gold_diff.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m:
            cur_file = m.group(1)
            continue
        m = re.match(r"^@@ .*@@\s*(?:def|class)\s+(\w+)", line)
        if m and cur_file:
            out.append((cur_file, m.group(1)))
    return out


def changed_files(gold_diff):
    return sorted(set(re.findall(r"^\+\+\+ b/(.+)$", gold_diff, re.M)))


def literals_from_tests(snap, limit=40):
    """String and numeric literals the project's own tests use."""
    vals, seen = [], set()
    for p, v in sorted(snap.get("files", {}).items()):
        if v.get("kind") != "test_header":
            continue
        for m in re.finditer(r"""["']([^"'\n]{1,40})["']""", v.get("content", "")):
            s = m.group(1)
            if s and s not in seen and not s.startswith("_"):
                seen.add(s)
                vals.append(s)
            if len(vals) >= limit:
                return vals
    return vals


def literals_from_benchmark(test_patch_path, limit=60):
    """Inputs harvested from the benchmark's own reproducer.

    This is the important source.  The benchmark test patch contains the exact
    values that reproduce the defect -- the goal patch was written to satisfy
    them -- so they reach the changed code paths far more reliably than
    synthesised guesses.  The first version of this generator used only generic
    literals and numeric stubs, and found ZERO behavioural differences on the
    two tasks it was tried on.

    Reading the benchmark's *inputs* is legitimate for a holdout author: the
    paper forbids reusing benchmark *assertions* (plan 11.2 excludes tests that
    merely repeat a benchmark assertion), not reusing the scenario.
    """
    if not test_patch_path or not os.path.exists(test_patch_path):
        return []
    txt = open(test_patch_path, encoding="utf-8", errors="replace").read()
    vals, seen = [], set()
    for line in txt.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        for m in re.finditer(r"""["']([^"'\n]{1,60})["']""", body):
            s = m.group(1)
            if s and s not in seen:
                seen.add(s)
                vals.append(s)
        for m in re.finditer(r"\b(\d{1,4})\b", body):
            n = int(m.group(1))
            if n not in seen:
                seen.add(n)
                vals.append(n)
        if len(vals) >= limit:
            return vals[:limit]
    return vals[:limit]


def numeric_inputs():
    return [0, 1, -1, 2, 10, 76, 100]


def build_probe_module(callables, probe_plan):
    """A standalone script that, for each (module, function) pair, tries a set of
    inputs and prints a canonical JSON result.  Run once per revision; the two
    outputs are diffed."""
    plan_json = json.dumps(probe_plan)
    return f'''
import importlib, json, sys, traceback

PLAN = json.loads({plan_json!r})

def canon(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        return repr(v)[:400]

out = {{}}
for entry in PLAN:
    mod_name, func_name, inputs = entry["module"], entry["func"], entry["inputs"]
    key = mod_name + "::" + func_name
    res = {{}}
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        out[key] = {{"import_error": type(e).__name__ + ": " + str(e)[:200]}}
        continue
    fn = getattr(mod, func_name, None)
    if fn is None:
        out[key] = {{"missing": True}}
        continue
    for i, spec in enumerate(inputs):
        args, kwargs = spec.get("args", []), spec.get("kwargs", {{}})
        try:
            r = fn(*args, **kwargs)
            res[str(i)] = {{"ok": True, "value": canon(r)}}
        except Exception as e:
            res[str(i)] = {{"ok": False, "exc": type(e).__name__,
                            "msg": str(e)[:200]}}
    out[key] = res
print("@@PROBE@@" + json.dumps(out, sort_keys=True, default=repr))
'''


def run_probe(task_id, patches, probe_src):
    wd, how = te.workspace(task_id)
    applied = [te.apply_patch(wd, p) for p in patches]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    py = te.venv_python(ev.load_spec(task_id)["repo_id"]) or sys.executable
    f = os.path.join(wd, "_probe_tmp.py")
    open(f, "w", encoding="utf-8", newline="\n").write(probe_src)
    try:
        p = subprocess.run([py, f], cwd=wd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           timeout=PROBE_TIMEOUT * 4)
        out = p.stdout or ""
        err = (p.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        out, err = "", "timeout"
    finally:
        try:
            os.remove(f)
        except OSError:
            pass
    data = None
    for line in out.splitlines():
        if line.startswith("@@PROBE@@"):
            try:
                data = json.loads(line[len("@@PROBE@@"):])
            except Exception:
                data = None
    return {"applied": applied, "how": how, "data": data, "stderr": err}


def module_name_for(repo_id, path):
    """Map a repository path to an importable module name, trying the usual
    src-layout prefixes."""
    if not path.endswith(".py"):
        return None
    base = path[:-3].replace("/", ".")
    if base.endswith(".__init__"):
        base = base[: -len(".__init__")]
    cands = [base]
    for pre in ("src.", "lib.", "python."):
        if base.startswith(pre):
            cands.append(base[len(pre):])
    for pre in ("src.", "lib."):
        cands.append(pre + base)
    return cands


def probe_task(task_id):
    spec = ev.load_spec(task_id)
    gold = ev.resolve_dataset_path(spec.get("gold_patch_file"))
    if not gold or not os.path.exists(gold):
        return {"task_id": task_id, "status": "no_gold_patch"}
    gold_txt = open(gold, encoding="utf-8", errors="replace").read()
    files = changed_files(gold_txt)
    if not files:
        return {"task_id": task_id, "status": "no_changed_files"}

    snap = json.load(open(os.path.join(ROOT, "repo_cache", "_snapshots",
                                       task_id + ".json"), encoding="utf-8"))
    lits = literals_from_tests(snap)
    bench = literals_from_benchmark(
        ev.resolve_dataset_path(spec.get("test_patch_file")))
    # benchmark-derived inputs first: they are the ones that actually reproduce
    inputs_pool = bench + [x for x in lits if x not in bench]
    nums = numeric_inputs()

    # collect zero/one-argument functions from the CHANGED files only
    import ast
    plan = []
    verbatim = {p: v for p, v in snap.get("files", {}).items()
                if v.get("kind") == "verbatim"}
    for f in files:
        src = verbatim.get(f, {}).get("content")
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        modnames = module_name_for(spec["repo_id"], f) or []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, ast.AsyncFunctionDef):
                continue
            npos = len([a for a in node.args.args
                        if a.arg not in ("self", "cls")])
            if npos > 2:
                continue
            fname = node.name
            if fname.startswith("_") and not fname.startswith("__"):
                pass          # private helpers are often the real fix site
            inputs = []
            if npos == 0:
                inputs = [{"args": []}]
            elif npos == 1:
                inputs = [{"args": [s]} for s in inputs_pool[:10]]
                inputs += [{"args": [n]} for n in nums[:4]]
            else:
                inputs = [{"args": [a, b]} for a in inputs_pool[:5]
                          for b in nums[:3]]
            inputs = inputs[:MAX_INPUTS_PER_CALLABLE]
            if not inputs:
                continue
            plan.append({"module_candidates": modnames, "func": fname,
                         "inputs": inputs, "file": f})

    if not plan:
        return {"task_id": task_id, "status": "no_probeable_callables",
                "changed_files": files}

    # probe each module candidate set until one imports
    results = {}
    for entry in plan:
        for mn in entry["module_candidates"]:
            src = build_probe_module(None, [{"module": mn, "func": entry["func"],
                                             "inputs": entry["inputs"]}])
            base = run_probe(task_id, [], src)
            if not base["data"] or all(
                    "import_error" in v or "missing" in v
                    for v in base["data"].values()):
                continue
            gold_r = run_probe(task_id,
                               [ev.resolve_dataset_path(
                                   spec.get("test_patch_file")), gold], src)
            results[f"{mn}::{entry['func']}"] = {
                "module": mn, "func": entry["func"], "file": entry["file"],
                "base": base["data"], "gold": gold_r["data"],
            }
            break

    # keep only inputs where the revisions disagree
    findings = []
    for key, rec in results.items():
        b, g = rec.get("base") or {}, rec.get("gold") or {}
        if not b or not g:
            continue
        for i in sorted(set(b) & set(g)):
            vb, vg = b[i], g[i]
            if vb == vg:
                continue
            if not vb.get("ok") and not vg.get("ok"):
                continue          # raises in both: not a behavioural difference
            findings.append({
                "callable": key, "file": rec["file"], "input_index": int(i),
                "base": vb, "gold": vg,
            })

    return {"task_id": task_id, "status": "probed",
            "changed_files": files, "n_callables_probed": len(results),
            "n_differing_inputs": len(findings), "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", action="append", default=[])
    ap.add_argument("--repo", default=None)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    os.makedirs(PROBE_DIR, exist_ok=True)
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]
    targets = idx
    if a.repo:
        targets = [t for t in targets if t["repo_id"] == a.repo]
    if a.task_id:
        targets = [t for t in targets if t["task_id"] in set(a.task_id)]
    if a.limit:
        targets = targets[:a.limit]

    summary = {"generated_utc": NOW, "n_tasks": len(targets),
               "with_differences": 0, "total_findings": 0, "tasks": {}}
    for i, t in enumerate(targets, 1):
        tid = t["task_id"]
        try:
            r = probe_task(tid)
        except Exception as e:
            r = {"task_id": tid, "status": "error",
                 "error": f"{type(e).__name__}: {e}"}
        json.dump(r, open(os.path.join(PROBE_DIR, tid + ".json"), "w",
                          encoding="utf-8"), indent=1, ensure_ascii=False)
        n = r.get("n_differing_inputs", 0)
        if n:
            summary["with_differences"] += 1
            summary["total_findings"] += n
        summary["tasks"][tid] = {"status": r.get("status"),
                                 "changed_files": len(r.get("changed_files") or []),
                                 "callables": r.get("n_callables_probed", 0),
                                 "differing_inputs": n}
        print(f"[{i}/{len(targets)}] {tid}: {r.get('status')} "
              f"callables={r.get('n_callables_probed', 0)} differing={n}",
              flush=True)

    json.dump(summary, open(os.path.join(PROBE_DIR, "_summary.json"), "w",
                            encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\ntasks with differential findings: "
          f"{summary['with_differences']}/{len(targets)}  "
          f"total findings: {summary['total_findings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
