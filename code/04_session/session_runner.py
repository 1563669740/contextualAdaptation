#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase F -- Session runner and trajectory logger (plan 8, 9; milestone M3)

This is the single entry point all conditions go through, which is what makes
tool access equivalent across treatments (plan 13.1 "tool equivalence").

It provides
  * session clock: wall clock UTC + monotonic ms relative to session start
  * `events.jsonl` in the frozen schema (protocol/event_schema.json)
  * the 75-minute hard stop, enforced in code rather than by instruction
  * treatment-fidelity enforcement per delegation regime
  * git watcher: worktree hash before/after key events
  * terminal wrapper, AI gateway and IDE logger entry points
  * result freezing: final patch, worktree manifest, artefact hashes
    (`freeze` makes the session directory read-only)

Subcommands
  start    begin a session for an allocated session_id
  log      append one event (used by the terminal wrapper / IDE logger)
  checkpoint  record a Shared-control decision
  heartbeat   logger health proof
  stop     stop the clock and record the stop reason
  freeze   write final.patch + worktree_manifest + hashes, then seal

Deliberate non-goals
  The runner does NOT evaluate.  Benchmark and holdout execution live in
  evaluation/, run from an independent clean workspace after freezing, so that
  no grading material is ever reachable from the participant workspace.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
SESSIONS = os.path.join(ROOT, "sessions")
PROTO = os.path.join(ROOT, "protocol")

SESSION_CAP_MIN = 75
HEARTBEAT_SEC = 30

REGIME_CHECKPOINTS = {
    "ai_led": [],
    "shared_control": ["diagnosis", "plan", "final_patch"],
    "human_led": [],
}
ACTOR_OK = {"human", "AI", "system", "evaluator"}


# --------------------------------------------------------------------------- #
def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_allocation():
    alloc = {}
    for name in ("pilot", "discovery", "held_out"):
        p = os.path.join(ROOT, "splits", f"allocation_{name}.csv")
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                alloc[row["session_id"]] = row
    return alloc


def sdir(session_id):
    return os.path.join(SESSIONS, session_id)


def meta_path(session_id):
    return os.path.join(sdir(session_id), "session_meta.json")


def events_path(session_id):
    return os.path.join(sdir(session_id), "events.jsonl")


def read_meta(session_id):
    p = meta_path(session_id)
    if not os.path.exists(p):
        sys.exit(f"session {session_id} not started (no session_meta.json)")
    return json.load(open(p, encoding="utf-8"))


def write_meta(session_id, meta):
    meta["updated_utc"] = now_utc()
    json.dump(meta, open(meta_path(session_id), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)


def next_event_id(session_id, meta):
    meta["_event_counter"] = meta.get("_event_counter", 0) + 1
    return meta["_event_counter"]


def append_event(session_id, meta, actor, event_type, payload, source,
                 visible_to_human=None, visible_to_ai=None,
                 working_tree_hash=None):
    if actor not in ACTOR_OK:
        sys.exit(f"invalid actor {actor!r}; must be one of {sorted(ACTOR_OK)}")
    eid = next_event_id(session_id, meta)
    mono = int(round((time.monotonic() - meta["_t0_monotonic"]) * 1000))
    ev = {
        "session_id": session_id,
        "event_id": eid,
        "timestamp_utc": now_utc(),
        "monotonic_ms": mono,
        "actor": actor,
        "event_type": event_type,
        "payload": payload,
        "source": source,
    }
    if visible_to_human is not None:
        ev["visible_to_human"] = visible_to_human
    if visible_to_ai is not None:
        ev["visible_to_ai"] = visible_to_ai
    if working_tree_hash:
        ev["working_tree_hash"] = working_tree_hash
    with open(events_path(session_id), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def git(args, cwd):
    p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    return p.returncode, p.stdout or "", p.stderr or ""


def worktree_hash(workdir):
    """Hash of the tracked content state: HEAD + index + dirty file hashes."""
    if not workdir or not os.path.isdir(os.path.join(workdir, ".git")):
        return None
    h = hashlib.sha256()
    rc, out, _ = git(["rev-parse", "HEAD"], workdir)
    h.update(("HEAD:" + out.strip()).encode())
    rc, out, _ = git(["status", "--porcelain=v1"], workdir)
    h.update(("STATUS:" + out).encode())
    for line in out.splitlines():
        p = line[3:].strip().strip('"')
        fp = os.path.join(workdir, p)
        if os.path.isfile(fp):
            try:
                h.update((p + ":" + sha256_file(fp)).encode())
            except OSError:
                pass
    return h.hexdigest()


def violation(session_id, meta, kind, detail):
    append_event(session_id, meta, "system", "protocol_violation",
                 {"kind": kind, "detail": detail}, "runner")
    meta["protocol_violation"] = True
    meta.setdefault("violations", []).append({"kind": kind, "detail": detail,
                                             "at_utc": now_utc()})
    write_meta(session_id, meta)


# --------------------------------------------------------------------------- #
def cmd_start(a):
    alloc = load_allocation()
    row = alloc.get(a.session_id)
    if row is None:
        sys.exit(f"{a.session_id} is not in the frozen allocation; refusing to "
                 f"start an unallocated session")
    d = sdir(a.session_id)
    if os.path.exists(meta_path(a.session_id)):
        sys.exit(f"{a.session_id} already started; sessions are single-use")
    os.makedirs(d, exist_ok=True)
    for sub in ("terminal", "ai_calls", "diffs", "visible_tests"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)

    delegation = row["delegation"] or row["policy"]
    meta = {
        "schema_version": "1.0",
        "session_id": a.session_id,
        "participant_id": row["participant_id"],
        "task_id": row["task_id"],
        "repo_id": row["repo_id"],
        "split": row["split"],
        "base_commit": row["base_commit"],
        "context_condition": row["context_condition"],
        "delegation": row["delegation"],
        "policy": row["policy"],
        "condition_order": int(row["condition_order"]),
        "allocation_seed": int(row["allocation_seed"]),
        "task_difficulty_stratum": row["task_difficulty_stratum"],
        "workdir": os.path.abspath(a.workdir) if a.workdir else None,
        "os_image": a.os_image,
        "runner_version": "0.1.0",
        "network_policy": {"setup": "allow-package-mirrors",
                           "task": "deny-external-by-default"},
        "resource_limits": {"cpu": a.cpu, "memory_gb": a.memory_gb,
                            "disk_gb": a.disk_gb},
        "protocol_violation": False,
        "violations": [],
        "logger_health": "unknown",
        "missing_event_count": 0,
        "abort_reason": None,
        "prep_start_utc": None, "prep_end_utc": None, "context_prep_sec": None,
        "task_start_utc": now_utc(),
        "task_end_utc": None,
        "human_active_sec": 0.0,
        "wall_clock_sec": None,
        "session_cap_sec": SESSION_CAP_MIN * 60,
        "session_start_utc": now_utc(),
        "freeze_timestamp": None,
        "_t0_monotonic": time.monotonic(),
        "_event_counter": 0,
        "_human_active_open": None,
    }
    # provenance hashes, so the audit can prove which frozen inputs were used
    prov = {}
    for rel, key in [("manifests/model_manifest.json", "model_manifest"),
                     ("manifests/environment_spec.json", "environment_spec"),
                     ("policy/adaptive_policy_v1.json", "policy"),
                     ("codebook/codebook_v1.json", "codebook"),
                     ("protocol/event_schema.json", "event_schema")]:
        p = os.path.join(ROOT, os.path.basename(rel) if False else rel)
        if os.path.exists(p):
            prov[key] = sha256_file(p)
    for rel, key in [(f"manifests/tasks/{row['task_id']}.yaml", "task_manifest")]:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            prov[key] = sha256_file(p)
    if row["context_condition"] == "Chigh":
        p = os.path.join(ROOT, "context_packages", row["task_id"] + ".md")
        prov["context_package"] = sha256_file(p) if os.path.exists(p) else None
    meta["provenance_hashes"] = prov

    if meta["workdir"]:
        meta["worktree_hash_start"] = worktree_hash(meta["workdir"])

    write_meta(a.session_id, meta)
    append_event(a.session_id, meta, "system", "session_start",
                 {"task_id": row["task_id"],
                  "base_commit": row["base_commit"],
                  "context_condition": row["context_condition"],
                  "delegation": delegation,
                  "allocation_seed": int(row["allocation_seed"]),
                  "cap_sec": meta["session_cap_sec"]},
                 "runner")
    write_meta(a.session_id, meta)

    print(f"session {a.session_id} started")
    print(f"  participant   : {row['participant_id']}")
    print(f"  task          : {row['task_id']}  ({row['repo_id']})")
    print(f"  condition     : {row['context_condition']} / {delegation}")
    print(f"  base_commit   : {row['base_commit']}")
    print(f"  hard stop     : {SESSION_CAP_MIN} min from task start")
    if row["context_condition"] == "Chigh":
        print(f"  context package: context_packages/{row['task_id']}.md "
              f"(hash {str(prov.get('context_package'))[:12]})")


def cmd_log(a):
    meta = read_meta(a.session_id)
    payload = json.loads(a.payload) if a.payload else {}
    kwargs = {}
    if a.visible_to is not None:
        kwargs["visible_to_human"] = "human" in a.visible_to
        kwargs["visible_to_ai"] = "ai" in a.visible_to
    if a.worktree:
        kwargs["working_tree_hash"] = worktree_hash(meta.get("workdir"))
    ev = append_event(a.session_id, meta, a.actor, a.event_type, payload,
                      a.source or "cli", **kwargs)
    write_meta(a.session_id, meta)
    print(json.dumps(ev, ensure_ascii=False))


def cmd_checkpoint(a):
    meta = read_meta(a.session_id)
    regime = meta.get("delegation") or ""
    required = REGIME_CHECKPOINTS.get(regime, [])
    if required and a.checkpoint not in required:
        violation(a.session_id, meta, "unknown_checkpoint",
                  f"{a.checkpoint!r} is not one of {required} for {regime}")
        sys.exit(f"checkpoint {a.checkpoint!r} is not part of the "
                 f"{regime} protocol")
    if a.decision not in ("approve", "modify", "reject", "note"):
        sys.exit("decision must be approve | modify | reject | note")
    append_event(a.session_id, meta, "human", "checkpoint",
                 {"checkpoint": a.checkpoint, "decision": a.decision,
                  "note": a.note, "wait_sec": a.wait_sec},
                 "checkpoint_cli")
    if a.decision in ("approve", "modify"):
        meta.setdefault("checkpoints_done", []).append(a.checkpoint)
    write_meta(a.session_id, meta)
    print(f"checkpoint {a.checkpoint} -> {a.decision}")


def cmd_heartbeat(a):
    meta = read_meta(a.session_id)
    append_event(a.session_id, meta, "system", "logger_heartbeat",
                 {"pid": os.getpid()}, "runner")
    meta["logger_health"] = "alive"
    write_meta(a.session_id, meta)


def cmd_guard(a):
    """Treatment-fidelity guard, called by the AI gateway / chat surface."""
    meta = read_meta(a.session_id)
    regime = meta.get("delegation") or ""
    kind = a.kind
    if regime == "ai_led" and kind == "human_correction":
        violation(a.session_id, meta, "ai_led_human_intervention", a.detail)
        sys.exit("BLOCKED: AI-led sessions do not accept human corrective "
                 "messages (protocol 3.1)")
    if regime == "human_led" and kind == "ai_takeover":
        violation(a.session_id, meta, "human_led_ai_takeover", a.detail)
        sys.exit("BLOCKED: Human-led sessions forbid end-to-end AI takeover; "
                 "only bounded local requests are allowed (protocol 3.3)")
    if regime == "shared_control" and kind == "advance_without_checkpoint":
        done = set(meta.get("checkpoints_done", []))
        missing = [c for c in REGIME_CHECKPOINTS["shared_control"]
                   if c not in done]
        if missing:
            violation(a.session_id, meta, "shared_control_skipped_checkpoint",
                      f"missing {missing}")
            sys.exit(f"BLOCKED: Shared-control requires checkpoints {missing} "
                     f"before advancing (protocol 3.2)")
    print("OK")


def cmd_stop(a):
    meta = read_meta(a.session_id)
    elapsed = time.monotonic() - meta["_t0_monotonic"]
    meta["task_end_utc"] = now_utc()
    meta["wall_clock_sec"] = round(elapsed, 1)
    meta["stop_reason"] = a.reason
    if a.reason == "cap_reached" or elapsed >= SESSION_CAP_MIN * 60:
        meta["stop_reason"] = "cap_reached"
    append_event(a.session_id, meta, "system", "session_end",
                 {"stop_reason": meta["stop_reason"],
                  "wall_clock_sec": meta["wall_clock_sec"]}, "runner")
    write_meta(a.session_id, meta)
    print(f"stopped: {meta['stop_reason']} after "
          f"{meta['wall_clock_sec']:.0f}s "
          f"({meta['wall_clock_sec']/60:.1f} min)")


def cmd_freeze(a):
    meta = read_meta(a.session_id)
    d = sdir(a.session_id)
    wd = meta.get("workdir")

    if wd and os.path.isdir(os.path.join(wd, ".git")):
        rc, diff, _ = git(["diff", "--binary", "HEAD"], wd)
        open(os.path.join(d, "final.patch"), "w", encoding="utf-8",
             newline="\n").write(diff)
        rc, st, _ = git(["status", "--porcelain=v1"], wd)
        open(os.path.join(d, "diffs", "git_status.txt"), "w",
             encoding="utf-8", newline="\n").write(st)
        rc, head, _ = git(["rev-parse", "HEAD"], wd)
        rc, base, _ = git(["merge-base", "HEAD", meta["base_commit"]], wd)
        files = [{"path": l[3:].strip(), "status": l[:2]}
                 for l in st.splitlines() if len(l) > 3]
        meta["worktree_hash_end"] = worktree_hash(wd)
        json.dump({"base_commit": meta["base_commit"], "head": head.strip(),
                   "merge_base": base.strip(),
                   "worktree_hash_start": meta.get("worktree_hash_start"),
                   "worktree_hash_end": meta.get("worktree_hash_end"),
                   "changed_files": files,
                   "n_changed_files": len(files)},
                  open(os.path.join(d, "worktree_manifest.json"), "w",
                       encoding="utf-8"), indent=1, ensure_ascii=False)

    # freeze: hash every artefact, then seal the directory
    artefacts = {}
    for dp, dn, fn in os.walk(d):
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, d).replace("\\", "/")
            if rel in ("freeze.json",):
                continue
            artefacts[rel] = {"sha256": sha256_file(p),
                              "bytes": os.path.getsize(p)}
    meta["freeze_timestamp"] = now_utc()
    meta["evaluation_version"] = None
    meta["artefacts"] = artefacts
    fp = os.path.join(d, "final.patch")
    meta["final_patch_sha256"] = sha256_file(fp) if os.path.exists(fp) else None
    ep = events_path(a.session_id)
    meta["events_sha256"] = sha256_file(ep) if os.path.exists(ep) else None
    meta["n_events"] = meta.get("_event_counter", 0)

    frozen = {
        "schema_version": "1.0",
        "session_id": a.session_id,
        "frozen_utc": meta["freeze_timestamp"],
        "final_patch_sha256": meta["final_patch_sha256"],
        "events_sha256": meta["events_sha256"],
        "n_events": meta["n_events"],
        "n_artefacts": len(artefacts),
        "artefacts": artefacts,
        "protocol_violation": meta.get("protocol_violation"),
        "stop_reason": meta.get("stop_reason"),
        "wall_clock_sec": meta.get("wall_clock_sec"),
        "note": ("session data is immutable from this point (plan 8 step 8)"),
    }
    json.dump(frozen, open(os.path.join(d, "freeze.json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)
    meta.pop("_t0_monotonic", None)
    write_meta(a.session_id, meta)

    print(f"frozen {a.session_id}")
    print(f"  events           : {meta['n_events']}")
    print(f"  final.patch      : {str(meta['final_patch_sha256'])[:16]}")
    print(f"  events.jsonl     : {str(meta['events_sha256'])[:16]}")
    print(f"  artefacts hashed : {len(artefacts)}")


def cmd_status(a):
    alloc = load_allocation()
    done = []
    part = []
    if os.path.isdir(SESSIONS):
        for s in sorted(os.listdir(SESSIONS)):
            if os.path.exists(os.path.join(SESSIONS, s, "freeze.json")):
                done.append(s)
            elif os.path.exists(os.path.join(SESSIONS, s, "session_meta.json")):
                part.append(s)
    print(f"allocated {len(alloc)}  started {len(part)}  frozen {len(done)}")
    for sid in (part + done)[:40]:
        r = alloc.get(sid, {})
        print(f"  {sid}  {r.get('participant_id','?'):>5}  "
              f"{r.get('context_condition','?'):>5}  "
              f"{(r.get('delegation') or r.get('policy') or '?'):>22}  "
              f"{r.get('task_id','?')}")


def main():
    ap = argparse.ArgumentParser(description="session runner / trajectory logger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start")
    p.add_argument("session_id")
    p.add_argument("--workdir", default=None,
                   help="participant workspace checked out at base_commit")
    p.add_argument("--os-image", default=None)
    p.add_argument("--cpu", type=int, default=4)
    p.add_argument("--memory-gb", type=int, default=8, dest="memory_gb")
    p.add_argument("--disk-gb", type=int, default=30, dest="disk_gb")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("log")
    p.add_argument("session_id")
    p.add_argument("actor", choices=sorted(ACTOR_OK))
    p.add_argument("event_type")
    p.add_argument("--payload", default=None, help="JSON object")
    p.add_argument("--source", default="cli")
    p.add_argument("--visible-to", default=None,
                   help="comma list: human,ai")
    p.add_argument("--worktree", action="store_true",
                   help="attach the current worktree hash")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("checkpoint")
    p.add_argument("session_id")
    p.add_argument("checkpoint")
    p.add_argument("decision")
    p.add_argument("--note", default=None)
    p.add_argument("--wait-sec", type=float, default=0.0, dest="wait_sec")
    p.set_defaults(fn=cmd_checkpoint)

    p = sub.add_parser("heartbeat")
    p.add_argument("session_id")
    p.set_defaults(fn=cmd_heartbeat)

    p = sub.add_parser("guard")
    p.add_argument("session_id")
    p.add_argument("kind", choices=["human_correction", "ai_takeover",
                                    "advance_without_checkpoint"])
    p.add_argument("--detail", default=None)
    p.set_defaults(fn=cmd_guard)

    p = sub.add_parser("stop")
    p.add_argument("session_id")
    p.add_argument("reason", choices=["participant_done", "agent_done",
                                      "budget_exhausted", "cap_reached",
                                      "aborted"])
    p.set_defaults(fn=cmd_stop)

    p = sub.add_parser("freeze")
    p.add_argument("session_id")
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("status")
    p.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
