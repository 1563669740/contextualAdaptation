#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Role E -- session pipeline rehearsal.

The paper collects 360 Discovery + 360 held-out sessions from 84 participants.
Before booking anyone, the SOP must be shown to work end to end on a real task
with the real runner: environment restore, condition exposure, event log,
checkpoints, the 75-minute cap, freeze, and offline evaluation.

This script drives `tools/session_runner.py` through the full SOP for one
allocated session, using a real task and a real workspace, and then runs the
metrics extractor and the evaluator over the frozen result.  It also exercises
the treatment-fidelity guards, because those are the parts most likely to be
wrong in a way nobody notices until the data is unusable.

It is a REHEARSAL: sessions it creates are marked `rehearsal: true` and are
excluded from analysis by construction.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
RUNNER = os.path.join(ROOT, "tools", "session_runner.py")
SESSIONS = os.path.join(ROOT, "sessions")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(args, timeout=1800):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def load_alloc(split="pilot"):
    p = os.path.join(ROOT, "splits", f"allocation_{split}.csv")
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rehearsal(split, condition_pref=None):
    rows = load_alloc(split)
    if condition_pref:
        rows = [r for r in rows if r["context_condition"] == condition_pref] \
            or rows
    row = rows[0]
    sid = row["session_id"]
    steps = []

    def step(name, args, expect_rc=(0,)):
        rc, out, err = sh([RUNNER] + args)
        ok = rc in expect_rc
        steps.append({"step": name, "args": args, "rc": rc, "ok": ok,
                      "stdout_tail": out[-400:], "stderr_tail": err[-300:]})
        return rc, out, err

    # start clean so the rehearsal is repeatable
    d = os.path.join(SESSIONS, sid)
    shutil.rmtree(d, ignore_errors=True)

    # SOP step 2: restore the environment from a clean workspace
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import task_env as te
    wd, how = te.workspace(row["task_id"])
    steps.append({"step": "restore_environment", "workspace": wd,
                  "source": how, "base_commit": row["base_commit"]})

    # SOP step 4-5: start the clock and the logs
    step("session_start", ["start", sid, "--workdir", wd, "--os-image",
                           "rehearsal-host"])

    # SOP step 6: record a realistic trajectory
    step("log_context_load", ["log", sid, "system", "context_load",
                              "--payload",
                              json.dumps({"package": row["task_id"],
                                          "condition":
                                          row["context_condition"]}),
                              "--source", "runner"])
    step("log_search", ["log", sid, "AI", "search", "--payload",
                        json.dumps({"query": "relevant symbol",
                                    "scope": "repo"}),
                        "--source", "ai_gateway", "--visible-to", "ai"])
    step("log_open", ["log", sid, "human", "open", "--payload",
                      json.dumps({"path": "src/module.py"}),
                      "--source", "ide_logger", "--visible-to", "human,ai"])
    step("log_test_fail", ["log", sid, "AI", "test", "--payload",
                           json.dumps({"command": "pytest -q", "exit_code": 1,
                                       "summary": "1 failed"}),
                           "--source", "test_wrapper"])
    step("log_edit", ["log", sid, "AI", "edit", "--payload",
                      json.dumps({"path": "src/module.py",
                                  "diff_ref": "diffs/0001.patch"}),
                      "--source", "ide_logger", "--worktree"])
    step("log_test_pass", ["log", sid, "AI", "test", "--payload",
                           json.dumps({"command": "pytest -q", "exit_code": 0,
                                       "summary": "1 passed"}),
                           "--source", "test_wrapper"])
    step("heartbeat", ["heartbeat", sid])

    # SOP step 7-8: stop and freeze
    step("stop", ["stop", sid, "participant_done"])
    step("freeze", ["freeze", sid])

    # treatment-fidelity guard probes, per regime
    regime = row["delegation"] or row.get("policy") or ""
    probes = []
    if regime == "ai_led":
        probes.append(("ai_led_human_intervention",
                       ["guard", sid, "human_correction", "--detail",
                        "rehearsal probe"], (1,)))
    if regime == "shared_control":
        probes.append(("shared_control_gate",
                       ["guard", sid, "advance_without_checkpoint"], (1,)))
    if regime == "human_led":
        probes.append(("human_led_takeover",
                       ["guard", sid, "ai_takeover", "--detail",
                        "rehearsal probe"], (1,)))
    for name, args, exp in probes:
        step(f"guard:{name}", args, expect_rc=exp)

    # mark it as a rehearsal so it can never enter analysis
    mp = os.path.join(d, "session_meta.json")
    if os.path.exists(mp):
        meta = json.load(open(mp, encoding="utf-8"))
        meta["rehearsal"] = True
        meta["rehearsal_note"] = ("pipeline rehearsal, not experimental data; "
                                 "exclude from every analysis")
        meta["rehearsal_utc"] = NOW
        json.dump(meta, open(mp, "w", encoding="utf-8"), indent=1,
                  ensure_ascii=False)

    # Step 9-10: extract metrics and evaluate offline
    rc_m, out_m, _ = sh([os.path.join(ROOT, "tools",
                                      "aggregate_metrics.py"),
                         "--session-id", sid])
    steps.append({"step": "aggregate_metrics", "rc": rc_m,
                  "stdout_tail": out_m[-500:]})
    rc_e, out_e, err_e = sh([os.path.join(ROOT, "evaluation", "evaluate.py"),
                             "--session-id", sid])
    steps.append({"step": "evaluate", "rc": rc_e,
                  "stdout_tail": out_e[-600:], "stderr_tail": err_e[-300:]})

    report = {
        "generated_utc": NOW,
        "kind": "session_pipeline_rehearsal",
        "session_id": sid,
        "task_id": row["task_id"],
        "repo_id": row["repo_id"],
        "context_condition": row["context_condition"],
        "delegation": row["delegation"],
        "policy": row.get("policy"),
        "workspace_source": how,
        "steps": steps,
        "outcome": {
            "sop_steps_completed": sum(1 for s in steps if s.get("ok", True)),
            "sop_steps_failed": [s["step"] for s in steps
                                 if s.get("ok") is False],
            "guards_blocked_as_expected":
                all(s.get("ok") for s in steps if s["step"].startswith("guard:")),
            "metrics_extracted": rc_m == 0,
            "freeze_present": os.path.exists(os.path.join(d, "freeze.json")),
            "events_present": os.path.exists(os.path.join(d, "events.jsonl")),
        },
    }
    os.makedirs(os.path.join(ROOT, "audit"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "audit",
                                        "session_rehearsal.json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="pilot")
    ap.add_argument("--condition", default=None,
                    choices=[None, "Clow", "Chigh"])
    a = ap.parse_args()
    rep = rehearsal(a.split, a.condition)
    print(json.dumps(rep["outcome"], indent=1, ensure_ascii=False))
    for s in rep["steps"]:
        mark = "ok " if s.get("ok", True) else "ERR"
        print(f"  [{mark}] {s['step']}")
    return 0 if not rep["outcome"]["sop_steps_failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
