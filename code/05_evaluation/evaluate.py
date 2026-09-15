#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase C -- Evaluation harness (plan 11.1, 11.2, 8 step 9)

Runs hidden evaluation in an independent clean workspace that never shares
state with the participant's session directory.  Two stages:

  1. benchmark   -- apply the frozen test patch, then the candidate patch, run
                    the frozen test command, and decide `benchmark_resolved`
                    from the F2P / P2P oracle.
  2. holdout     -- if `holdout_tests/<task_id>/` exists, apply and run those
                    tests too; only then can `enhanced_resolved` be true.

Plan 11.2 requires each holdout test to fail at `base_commit`, pass on the gold
patch, and be deterministic over 5 runs.  `--verify-holdout` automates that
check, which is how a holdout suite gets admitted.

Plan 11.1 states Enhanced Resolved must NOT use gold-patch similarity, so no
patch-similarity metric is computed anywhere in this file.

Usage
  python evaluate.py --session-id D-S0001
  python evaluate.py --task-id aiogram__aiogram-1469 --patch path/to/final.patch
  python evaluate.py --verify-holdout --task-id <id>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
CACHE = os.path.join(ROOT, "repo_cache")
EVAL = os.path.join(ROOT, "evaluation")
WORK = os.path.join(ROOT, "_eval_workspaces")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PYTEST_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+(\S+)")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def run(cmd, cwd=None, timeout=3600, env=None):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=env, shell=isinstance(cmd, str))
    return p.returncode, (p.stdout or ""), (p.stderr or ""), time.time() - t0


def git(args, cwd, timeout=1800):
    rc, out, err, dt = run(["git"] + args, cwd=cwd, timeout=timeout)
    return rc, out, err


def repo_dir_of(slug):
    return os.path.join(CACHE, slug)


def fresh_workspace(slug, base_commit, tag):
    """Independent clean checkout -- never the participant's directory."""
    src = repo_dir_of(slug)
    if not os.path.isdir(os.path.join(src, ".git")):
        raise SystemExit(f"no clone cache for {slug}")
    dst = os.path.join(WORK, f"{slug}__{tag}")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rc, out, err = git(["worktree", "add", "--detach", "--force", dst,
                        base_commit], cwd=src)
    if rc != 0:
        # fall back to clone + checkout
        rc2, out2, err2, _ = run(["git", "clone", "--no-hardlinks", src, dst])
        if rc2 != 0:
            raise SystemExit(f"cannot create workspace: {err[-300:]} {err2[-300:]}")
        git(["checkout", "--detach", base_commit], cwd=dst)
    rc, st, _ = git(["status", "--porcelain"], cwd=dst)
    if st.strip():
        raise SystemExit("evaluation workspace is dirty; refusing to evaluate")
    return dst


def cleanup_workspace(slug, path):
    src = repo_dir_of(slug)
    run(["git", "worktree", "remove", "--force", path], cwd=src)
    shutil.rmtree(path, ignore_errors=True)


def resolve_dataset_path(rel):
    """Resolve a path recorded in an evaluation spec.

    Specs store dataset-relative paths (e.g. "gold/patches/x.patch"), but the
    test-patch entry was written relative to the TIFS workspace instead. Both
    forms appear in already-frozen specs, so handle them explicitly rather than
    silently producing a doubled prefix like TIFS/gold/patches/... .
    """
    if not rel:
        return None
    if os.path.isabs(rel):
        return rel if os.path.exists(rel) else None
    tifs = r"C:\Users\Administrator\Desktop\TIFS"
    for base in (tifs, DS):
        cand = os.path.join(base, rel.replace("/", os.sep))
        if os.path.exists(cand):
            return cand
    # last resort: strip a leading dataset dir name and retry
    parts = rel.replace("\\", "/").split("/")
    if parts and parts[0] in ("dataset", "gold", "benchmark_tests"):
        cand = os.path.join(DS, *parts[1:])
        if os.path.exists(cand):
            return cand
    return os.path.join(tifs, rel.replace("/", os.sep))


def load_spec(task_id):
    p = os.path.join(ROOT, "evaluation_spec", task_id + ".yaml")
    if not os.path.exists(p):
        raise SystemExit(f"no evaluation spec for {task_id}")
    import yaml
    return yaml.safe_load(open(p, encoding="utf-8"))


def apply_patch(workdir, patch_path, label):
    if not patch_path or not os.path.exists(patch_path):
        return {"label": label, "applied": False, "reason": "patch missing",
                "path": patch_path}
    for args in (["apply", "-v", "--whitespace=nowarn", patch_path],
                 ["apply", "-v", "--3way", "--whitespace=nowarn", patch_path]):
        rc, out, err = git(args, workdir)
        if rc == 0:
            return {"label": label, "applied": True, "command":
                    "git " + " ".join(args[:2]), "stderr_tail": err[-300:]}
    return {"label": label, "applied": False,
            "reason": (err or out)[-500:], "path": patch_path}


def parse_pytest(output):
    results = {}
    for line in output.splitlines():
        m = PYTEST_LINE.match(line.strip())
        if m:
            results[m.group(2)] = m.group(1)
    summary = ""
    for line in reversed(output.splitlines()):
        if re.search(r"\b\d+ (passed|failed|error)", line):
            summary = line.strip()
            break
    counts = {}
    for k in ("passed", "failed", "error", "errors", "skipped", "xfailed",
              "xpassed"):
        m = re.search(rf"(\d+) {k}\b", output)
        if m:
            counts[k.rstrip("s") if k == "errors" else k] = int(m.group(1))
    return results, summary, counts


def decide(f2p, p2p, results, returncode=None):
    """Plan 11.1: resolved iff every F2P passes AND every P2P still passes.

    A run that could not collect its tests (missing dependency, broken
    environment) is **not** a failed repair.  Conflating the two would turn an
    infrastructure fault into a wrong scientific claim, so `suite_status`
    separates them and `benchmark_resolved` is left undefined when the suite
    never ran.
    """
    suite_status = "executed"
    if returncode is not None and returncode not in (0, 1, 2):
        # pytest exit codes: 0 ok, 1 tests failed, 2 interrupted;
        # 3 internal error, 4 usage error, 5 no tests collected
        suite_status = ("collection_error_or_missing_dependency"
                        if not results else "abnormal_exit")
    elif f2p and not results:
        suite_status = "no_test_results_parsed"

    f2p_pass = [t for t in f2p if results.get(t) in ("PASSED", "XFAIL")]
    f2p_fail = [t for t in f2p if results.get(t) in ("FAILED", "ERROR")]
    f2p_missing = [t for t in f2p if t not in results]
    p2p_pass = [t for t in p2p if results.get(t) in ("PASSED", "XFAIL")]
    p2p_fail = [t for t in p2p if results.get(t) in ("FAILED", "ERROR")]
    p2p_missing = [t for t in p2p if t not in results]

    resolved = None
    if suite_status == "executed":
        resolved = (len(f2p_fail) == 0 and len(f2p_missing) == 0
                    and len(p2p_fail) == 0)
    return {
        "suite_status": suite_status,
        "benchmark_resolved": bool(resolved) if resolved is not None else None,
        "benchmark_resolved_undefined_reason": (
            None if resolved is not None else
            "the frozen test suite did not execute in this workspace, so no "
            "correctness claim can be made (plan 13.1: environment faults are "
            "not participant outcomes)"),
        "f2p_total": len(f2p), "f2p_pass": len(f2p_pass),
        "f2p_fail": len(f2p_fail), "f2p_missing": len(f2p_missing),
        "p2p_total": len(p2p), "p2p_pass": len(p2p_pass),
        "p2p_fail": len(p2p_fail), "p2p_missing": len(p2p_missing),
        "regression_count": len(p2p_fail),
        "regression_rate": round(len(p2p_fail) / len(p2p), 4) if p2p else None,
        "failed_tests": (f2p_fail + p2p_fail)[:50],
    }


def holdout_dir(task_id):
    return os.path.join(DS, "holdout_tests", task_id)


def run_stage(workdir, spec, candidate_patch, task_id, out_dir, extra_patch=None,
              label="benchmark"):
    os.makedirs(out_dir, exist_ok=True)
    log = []
    a = apply_patch(workdir, resolve_dataset_path(spec.get("test_patch_file")),
                    "test_patch")
    log.append(a)
    if not a["applied"]:
        return {"stage": label, "ok": False,
                "error": "frozen test patch did not apply",
                "detail": a}, None
    if extra_patch:
        b = apply_patch(workdir, extra_patch, "holdout_tests")
        log.append(b)
        if not b["applied"]:
            return {"stage": label, "ok": False,
                    "error": "holdout patch did not apply",
                    "detail": b}, None
    if candidate_patch:
        c = apply_patch(workdir, candidate_patch, "candidate_patch")
        log.append(c)
        if not c["applied"]:
            return {"stage": label, "ok": False,
                    "error": "candidate patch did not apply",
                    "detail": c}, None

    cmd = spec.get("test_command")
    if isinstance(cmd, list):
        cmd = " && ".join(cmd)
    cmd = cmd or "pytest -rA"
    t0 = time.time()
    rc, out, err, dt = run(cmd, cwd=workdir, timeout=5400)
    open(os.path.join(out_dir, f"{label}_stdout.txt"), "w", encoding="utf-8",
         newline="\n").write(out)
    open(os.path.join(out_dir, f"{label}_stderr.txt"), "w", encoding="utf-8",
         newline="\n").write(err)
    results, summary, counts = parse_pytest(out)
    return {"stage": label, "ok": True, "command": cmd, "returncode": rc,
            "seconds": round(dt, 1), "summary": summary, "counts": counts,
            "n_test_results": len(results), "patch_log": log,
            "stderr_tail": err[-1500:]}, results


def evaluate(task_id, candidate_patch, session_id=None, keep=False):
    spec = load_spec(task_id)
    slug = task_id.split("-")[0]
    base = spec["base_commit"]
    tag = (session_id or "adhoc") + "_" + str(int(time.time()))
    out_root = os.path.join(EVAL, session_id or task_id)
    os.makedirs(out_root, exist_ok=True)

    metrics = {
        "schema_version": "1.0",
        "task_id": task_id,
        "session_id": session_id,
        "repo_id": spec["repo_id"],
        "base_commit": base,
        "evaluated_utc": NOW,
        "evaluation_version": "1.0",
        "candidate_patch": candidate_patch,
        "candidate_patch_sha256": sha256_file(candidate_patch)
        if candidate_patch and os.path.exists(candidate_patch) else None,
        "gold_patch_used_for_scoring": False,
        "gold_patch_similarity_computed": False,
    }

    bench_dir = os.path.join(out_root, "benchmark")
    wd = fresh_workspace(slug, base, tag + "_bench")
    try:
        bench, results = run_stage(wd, spec, candidate_patch, task_id, bench_dir,
                                   label="benchmark")
    finally:
        if not keep:
            cleanup_workspace(slug, wd)
    metrics["benchmark"] = bench
    if results is not None:
        metrics["benchmark"].update(
            decide(spec.get("fail_to_pass") or [],
                   spec.get("pass_to_pass") or [], results,
                   returncode=bench.get("returncode")))
    metrics["benchmark_resolved"] = metrics["benchmark"].get(
        "benchmark_resolved")
    metrics["suite_status"] = metrics["benchmark"].get("suite_status")
    if metrics["benchmark_resolved"] is None:
        metrics["environment_fault"] = {
            "detected": True,
            "reason": metrics["benchmark"].get(
                "benchmark_resolved_undefined_reason"),
            "stderr_tail": (bench.get("stderr_tail") or "")[-500:],
            "plan_reference": ("13.1 requires environment faults to be "
                               "recorded and handled by a pre-registered rule, "
                               "not scored as participant outcomes"),
        }

    # ---------------------------------------------------------------- holdout
    hd = holdout_dir(task_id)
    has_holdout = os.path.isdir(hd) and any(
        f.endswith(".py") or f.endswith(".diff") or f.endswith(".patch")
        for f in os.listdir(hd)) if os.path.isdir(hd) else False
    metrics["holdout_status"] = "available" if has_holdout else "not_authored"
    metrics["enhanced_resolved"] = None

    if has_holdout:
        hp = None
        for f in sorted(os.listdir(hd)):
            if f.endswith((".diff", ".patch")):
                hp = os.path.join(hd, f)
                break
        hold_dir = os.path.join(out_root, "holdout")
        wd2 = fresh_workspace(slug, base, tag + "_hold")
        try:
            ho, hres = run_stage(wd2, spec, candidate_patch, task_id, hold_dir,
                                 extra_patch=hp, label="holdout")
        finally:
            if not keep:
                cleanup_workspace(slug, wd2)
        metrics["holdout"] = ho
        if hres is not None:
            hf2p = [t for t, v in hres.items() if v == "PASSED"]
            metrics["holdout"]["n_passed"] = len(hf2p)
            metrics["enhanced_resolved"] = bool(
                metrics["benchmark_resolved"] and ho.get("ok")
                and ho.get("returncode") == 0)
    else:
        metrics["enhanced_resolved_note"] = (
            "plan 11.2 holdout tests have not been authored for this task, so "
            "Enhanced Resolved is undefined; benchmark_resolved is reported")
    if metrics.get("benchmark_resolved") is None:
        metrics["enhanced_resolved"] = None
        metrics["enhanced_resolved_note"] = (
            "benchmark suite did not execute, so Enhanced Resolved is "
            "undefined regardless of holdout availability")

    # semantic review is authored by a human reviewer, not computed here
    metrics["semantic_review"] = {"status": "not_reviewed", "reviewer": None,
                                  "verdict": None}
    metrics["unintended_change"] = None

    json.dump(metrics, open(os.path.join(out_root, "metrics.json"), "w",
                            encoding="utf-8"), indent=1, ensure_ascii=False)
    return metrics


def verify_holdout(task_id, runs=5):
    """Plan 11.2 acceptance: fails at base_commit, passes on gold, deterministic."""
    spec = load_spec(task_id)
    slug = task_id.split("-")[0]
    base = spec["base_commit"]
    hd = holdout_dir(task_id)
    if not os.path.isdir(hd):
        raise SystemExit(f"no holdout_tests/{task_id}")
    hp = None
    for f in sorted(os.listdir(hd)):
        if f.endswith((".diff", ".patch")):
            hp = os.path.join(hd, f)
    report = {"task_id": task_id, "attempts": [], "runs_required": runs}
    gold = resolve_dataset_path(spec.get("gold_patch_file"))
    for label, cand in (("base", None), ("gold", gold)):
        outs = []
        for i in range(runs if label == "gold" else 1):
            wd = fresh_workspace(slug, base, f"vh_{label}_{i}_{int(time.time())}")
            try:
                st, res = run_stage(wd, spec, cand, task_id,
                                    os.path.join(EVAL, "_holdout_verify",
                                                 task_id, f"{label}_{i}"),
                                    extra_patch=hp, label=f"{label}_{i}")
            finally:
                cleanup_workspace(slug, wd)
            outs.append({"ok": st.get("ok"), "returncode": st.get("returncode"),
                         "summary": st.get("summary"),
                         "n_passed": sum(1 for v in (res or {}).values()
                                         if v == "PASSED")})
        report["attempts"].append({"label": label, "runs": outs})
    base_ok = all(r["returncode"] != 0 for r in report["attempts"][0]["runs"])
    gold_runs = report["attempts"][1]["runs"]
    gold_ok = all(r["returncode"] == 0 for r in gold_runs)
    det = len({r["summary"] for r in gold_runs}) == 1
    report["verdict"] = {
        "fails_at_base": base_ok,
        "passes_on_gold": gold_ok,
        "deterministic_over_5_runs": det,
        "accepted": base_ok and gold_ok and det,
    }
    os.makedirs(os.path.join(EVAL, "_holdout_verify", task_id), exist_ok=True)
    json.dump(report, open(os.path.join(EVAL, "_holdout_verify", task_id,
                                        "verification.json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id")
    ap.add_argument("--session-id")
    ap.add_argument("--patch")
    ap.add_argument("--keep-workspace", action="store_true")
    ap.add_argument("--verify-holdout", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()

    os.makedirs(EVAL, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    if a.verify_holdout:
        rep = verify_holdout(a.task_id, a.runs)
        print(json.dumps(rep["verdict"], indent=1))
        return

    if a.session_id and not a.task_id:
        mp = os.path.join(ROOT, "sessions", a.session_id,
                          "session_meta.json")
        if not os.path.exists(mp):
            raise SystemExit(f"no such session {a.session_id}")
        meta = json.load(open(mp, encoding="utf-8"))
        a.task_id = meta["task_id"]
        if not a.patch:
            a.patch = os.path.join(ROOT, "sessions", a.session_id,
                                   "final.patch")

    if not a.task_id:
        raise SystemExit("need --task-id or --session-id")
    m = evaluate(a.task_id, a.patch, a.session_id, a.keep_workspace)
    print(json.dumps({k: m.get(k) for k in
                      ("task_id", "benchmark_resolved", "enhanced_resolved",
                       "holdout_status")}, indent=1))
    if "benchmark" in m:
        print(json.dumps({k: v for k, v in m["benchmark"].items()
                          if k not in ("failed_tests",)}, indent=1))


if __name__ == "__main__":
    main()
