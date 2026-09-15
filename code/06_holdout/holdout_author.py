#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Role A1 -- holdout test author.

The paper (V-G) requires, for every task, independent tests that
  (1) expose the defect at base_commit,
  (2) pass on the gold patch,
  (3) are deterministic over 5 isolated runs,
  (4) are not merely a duplicate assertion of an existing benchmark test,
and reports a median of 4 holdout tests per task (IQR 3-6).

This tool is the author's bench. It does the mechanical work -- clean
workspaces, patching, isolation, repetition, logging, admission decision -- so
the author's attention goes to the part that actually needs a human: reading
what the fix changed and pinning that behaviour down in a test that the
benchmark does not already assert.

Layout
  dataset/holdout_tests/<task_id>/holdout.diff      the tests (a git patch)
  dataset/holdout_tests/<task_id>/holdout.json      per-test metadata
  dataset/holdout_tests/_calibration/<task_id>.json what the benchmark asserts
  evaluation/holdout_construction_log.json          the V-G record

CLI
  calibrate  confirm base fails / gold passes, and dump the F2P node ids and
             the gold diff so the author can see what to pin down
  verify     run base / gold / 5x determinism against the authored holdout.diff
             and write or update the construction log
  status     which tasks have admissible holdout suites
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluation"))
import task_env as te          # noqa: E402
import evaluate as ev          # noqa: E402

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
HOLDOUT = os.path.join(DS, "holdout_tests")
CALIB = os.path.join(HOLDOUT, "_calibration")
LOG = os.path.join(ROOT, "evaluation", "holdout_construction_log.json")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

DETERMINISM_RUNS = 5
PYTEST_BASE = ["-q", "--no-header", "-p", "no:cacheprovider"]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def pytest(task_id, wd, nodeids=None, extra=None, timeout=3600):
    meta, _, _ = te.load(task_id)
    py = te.venv_python(meta["repo_id"]) or sys.executable
    args = list(PYTEST_BASE) + (nodeids or []) + (extra or [])
    p = subprocess.run([py, "-m", "pytest"] + args, cwd=wd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def summary_line(out):
    for line in reversed(out.splitlines()):
        if re.search(r"\b\d+ (passed|failed|error|skipped)", line):
            return line.strip()
    return ""


def outcome_key(out):
    """Determinism must compare OUTCOMES, not durations.

    pytest's summary line ends with "in 0.17s", so comparing the raw line would
    report two identical runs as different.  Normalising to counts plus the set
    of failed node ids is what 'deterministic over N runs' actually means.
    """
    counts = {}
    for k in ("passed", "failed", "error", "errors", "skipped", "xfailed",
              "xpassed", "warning", "warnings", "deselected"):
        m = re.search(rf"(\d+) {k}\b", out)
        if m:
            counts[k] = int(m.group(1))
    failed = sorted({m.group(1) for m in
                     re.finditer(r"^FAILED (\S+)", out, re.M)})
    errored = sorted({m.group(1) for m in
                      re.finditer(r"^ERROR (\S+)", out, re.M)})
    return {"counts": counts, "failed": failed, "errored": errored}


# --------------------------------------------------------------------------- #
def cmd_calibrate(a):
    """Etablish the ground truth the author needs before writing anything."""
    tid = a.task_id
    os.makedirs(CALIB, exist_ok=True)
    spec = ev.load_spec(tid)
    tp = ev.resolve_dataset_path(spec.get("test_patch_file"))
    gp = ev.resolve_dataset_path(spec.get("gold_patch_file"))
    f2p = spec.get("fail_to_pass") or []

    rec = {"task_id": tid, "calibrated_utc": NOW,
           "repo_id": spec.get("repo_id"), "base_commit": spec.get("base_commit"),
           "fail_to_pass": f2p,
           "pass_to_pass_count": len(spec.get("pass_to_pass") or []),
           "gold_patch_file": gp, "test_patch_file": tp}

    # stage 1: base + test_patch, no gold -> F2P must fail
    wd, how = te.workspace(tid)
    rec["workspace_source"] = how
    rec["apply_test_patch"] = te.apply_patch(wd, tp) if tp else None
    rc1, out1, err1 = pytest(tid, wd, f2p)
    rec["base_without_gold"] = {"rc": rc1, "summary": summary_line(out1),
                               "f2p_failed": rc1 != 0,
                               "stderr_tail": err1[-300:]}

    # stage 2: base + test_patch + gold -> F2P must pass
    wd2, _ = te.workspace(tid)
    te.apply_patch(wd2, tp)
    rec["apply_gold"] = te.apply_patch(wd2, gp) if gp else None
    rc2, out2, err2 = pytest(tid, wd2, f2p)
    rec["base_with_gold"] = {"rc": rc2, "summary": summary_line(out2),
                             "f2p_passed": rc2 == 0,
                             "stderr_tail": err2[-300:]}

    rec["verdict"] = {
        "oracle_reproduced": (rc1 != 0 and rc2 == 0),
        "note": ("oracle_reproduced must be true before holdout tests are "
                 "worth authoring: it proves this environment can distinguish "
                 "the defect from the fix"),
    }

    # what the fix actually changed -- the material the author works from
    if gp and os.path.exists(gp):
        gold = open(gp, encoding="utf-8", errors="replace").read()
        rec["gold_diff"] = gold[:20000]
        rec["gold_files"] = re.findall(r"^diff --git a/(\S+)", gold, re.M)
        rec["gold_added_lines"] = [l[1:] for l in gold.splitlines()
                                   if l.startswith("+") and not l.startswith("+++")][:200]
    if tp and os.path.exists(tp):
        tpd = open(tp, encoding="utf-8", errors="replace").read()
        rec["test_patch_added_lines"] = [l[1:] for l in tpd.splitlines()
                                         if l.startswith("+") and not l.startswith("+++")][:200]

    json.dump(rec, open(os.path.join(CALIB, tid + ".json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)

    print(json.dumps({k: rec[k] for k in
                      ("task_id", "oracle_reproduced", "base_without_gold",
                       "base_with_gold") if k in rec} |
                     {"verdict": rec["verdict"]}, indent=1, ensure_ascii=False))
    print(f"gold files: {rec.get('gold_files')}")
    print(f"calibration -> {os.path.relpath(os.path.join(CALIB, tid + '.json'), ROOT)}")
    return 0 if rec["verdict"]["oracle_reproduced"] else 1


def _discriminating(result):
    """How many node ids fail at base but pass on gold.

    A holdout suite whose tests all pass at base_commit is measuring nothing,
    so this number -- not the raw test count -- is what the construction log
    should record as the suite's strength.
    """
    base_failed = set()
    for r in result["attempts"]["base"]:
        base_failed |= set(r["outcome"].get("failed", []))
        base_failed |= set(r["outcome"].get("errored", []))
    return len(base_failed)


# --------------------------------------------------------------------------- #
def cmd_verify(a):
    tid = a.task_id
    hd = os.path.join(HOLDOUT, tid)
    diff = os.path.join(hd, "holdout.diff")
    if not os.path.exists(diff):
        sys.exit(f"no holdout.diff for {tid}")

    spec = ev.load_spec(tid)
    tp = ev.resolve_dataset_path(spec.get("test_patch_file"))
    gp = ev.resolve_dataset_path(spec.get("gold_patch_file"))
    nodes = a.node or []

    result = {"task_id": tid, "verified_utc": NOW,
              "holdout_diff_sha256": sha256_file(diff),
              "node_ids": nodes, "runs_required": DETERMINISM_RUNS,
              "attempts": {}}

    def scenario(label, patches, repeat=1):
        runs = []
        for i in range(repeat):
            wd, how = te.workspace(tid)
            reps = []
            for p in patches:
                reps.append({"patch": os.path.basename(p or ""),
                             **te.apply_patch(wd, p)})
            rc, out, err = pytest(tid, wd, nodes or None)
            runs.append({"run": i + 1, "rc": rc, "summary": summary_line(out),
                         "outcome": outcome_key(out),
                         "applied": reps, "stdout_tail": out[-600:],
                         "stderr_tail": err[-400:]})
        return runs

    result["attempts"]["base"] = scenario("base", [tp, diff])
    result["attempts"]["gold"] = scenario("gold", [tp, gp, diff])
    result["attempts"]["determinism"] = scenario(
        "determinism", [tp, gp, diff], repeat=DETERMINISM_RUNS)

    base_ok = all(r["rc"] != 0 for r in result["attempts"]["base"])
    gold_runs = result["attempts"]["gold"]
    gold_ok = all(r["rc"] == 0 for r in gold_runs)
    det_outcomes = {json.dumps(r["outcome"], sort_keys=True)
                    for r in result["attempts"]["determinism"]}
    det_ok = (len(det_outcomes) == 1
              and all(r["rc"] == 0 for r in result["attempts"]["determinism"]))

    # the suite size is what pytest actually collected on gold -- not the number
    # of --node arguments.  The first version recorded the latter, which
    # reported every suite as exactly one test.
    _gc = gold_runs[0]["outcome"]["counts"] if gold_runs else {}
    n_collected = sum(_gc.get(k, 0) for k in ("passed", "failed", "error",
                                              "skipped", "xfailed", "xpassed"))
    result["verdict"] = {
        "fails_at_base": base_ok,
        "passes_on_gold": gold_ok,
        "deterministic_over_5_runs": det_ok,
        "distinct_outcomes": [json.loads(x) for x in sorted(det_outcomes)],
        "n_discriminating_tests": _discriminating(result),
        "n_tests_collected": n_collected,
        "admitted": bool(base_ok and gold_ok and det_ok),
    }
    json.dump(result, open(os.path.join(hd, "verification.json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)

    # mirror into the paper's construction log
    log = {"schema_version": "1.0",
           "paper_reference": "Section V-G",
           "status": "in_progress",
           "updated_utc": NOW,
           "authoring_constraints": [
               "author did not run any experimental session",
               "author saw the issue, base commit and gold patch only",
               "author never saw a candidate patch or a delegation label"],
           "tasks": {}}
    if os.path.exists(LOG):
        try:
            log = json.load(open(LOG, encoding="utf-8"))
            log["updated_utc"] = NOW
        except Exception:
            pass
    log.setdefault("tasks", {})
    meta_p = os.path.join(hd, "holdout.json")
    hmeta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    log["tasks"][tid] = {
        "task_id": tid,
        "repo_id": spec.get("repo_id"),
        "n_holdout_tests": result["verdict"]["n_tests_collected"]
        or hmeta.get("n_tests"),
        "n_discriminating_tests": result["verdict"]["n_discriminating_tests"],
        "behaviour_covered": hmeta.get("behaviour_covered"),
        "why_not_duplicate": hmeta.get("why_not_duplicate"),
        "base_commit_result": "fail" if base_ok else "NOT_FAILING",
        "gold_patch_result": "pass" if gold_ok else "NOT_PASSING",
        "determinism_runs": DETERMINISM_RUNS,
        "determinism_outcome": result["verdict"]["distinct_outcomes"],
        "holdout_diff_sha256": result["holdout_diff_sha256"],
        "admitted": result["verdict"]["admitted"],
        "author_pseudonym": hmeta.get("author_pseudonym", "roleA1"),
        "verified_utc": NOW,
    }
    admitted = [t for t, v in log["tasks"].items() if v.get("admitted")]
    log["n_tasks_admitted"] = len(admitted)
    if admitted:
        counts = sorted(log["tasks"][t]["n_holdout_tests"] or 0
                        for t in admitted)
        median = counts[len(counts) // 2]
        log["tests_per_task"] = {"median": median,
                                 "min": counts[0], "max": counts[-1],
                                 "paper_target_median": 4,
                                 "paper_target_iqr": [3, 6]}
    json.dump(log, open(LOG, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)

    print(json.dumps(result["verdict"], indent=1, ensure_ascii=False))
    for lab in ("base", "gold"):
        for r in result["attempts"][lab]:
            print(f"  {lab:12s} rc={r['rc']} {r['summary']}")
    return 0 if result["verdict"]["admitted"] else 1


# --------------------------------------------------------------------------- #
def cmd_status(a):
    if not os.path.isdir(HOLDOUT):
        print("no holdout_tests directory")
        return 0
    tasks = sorted(d for d in os.listdir(HOLDOUT)
                   if os.path.isdir(os.path.join(HOLDOUT, d))
                   and not d.startswith("_"))
    print(f"authored holdout suites: {len(tasks)}")
    for t in tasks:
        v = os.path.join(HOLDOUT, t, "verification.json")
        if os.path.exists(v):
            d = json.load(open(v, encoding="utf-8"))
            verdict = d.get("verdict", {})
            print(f"  {t:52s} admitted={verdict.get('admitted')} "
                  f"base_fail={verdict.get('fails_at_base')} "
                  f"gold_pass={verdict.get('passes_on_gold')} "
                  f"det={verdict.get('deterministic_over_5_runs')}")
        else:
            print(f"  {t:52s} not verified")
    if os.path.exists(LOG):
        d = json.load(open(LOG, encoding="utf-8"))
        print(f"\nconstruction log: {d.get('n_tasks_admitted', 0)} admitted, "
              f"tests/task {d.get('tests_per_task')}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("calibrate"); p.add_argument("--task-id", required=True)
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("verify"); p.add_argument("--task-id", required=True)
    p.add_argument("--node", action="append", default=[])
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("status"); p.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
