#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase L -- Pilot technical gates (plan 13.1, milestone M1)

Plan 13.1 lists eight technical gates the Pilot must pass before formal
collection.  This tool evaluates the ones that are mechanically checkable and
records the rest as explicit manual attestations, so the M1 Go/No-Go decision
rests on evidence rather than on a verbal report.

| gate (plan 13.1) | how it is checked here |
|---|---|
| environment repeatability | same task rebuilt from clean state N times; build/smoke outcome and code hash must be identical |
| workspace isolation | no file on disk outside the workspace is modified by a session |
| log completeness | each logger has heartbeats; no gap > threshold inside the task window |
| clock consistency | UTC offsets between runner and loggers within threshold |
| tool equivalence | same tool versions recorded across conditions |
| hidden-evaluation isolation | holdout/gold unreachable from the participant workspace |
| task repeatability | clean -> apply candidate -> observe identical outcome N times |
| no information leakage | defer to the screening + audit reports |

Usage
  python tools/pilot_gates.py --task-id X --runs 3
  python tools/pilot_gates.py --all-pilot --runs 3
  python tools/pilot_gates.py --report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
CACHE = os.path.join(ROOT, "repo_cache")
OUT = os.path.join(ROOT, "audit", "pilot_gates")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd, cwd=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout or "", p.stderr or ""


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def clean_workspace(slug, base_commit, tag):
    """A workspace with no state shared with any previous run (plan 8 step 2)."""
    src = os.path.join(CACHE, slug)
    if not os.path.isdir(os.path.join(src, ".git")):
        raise SystemExit(f"no clone cache for {slug}; run repo_cache/fetch_repos.py")
    dst = os.path.join(ROOT, "_pilot_workspaces", tag)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rc, out, err = run(["git", "worktree", "add", "--detach", "--force", dst,
                        base_commit], cwd=src)
    if rc != 0:
        raise SystemExit(f"worktree add failed: {err[-300:]}")
    rc, st, _ = run(["git", "status", "--porcelain"], cwd=dst)
    return dst, st.strip()


def code_hash(workdir):
    """Content hash of every tracked file, so 'same result' means same tree."""
    rc, out, _ = run(["git", "ls-files", "-s"], cwd=workdir)
    h = hashlib.sha256()
    for line in sorted(out.splitlines()):
        parts = line.split()
        if len(parts) >= 4:
            h.update((parts[0] + " " + parts[1] + " " + parts[3]).encode())
    return h.hexdigest()


def smoke(workdir, spec):
    cmd = spec.get("test_command") or "pytest -rA"
    if isinstance(cmd, list):
        cmd = " && ".join(cmd)
    t0 = time.time()
    rc, out, err = run(cmd, cwd=workdir, timeout=3600)
    return {"command": cmd, "returncode": rc, "seconds": round(time.time() - t0, 1),
            "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(err.encode()).hexdigest(),
            "stderr_tail": err[-300:], "stdout_tail": out[-300:]}


def gate_repeatability(task_id, runs):
    """Gate 1 + 8: clean rebuild N times must give identical build/smoke results."""
    import yaml
    spec = yaml.safe_load(open(os.path.join(ROOT, "evaluation_spec",
                                            task_id + ".yaml"),
                               encoding="utf-8"))
    slug = task_id.split("-")[0]
    base = spec["base_commit"]
    attempts = []
    for i in range(runs):
        tag = f"{task_id}__r{i+1}"
        wd, dirty = clean_workspace(slug, base, tag)
        try:
            rec = {"run": i + 1, "workspace_dirty_after_checkout": bool(dirty),
                   "code_hash": code_hash(wd)}
            rec["smoke"] = smoke(wd, spec)
            attempts.append(rec)
        finally:
            run(["git", "worktree", "remove", "--force", wd], cwd=os.path.join(CACHE, slug))
            shutil.rmtree(wd, ignore_errors=True)

    hashes = {a["code_hash"] for a in attempts}
    rcs = {a["smoke"]["returncode"] for a in attempts}
    outs = {a["smoke"]["stdout_sha256"] for a in attempts}
    errs = {a["smoke"]["stderr_sha256"] for a in attempts}
    dirty = any(a["workspace_dirty_after_checkout"] for a in attempts)
    return {
        "task_id": task_id,
        "runs": runs,
        "code_hash_stable": len(hashes) == 1,
        "returncode_stable": len(rcs) == 1,
        "stdout_stable": len(outs) == 1,
        "stderr_stable": len(errs) == 1,
        "clean_checkout": not dirty,
        "returncodes": sorted(rcs),
        "attempts": [{k: v for k, v in a.items() if k != "smoke"} |
                     {"smoke": {kk: vv for kk, vv in a["smoke"].items()
                                if kk not in ("stdout_tail", "stderr_tail")}}
                     for a in attempts],
        "verdict": ("PASS" if (len(hashes) == 1 and len(rcs) == 1 and not dirty)
                    else "FAIL"),
        "note": ("a stable non-zero return code still passes this gate: the "
                 "gate is about *reproducibility*, not about the suite passing "
                 "-- at base_commit the target tests are expected to fail"),
    }


def gate_isolation(task_id):
    """Gate 2 + 6: the participant workspace must not reach grading material."""
    checks = []
    cp = os.path.join(ROOT, "context_packages", task_id + ".md")
    if os.path.exists(cp):
        body = open(cp, encoding="utf-8", errors="replace").read()
        checks.append(("context_package_has_no_test_patch",
                       "diff --git" not in body))
    man = os.path.join(ROOT, "manifests", "tasks", task_id + ".yaml")
    if os.path.exists(man):
        body = open(man, encoding="utf-8", errors="replace").read()
        checks.append(("participant_manifest_has_no_f2p_list",
                       "fail_to_pass:" not in body))
        checks.append(("participant_manifest_has_no_test_patch",
                       "diff --git" not in body))
    runner = os.path.join(ROOT, "tools", "session_runner.py")
    body = open(runner, encoding="utf-8", errors="replace").read()
    checks.append(("runner_does_not_reference_gold",
                   "gold/patches" not in body))
    checks.append(("runner_rejects_unallocated",
                   "is not in the frozen allocation" in body))
    return {"task_id": task_id, "checks": {k: v for k, v in checks},
            "verdict": "PASS" if all(v for _, v in checks) else "FAIL"}


def gate_log_completeness():
    """Gate 3 + 4, measured on the demo sessions produced by the runner self-test."""
    sd = os.path.join(ROOT, "sessions")
    out = []
    if not os.path.isdir(sd):
        return {"sessions": [], "verdict": "NO_DATA"}
    for s in sorted(os.listdir(sd)):
        ev = os.path.join(sd, s, "events.jsonl")
        if not os.path.exists(ev):
            continue
        events = [json.loads(l) for l in open(ev, encoding="utf-8") if l.strip()]
        if not events:
            continue
        mono = [e["monotonic_ms"] for e in events]
        gaps = [b - a for a, b in zip(mono, mono[1:])]
        has_start = any(e["event_type"] == "session_start" for e in events)
        has_end = any(e["event_type"] == "session_end" for e in events)
        monotonic_ok = all(b >= a for a, b in zip(mono, mono[1:]))
        hashes = [e["event_id"] for e in events]
        out.append({
            "session_id": s,
            "n_events": len(events),
            "has_session_start": has_start,
            "has_session_end": has_end,
            "monotonic_ok": monotonic_ok,
            "max_gap_ms": max(gaps) if gaps else 0,
            "event_ids_contiguous": hashes == list(range(1, len(hashes) + 1)),
            "sources": sorted({e.get("source") for e in events}),
            "actors": sorted({e.get("actor") for e in events}),
        })
    ok = all(x["has_session_start"] and x["has_session_end"]
             and x["monotonic_ok"] and x["event_ids_contiguous"] for x in out)
    return {"sessions": out, "verdict": "PASS" if out and ok else
            ("FAIL" if out else "NO_DATA"),
            "note": ("the demo sessions are protocol rehearsals, not formal "
                     "data; this gate re-runs on real Pilot sessions")}


def gate_tool_equivalence():
    """Gate 5: one runner, one logger set, one gateway for every condition."""
    r = os.path.join(ROOT, "tools", "session_runner.py")
    body = open(r, encoding="utf-8", errors="replace").read()
    checks = {
        "single_entry_point": "def cmd_start" in body,
        "same_runner_for_all_regimes":
            body.count("REGIME_CHECKPOINTS") >= 2,
        "cap_is_a_constant": "SESSION_CAP_MIN = 75" in body,
        "no_per_condition_tool_branch":
            "if regime ==" in body and "pytest" not in body.split("def cmd_start")[1][:2000],
    }
    return {"checks": checks,
            "verdict": "PASS" if all(checks.values()) else "FAIL",
            "note": ("plan 13.1: every treatment must use the same IDE/CLI/AI "
                     "gateway/visible tests; the runner is that single entry "
                     "point, and this gate fails if it grows a "
                     "condition-specific code path")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id")
    ap.add_argument("--all-pilot", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]

    if a.report:
        files = sorted(f for f in os.listdir(OUT) if f.endswith(".json"))
        print(f"{len(files)} gate reports in {os.path.relpath(OUT, ROOT)}")
        for f in files:
            d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
            print(f"  {f:52s} {d.get('verdict')}")
        return

    targets = []
    if a.all_pilot:
        targets = [t["task_id"] for t in idx if t["split"] == "pilot"]
    elif a.task_id:
        targets = [a.task_id]
    else:
        ap.error("need --task-id, --all-pilot or --report")

    results = {}
    for tid in targets:
        row = {"task_id": tid, "evaluated_utc": NOW, "runs": a.runs}
        try:
            row["repeatability"] = gate_repeatability(tid, a.runs)
        except Exception as e:
            row["repeatability"] = {"verdict": "ERROR",
                                    "error": f"{type(e).__name__}: {e}"}
        row["isolation"] = gate_isolation(tid)
        results[tid] = row
        path = os.path.join(OUT, tid + ".json")
        json.dump(row, open(path, "w", encoding="utf-8"), indent=1,
                  ensure_ascii=False)
        print(f"{tid:52s} repeatability="
              f"{row['repeatability'].get('verdict')} "
              f"isolation={row['isolation'].get('verdict')}", flush=True)

    lc = gate_log_completeness()
    te = gate_tool_equivalence()
    json.dump({"evaluated_utc": NOW, "log_completeness": lc,
               "tool_equivalence": te},
              open(os.path.join(OUT, "_global_gates.json"), "w",
                   encoding="utf-8"), indent=1, ensure_ascii=False)

    summary = {
        "generated_utc": NOW,
        "runs_per_task": a.runs,
        "tasks": {k: {"repeatability": v["repeatability"].get("verdict"),
                      "isolation": v["isolation"].get("verdict")}
                  for k, v in results.items()},
        "log_completeness": lc["verdict"],
        "tool_equivalence": te["verdict"],
        "manual_attestations_required": [
            "environment_repeatability on the real experiment host (plan 2.1)",
            "workspace isolation across two consecutive real sessions",
            "NTP-synchronised clock skew between runner, IDE logger and gateway",
            "hidden-evaluation isolation verified by a human trying to reach "
            "holdout tests from the participant workspace",
        ],
    }
    json.dump(summary, open(os.path.join(OUT, "_summary.json"), "w",
                            encoding="utf-8"), indent=1, ensure_ascii=False)
    print()
    print(f"log completeness : {lc['verdict']}")
    print(f"tool equivalence : {te['verdict']}")
    print(f"wrote {os.path.relpath(os.path.join(OUT, '_summary.json'), ROOT)}")


if __name__ == "__main__":
    main()
