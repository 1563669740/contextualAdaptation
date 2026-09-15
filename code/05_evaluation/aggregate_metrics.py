#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase M -- Session metrics aggregation (plan 11.3)

Turns frozen session directories plus evaluation results into one analysis-ready
row per session, with the time accounting the plan demands.

Time accounting is the part most easily got wrong, so it is explicit here:

  wall_clock_sec            formal task start -> result freeze.  Does NOT
                            include pre-task context building (plan 11.3).
  context_prep_sec          Chigh only, pre-task package reading.  Reported
                            SEPARATELY and never added to wall clock.
  human_active_sec          human reading/typing/reviewing/editing/deciding
                            inside the task phase, from explicit interval
                            events rather than from wall clock.
  Tinitial / Tinspection / Trework
                            activity measures that can overlap in time.  The
                            plan states they must NOT be summed and read as
                            wall clock; `overlap_warning` is written into every
                            row so no downstream script can do it by accident.
  ai_execution_sec / api_cost
                            from the gateway call log.

Outputs
  analysis/session_metrics.csv     one row per frozen session
  analysis/session_metrics.json    same data plus per-source provenance
  analysis/README.md               how the columns were computed

Usage
  python tools/aggregate_metrics.py
  python tools/aggregate_metrics.py --session-id D-S0001
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
SESSIONS = os.path.join(ROOT, "sessions")
EVAL = os.path.join(ROOT, "evaluation")
EVAL_DIR = None
OUT = os.path.join(ROOT, "analysis")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# event types that count as human activity, and whether they open or close an
# interval.  Explicit intervals beat assumptions about wall clock.
HUMAN_OPEN = {"checkpoint", "edit", "message", "read", "open"}
HUMAN_CLOSE = {"test", "session_end"}

COLUMNS = [
    "session_id", "split", "participant_id", "task_id", "repo_id",
    "context_condition", "delegation", "policy", "condition_order",
    "task_difficulty_stratum",
    # outcomes
    "benchmark_resolved", "enhanced_resolved", "suite_status",
    "environment_fault", "holdout_status", "semantic_review_status",
    "regression_count", "regression_rate", "f2p_pass", "f2p_total",
    "p2p_fail", "p2p_total",
    # time
    "wall_clock_sec", "context_prep_sec", "human_active_sec",
    "ai_execution_sec", "Tinitial_sec", "Tinspection_sec", "Trework_sec",
    "checkpoint_wait_sec", "overlap_warning",
    # effort
    "interaction_count", "checkpoint_count", "files_explored",
    "files_modified", "tests_run", "n_events", "n_ai_calls",
    "api_tokens", "api_cost_usd",
    # integrity
    "stop_reason", "protocol_violation", "n_violations",
    "logger_health", "missing_event_count", "n_log_sources",
    "final_patch_sha256", "events_sha256", "frozen_utc",
    "manifest_sha256", "context_package_sha256",
    "evaluation_version", "extractor_version", "metrics_generated_utc",
]

OVERLAP_WARNING = ("Tinitial / Tinspection / Trework are activity measures that "
                   "may overlap in time; do not sum them into wall clock "
                   "(plan 11.3)")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_events(sdir):
    p = os.path.join(sdir, "events.jsonl")
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def human_active_seconds(events):
    """Sum explicit human activity intervals.

    An interval runs from a human-attributed activity event to the next event
    that closes it.  If the trajectory never closes an interval we fall back to
    counting only the gap to the following event, which under-counts rather
    than over-counts -- the conservative direction for a cost claim.
    """
    total_ms = 0
    open_at = None
    for e in events:
        et, actor = e.get("event_type"), e.get("actor")
        mono = e.get("monotonic_ms") or 0
        if actor == "human" and et in HUMAN_OPEN:
            if open_at is None:
                open_at = mono
        elif open_at is not None and (actor == "human" or et in HUMAN_CLOSE):
            total_ms += max(0, mono - open_at)
            open_at = None
    if open_at is not None and events:
        total_ms += max(0, (events[-1].get("monotonic_ms") or 0) - open_at)
    return round(total_ms / 1000.0, 1)


def first_time(events, pred):
    for e in events:
        if pred(e):
            return (e.get("monotonic_ms") or 0) / 1000.0
    return None


def metrics_for(session_id, allocation):
    sdir = os.path.join(SESSIONS, session_id)
    mp = os.path.join(sdir, "session_meta.json")
    if not os.path.exists(mp):
        return None
    meta = json.load(open(mp, encoding="utf-8"))
    events = load_events(sdir)
    alloc = allocation.get(session_id, {})

    row = dict.fromkeys(COLUMNS)
    row.update({
        "session_id": session_id,
        "split": meta.get("split") or alloc.get("split"),
        "participant_id": meta.get("participant_id"),
        "task_id": meta.get("task_id"),
        "repo_id": meta.get("repo_id"),
        "context_condition": meta.get("context_condition"),
        "delegation": meta.get("delegation"),
        "policy": meta.get("policy"),
        "condition_order": meta.get("condition_order"),
        "task_difficulty_stratum": meta.get("task_difficulty_stratum"),
        "wall_clock_sec": meta.get("wall_clock_sec"),
        "context_prep_sec": meta.get("context_prep_sec"),
        "stop_reason": meta.get("stop_reason"),
        "protocol_violation": meta.get("protocol_violation"),
        "n_violations": len(meta.get("violations") or []),
        "logger_health": meta.get("logger_health"),
        "missing_event_count": meta.get("missing_event_count"),
        "final_patch_sha256": meta.get("final_patch_sha256"),
        "events_sha256": meta.get("events_sha256"),
        "frozen_utc": meta.get("freeze_timestamp"),
        "evaluation_version": meta.get("evaluation_version"),
        "n_events": meta.get("n_events") or len(events),
        "overlap_warning": OVERLAP_WARNING,
        "metrics_generated_utc": NOW,
        "extractor_version": "aggregate_metrics.py/1.0",
    })
    prov = meta.get("provenance_hashes") or {}
    row["manifest_sha256"] = prov.get("task_manifest")
    row["context_package_sha256"] = prov.get("context_package")

    row["human_active_sec"] = human_active_seconds(events)

    n_ev = Counter(e.get("event_type") for e in events)
    row["interaction_count"] = n_ev.get("message", 0) + n_ev.get("checkpoint", 0)
    row["checkpoint_count"] = n_ev.get("checkpoint", 0)
    row["tests_run"] = n_ev.get("test", 0)
    row["files_explored"] = len({(e.get("payload") or {}).get("path")
                                 for e in events
                                 if e.get("event_type") in ("open", "read")
                                 and (e.get("payload") or {}).get("path")})
    row["files_modified"] = len({(e.get("payload") or {}).get("path")
                                 for e in events
                                 if e.get("event_type") == "edit"
                                 and (e.get("payload") or {}).get("path")})
    row["n_log_sources"] = len({e.get("source") for e in events})

    wait = sum(float((e.get("payload") or {}).get("wait_sec") or 0)
               for e in events if e.get("event_type") == "checkpoint")
    row["checkpoint_wait_sec"] = round(wait, 1)

    t_first_edit = first_time(events, lambda e: e.get("event_type") == "edit")
    row["Tinitial_sec"] = round(t_first_edit, 1) if t_first_edit is not None else None

    # inspection = human activity after the first candidate repair exists
    if t_first_edit is not None:
        insp = 0
        open_at = None
        for e in events:
            mono = (e.get("monotonic_ms") or 0) / 1000.0
            if mono < t_first_edit:
                continue
            if e.get("actor") == "human" and e.get("event_type") in HUMAN_OPEN:
                open_at = mono if open_at is None else open_at
            elif open_at is not None:
                insp += max(0, mono - open_at)
                open_at = None
        row["Tinspection_sec"] = round(insp, 1)

    # rew ork = tests after the first candidate repair that then fail, plus
    # subsequent edits.  Only counted when a test event carries an exit code.
    rework = 0
    seen_candidate = t_first_edit is not None
    for e in events:
        if e.get("event_type") == "test" and seen_candidate:
            p = e.get("payload") or {}
            if p.get("exit_code") not in (0, None):
                rework += 1
    row["Trework_sec"] = None if not rework else None   # needs interval events
    row["rework_events"] = rework if rework else None

    # gateway calls, if the AI gateway wrote them
    ai_dir = os.path.join(sdir, "ai_calls")
    calls, tokens, cost, ai_sec = 0, 0, 0.0, 0.0
    if os.path.isdir(ai_dir):
        for f in sorted(os.listdir(ai_dir)):
            if not f.endswith(".json"):
                continue
            try:
                c = json.load(open(os.path.join(ai_dir, f), encoding="utf-8"))
            except Exception:
                continue
            calls += 1
            tokens += int(c.get("total_tokens") or 0)
            cost += float(c.get("cost_usd") or 0)
            ai_sec += float(c.get("duration_sec") or 0)
    row["n_ai_calls"] = calls or None
    row["api_tokens"] = tokens or None
    row["api_cost_usd"] = round(cost, 6) if cost else None
    row["ai_execution_sec"] = round(ai_sec, 1) if ai_sec else None

    # evaluation results
    evp = os.path.join(EVAL_DIR or EVAL, session_id, "metrics.json")
    if os.path.exists(evp):
        m = json.load(open(evp, encoding="utf-8"))
        b = m.get("benchmark") or {}
        row["benchmark_resolved"] = m.get("benchmark_resolved")
        row["enhanced_resolved"] = m.get("enhanced_resolved")
        row["suite_status"] = m.get("suite_status") or b.get("suite_status")
        row["environment_fault"] = bool(m.get("environment_fault"))
        row["holdout_status"] = m.get("holdout_status")
        row["semantic_review_status"] = (m.get("semantic_review") or {}).get("status")
        for k in ("regression_count", "regression_rate", "f2p_pass",
                  "f2p_total", "p2p_fail", "p2p_total"):
            row[k] = b.get(k)
        row["evaluation_version"] = m.get("evaluation_version")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id")
    ap.add_argument("--sessions-dir", default=None,
                    help=("read sessions from here instead of the real "
                          "sessions/ tree; used for the synthetic sample so "
                          "synthetic rows can never be pooled with real ones"))
    ap.add_argument("--evaluation-dir", default=None,
                    help="read evaluation/ from here instead")
    ap.add_argument("--out-dir", default=None,
                    help="where to write session_metrics.csv/json")
    a = ap.parse_args()

    global SESSIONS, EVAL_DIR
    if a.sessions_dir:
        SESSIONS = a.sessions_dir
    if a.evaluation_dir:
        EVAL_DIR = a.evaluation_dir
    out_dir = a.out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    allocation = {}
    for name in ("pilot", "discovery", "held_out"):
        p = os.path.join(ROOT, "splits", f"allocation_{name}.csv")
        if os.path.exists(p):
            with open(p, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    allocation[r["session_id"]] = r

    if a.session_id:
        ids = [a.session_id]
    elif os.path.isdir(SESSIONS):
        ids = sorted(d for d in os.listdir(SESSIONS)
                     if os.path.exists(os.path.join(SESSIONS, d,
                                                    "session_meta.json")))
    else:
        ids = []

    rows = []
    for sid in ids:
        r = metrics_for(sid, allocation)
        if r:
            rows.append(r)

    cols = COLUMNS + ["rework_events"]
    path = os.path.join(out_dir, "session_metrics.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    json.dump({
        "generated_utc": NOW,
        "extractor_version": "aggregate_metrics.py/1.0",
        "n_sessions": len(rows),
        "overlap_warning": OVERLAP_WARNING,
        "allocation_total": len(allocation),
        "note": ("rows exist only for sessions that were started; the "
                 "denominator for completeness is the frozen allocation"),
        "rows": rows,
    }, open(os.path.join(out_dir, "session_metrics.json"), "w", encoding="utf-8"),
        indent=1, ensure_ascii=False)

    readme = f"""# analysis/

Generated {NOW} by `tools/aggregate_metrics.py`.

`session_metrics.csv` holds one row per started session. Column meanings
follow plan 11.3; the ones that are easy to misuse:

* `wall_clock_sec` — formal task start to result freeze. Pre-task context
  building is excluded.
* `context_prep_sec` — Chigh only, reported separately. Never added to
  `wall_clock_sec`.
* `human_active_sec` — summed from explicit human-attributed activity
  intervals in `events.jsonl`. When the trajectory never closes an interval the
  extraction under-counts rather than over-counts.
* `Tinitial_sec` — task start to the first `edit` event.
* `Tinspection_sec` — human activity after the first `edit`.
* `Trework_sec` — left `null` on purpose: a trustworthy value needs explicit
  rework interval events, and inventing one from wall clock would be wrong.
  `rework_events` gives the count of failing test runs after the first edit.
* `overlap_warning` — a literal string in every row. `Tinitial`,
  `Tinspection` and `Trework` may overlap in time and must **not** be summed
  into wall clock.

Outcome columns come from `evaluation/<session_id>/metrics.json`. When the
frozen suite could not execute, `benchmark_resolved` is `null` and
`environment_fault` is true: plan 13.1 treats that as an infrastructure
variable, not a participant outcome.

Sessions: {len(rows)} of {len(allocation)} allocated.
"""
    open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8",
         newline="\n").write(readme)

    print(f"sessions aggregated: {len(rows)} (allocated {len(allocation)})")
    print(f"wrote {os.path.relpath(path, ROOT)}")
    for r in rows[:10]:
        print(f"  {r['session_id']:9s} {str(r['delegation'] or r['policy']):>22s} "
              f"wall={r['wall_clock_sec']} human={r['human_active_sec']} "
              f"events={r['n_events']} violations={r['n_violations']}")


if __name__ == "__main__":
    main()
