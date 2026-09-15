#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Task admission gate -- classify every task by whether its oracle is reproducible.

Why this exists
  A calibration run on six babel tasks reproduced the oracle in only three.  The
  three failures split into two kinds that need OPPOSITE handling:

    collection_error   the frozen tests do not run at all in this environment
                       (base and gold both fail to collect).  This is an
                       infrastructure fault: plan 13.1 / P6 say such a session
                       is reported as an environment variable and NOT counted as
                       a participant outcome.

    gold_does_not_pass the gold patch does not make the fail-to-pass tests pass.
                       This is a dataset labelling defect.  No amount of
                       environment work fixes it, so the task must leave the
                       main experiment.

  Treating those two the same would either discard usable tasks or -- far worse
  -- keep a task whose gold patch is incomplete and then record real
  participants as having failed it.

The gate is deliberately conservative and pre-registered: it decides from the
frozen evaluation spec and a calibration run, never from observed session
outcomes, so running it cannot bias the experiment it protects.

CLI
  python tools/admission_gate.py classify --task-id <id>     one task
  python tools/admission_gate.py batch --repo <repo>         one repository
  python tools/admission_gate.py report                      aggregate + exclusions
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
GATE = os.path.join(ROOT, "audit", "admission_gate")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "evaluation"))
import task_env as te          # noqa: E402
import evaluate as ev          # noqa: E402

PYTEST_COLLECTION_ERROR = 4     # pytest exit code for usage/collection errors

VERDICTS = {
    "admitted": ("the environment distinguishes the defect from the fix; the "
                 "task may enter the experiment and holdout authoring"),
    "excluded_gold_incomplete": ("the gold patch does not pass its own "
                                 "fail-to-pass tests; excluded from the main "
                                 "experiment because it would misattribute a "
                                 "dataset defect to participants"),
    "environment_fault": ("the frozen tests do not run; usable only if the "
                          "environment is repaired, otherwise report as an "
                          "infrastructure variable (plan 13.1, signal P6)"),
    "no_spec": "no evaluation spec available",
}


def _pytest(task_id, wd, nodes):
    meta, _, _ = te.load(task_id)
    py = te.venv_python(meta["repo_id"]) or sys.executable
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        p = subprocess.run([py, "-m", "pytest", "-q", "--no-header",
                            "-p", "no:cacheprovider"] + (nodes or []),
                           cwd=wd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           timeout=1800)
    except subprocess.TimeoutExpired:
        return {"rc": -1, "summary": "timeout", "tail": ""}
    tail = "\n".join([l for l in (p.stdout or "").splitlines()
                      if l.strip()][-3:])
    return {"rc": p.returncode, "summary": tail, "tail": (p.stdout or "")[-1200:]}


def classify(task_id):
    try:
        spec = ev.load_spec(task_id)
    except SystemExit:
        return {"task_id": task_id, "verdict": "no_spec",
                "reason": VERDICTS["no_spec"]}
    f2p = spec.get("fail_to_pass") or []
    tp = ev.resolve_dataset_path(spec.get("test_patch_file"))
    gp = ev.resolve_dataset_path(spec.get("gold_patch_file"))

    rec = {"task_id": task_id, "repo_id": spec.get("repo_id"),
           "split": spec.get("split"), "base_commit": spec.get("base_commit"),
           "n_f2p": len(f2p), "checked_utc": NOW,
           "gold_patch_present": bool(gp), "test_patch_present": bool(tp)}

    if not f2p:
        rec.update(verdict="environment_fault",
                   reason="evaluation spec lists no fail-to-pass tests")
        return rec

    # base + test patch
    wd, how = te.workspace(task_id)
    rec["workspace_source"] = how
    te.apply_patch(wd, tp)
    base = _pytest(task_id, wd, f2p)
    rec["base"] = base

    # base + test patch + gold
    wd2, _ = te.workspace(task_id)
    te.apply_patch(wd2, tp)
    applied = te.apply_patch(wd2, gp) if gp else {"applied": False}
    rec["gold_applied"] = applied
    gold = _pytest(task_id, wd2, f2p)
    rec["gold"] = gold

    if base["rc"] == PYTEST_COLLECTION_ERROR and gold["rc"] == \
            PYTEST_COLLECTION_ERROR:
        rec.update(verdict="environment_fault", **{
            "reason": ("frozen tests fail to collect in both revisions; the "
                       "suite cannot run in this environment"),
            "classification_basis": "pytest exit code 4 in base and gold"})
    elif not applied.get("applied"):
        rec.update(verdict="environment_fault",
                   reason=f"gold patch did not apply: {applied.get('reason')}")
    elif gold["rc"] != 0:
        rec.update(verdict="excluded_gold_incomplete", **{
            "reason": ("gold patch applied but the fail-to-pass tests still do "
                       "not pass; the gold patch is partial or depends on "
                       "companion changes not present in dataset/gold/patches"),
            "classification_basis": f"gold rc={gold['rc']} with patch applied"})
    elif base["rc"] == 0:
        rec.update(verdict="environment_fault", **{
            "reason": ("the fail-to-pass tests already pass at base_commit, so "
                       "this task cannot discriminate defect from fix"),
            "classification_basis": "base rc=0 with test patch applied"})
    else:
        rec.update(verdict="admitted", **{
            "reason": VERDICTS["admitted"],
            "classification_basis": f"base rc={base['rc']}, gold rc={gold['rc']}"})

    rec["verdict_reason"] = VERDICTS.get(rec["verdict"], "")
    return rec


def write(rec):
    os.makedirs(GATE, exist_ok=True)
    p = os.path.join(GATE, rec["task_id"] + ".json")
    json.dump(rec, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return p


def report():
    if not os.path.isdir(GATE):
        print("no gate results yet")
        return 1
    from collections import Counter
    rows = []
    for f in sorted(os.listdir(GATE)):
        if f.startswith("_") or not f.endswith(".json"):
            continue
        try:
            rows.append(json.load(open(os.path.join(GATE, f),
                                       encoding="utf-8")))
        except Exception:
            continue
    dist = Counter(r.get("verdict") for r in rows)
    by_split = {}
    for r in rows:
        by_split.setdefault(r.get("split"), Counter())[r.get("verdict")] += 1
    summary = {
        "generated_utc": NOW,
        "n_classified": len(rows),
        "n_total_tasks": 216,
        "distribution": dict(dist),
        "by_split": {k: dict(v) for k, v in by_split.items()},
        "excluded_gold_incomplete": sorted(
            r["task_id"] for r in rows
            if r.get("verdict") == "excluded_gold_incomplete"),
        "environment_fault": sorted(
            r["task_id"] for r in rows if r.get("verdict") == "environment_fault"),
        "admitted": sorted(r["task_id"] for r in rows
                           if r.get("verdict") == "admitted"),
        "handling_rules": {
            "admitted": "enters the experiment and the holdout authoring queue",
            "environment_fault": ("reported as an infrastructure variable and "
                                  "excluded from participant outcomes "
                                  "(plan 13.1, paper signal P6); repair then "
                                  "re-classify"),
            "excluded_gold_incomplete": ("removed from the main experiment with "
                                         "the reason retained in the data "
                                         "package; not repairable by "
                                         "environment work"),
        },
        "pre_registered": True,
        "decided_from": ("the frozen evaluation spec plus a calibration run; "
                         "never from observed session outcomes, so running the "
                         "gate cannot bias the experiment it protects"),
    }
    json.dump(summary, open(os.path.join(GATE, "_summary.json"), "w",
                            encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps({k: summary[k] for k in
                      ("n_classified", "distribution", "by_split")},
                     indent=1, ensure_ascii=False))
    print(f"\nexcluded (gold incomplete): {summary['excluded_gold_incomplete']}")
    print(f"environment faults        : {summary['environment_fault']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("classify")
    p.add_argument("--task-id", action="append", required=True)
    def _c(a):
        for t in a.task_id:
            r = classify(t)
            write(r)
            print(f"{t}: {r['verdict']}  ({r.get('reason', '')[:90]})")
    p.set_defaults(fn=_c)

    p = sub.add_parser("batch")
    p.add_argument("--repo")
    p.add_argument("--limit", type=int, default=0)
    def _b(a):
        idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                             encoding="utf-8"))["tasks"]
        targets = [t["task_id"] for t in idx
                   if not a.repo or t["repo_id"] == a.repo]
        if a.limit:
            targets = targets[:a.limit]
        for i, t in enumerate(targets, 1):
            r = classify(t)
            write(r)
            print(f"[{i}/{len(targets)}] {t}: {r['verdict']}", flush=True)
    p.set_defaults(fn=_b)

    p = sub.add_parser("report")
    p.set_defaults(fn=lambda a: report())

    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
