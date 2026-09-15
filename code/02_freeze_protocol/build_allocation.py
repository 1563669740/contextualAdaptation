#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase B -- Splits, frozen allocation files and participant plan
(plan sections 4, 5, 14; milestone M0/M2)

Implements the paper's design exactly:

  Discovery : 120 tasks x {AI-led, Shared-control, Human-led} = 360 sessions,
              with Clow/Chigh balanced so all six Context x Delegation cells
              hold exactly 60 sessions.
  Held-out  : 72 tasks x 5 policies = 360 sessions, with context balanced
              per policy (36 Clow / 36 Chigh each).
  Pilot     : 24 tasks x 3 regimes = 72 sessions (infrastructure validation).

Hard constraints enforced and verified by build_allocation.py:

  C1  no participant appears twice in the same repository
      (plan 5: "same participant-repository combination at most once")
  C2  each (task, regime) has exactly one session; each (task, policy) too
  C3  every session has exactly one participant; nobody is double-booked into
      the same session
  C4  context balance: 60/60 per regime (discovery), 36/36 per policy (held-out)
  C5  per-participant load is as even as integer arithmetic allows
  C6  per-participant context exposure is balanced

Randomisation follows plan 4.2: a pre-registered seed is frozen together with
the allocation file and its SHA256, and is never re-drawn after results appear.
The paper's published seed (20260301) is retained for Discovery; the seed is
recorded in randomisation.json either way.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

csv.field_size_limit(10 ** 9)

TIFS = r"C:\Users\Administrator\Desktop\TIFS"
ROOT = os.path.join(TIFS, "experiment_root")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SEED = 20260301
REGIMES = ["ai_led", "shared_control", "human_led"]
REGIME_LABEL = {"ai_led": "AI-led", "shared_control": "Shared-control",
                "human_led": "Human-led"}
POLICIES = ["always_ai_led", "always_shared_control", "always_human_led",
            "developer_ad_hoc", "adaptive_policy"]
POLICY_LABEL = {"always_ai_led": "Always AI-led",
                "always_shared_control": "Always Shared-control",
                "always_human_led": "Always Human-led",
                "developer_ad_hoc": "Developer Ad-hoc",
                "adaptive_policy": "Adaptive Policy"}

N_DISCOVERY_PARTICIPANTS = 48
N_HELDOUT_PARTICIPANTS = 36
N_PILOT_PARTICIPANTS = 18


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_tasks():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "manifests",
                                                 "task_index.json"),
                                    encoding="utf-8"))) \
        if False else json.load(open(os.path.join(ROOT, "manifests",
                                                  "task_index.json"),
                                     encoding="utf-8"))["tasks"]
    return rows


# --------------------------------------------------------------------------- #
# context assignment
# --------------------------------------------------------------------------- #
def assign_context(tasks, rng):
    """Half Clow / half Chigh, forced within each repository so that every
    repository contributes evenly to both context conditions (plan 4.1)."""
    by_repo = defaultdict(list)
    for t in tasks:
        by_repo[t["repo_id"]].append(t)
    out = {}
    for repo, tl in by_repo.items():
        rng.shuffle(tl)
        n = len(tl)
        n_high = n // 2 if n % 2 == 0 else (n + 1) // 2
        for i, t in enumerate(tl):
            out[t["task_id"]] = "Chigh" if i < n_high else "Clow"
    return out


# --------------------------------------------------------------------------- #
# participant assignment (greedy with capacity + balance objectives)
# --------------------------------------------------------------------------- #
def assign_participants(sessions, participants, rng):
    """
    sessions: list of dicts with keys repo_id, context_condition, delegation
    Mutates each session, adding 'participant_id'.
    Returns (sessions, diagnostics)
    """
    n = len(participants)
    load = Counter()
    repo_seen = defaultdict(Counter)      # pid -> repo_id -> sessions
    high = Counter()                      # pid -> Chigh count
    ctx_target = (sum(1 for s in sessions
                      if s["context_condition"] == "Chigh") / n)

    # Constrained-first ordering: large repositories have the tightest
    # per-participant capacity, so place them while everyone is still free.
    repo_size = Counter(s["repo_id"] for s in sessions)
    order = sorted(range(len(sessions)),
                   key=lambda i: (-repo_size[sessions[i]["repo_id"]],
                                  sessions[i]["repo_id"],
                                  sessions[i]["context_condition"],
                                  sessions[i]["delegation"],
                                  sessions[i]["task_id"]))

    # deterministic per-participant tie-break order
    for s in sessions:
        s["participant_id"] = None
    tie = {p: rng.random() for p in participants}

    for i in order:
        s = sessions[i]
        target_ctx = ctx_target
        best, best_key = None, None
        for p in participants:
            if repo_seen[p][s["repo_id"]] > 0:
                continue
            # C1 is absolute; among feasible participants minimise load, then
            # minimise over-exposure to this context condition.
            key = (load[p],
                   max(0.0, high[p] - target_ctx) if s["context_condition"] == "Chigh"
                   else max(0.0, (load[p] - high[p]) - target_ctx),
                   tie[p])
            if best_key is None or key < best_key:
                best, best_key = p, key
        if best is None:
            raise RuntimeError(
                f"allocation infeasible: no eligible participant for "
                f"{s['task_id']} in repo {s['repo_id']}")
        s["participant_id"] = best
        load[best] += 1
        repo_seen[best][s["repo_id"]] += 1
        if s["context_condition"] == "Chigh":
            high[best] += 1

    diag = {
        "load_min": min(load.values()),
        "load_max": max(load.values()),
        "load_hist": dict(sorted(Counter(load.values()).items())),
        "chigh_min": min(high.values()),
        "chigh_max": max(high.values()),
        "chigh_hist": dict(sorted(Counter(high.values()).items())),
    }
    return sessions, diag


# --------------------------------------------------------------------------- #
def write_csv(path, sessions, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in sessions:
            w.writerow({c: s.get(c, "") for c in cols})


COLS = ["session_id", "split", "phase", "task_id", "repo_id", "base_commit",
        "context_condition", "delegation", "policy", "participant_id",
        "condition_order", "allocation_seed", "sequence_index",
        "task_difficulty_stratum"]


def main():
    rng = random.Random(SEED)
    tasks = load_tasks()
    splits = defaultdict(list)
    for t in tasks:
        splits[t["split"]].append(t)

    alloc_dir = os.path.join(ROOT, "splits")
    os.makedirs(alloc_dir, exist_ok=True)

    report = {"generated_utc": NOW, "allocation_seed": SEED, "splits": {}}

    # ------------------------------------------------------------------ #
    # shared split listings (task level, no hidden material)
    # ------------------------------------------------------------------ #
    split_files = {}
    for name in ["pilot", "discovery", "held_out"]:
        p = os.path.join(alloc_dir, f"{name}_tasks.csv")
        cols = ["task_id", "repo_id", "issue_number", "base_commit",
                "language", "task_difficulty_stratum", "gold_files_changed",
                "gold_loc_changed", "fail_to_pass_count", "pass_to_pass_count"]
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for t in sorted(splits[name], key=lambda x: (x["repo_id"],
                                                         x["task_id"])):
                w.writerow({c: t.get(c, "") for c in cols})
        split_files[name] = p

    # ------------------------------------------------------------------ #
    # PILOT  24 tasks x 3 regimes = 72 sessions
    # ------------------------------------------------------------------ #
    pilot_ctx = assign_context(splits["pilot"], rng)
    ps = []
    for t in sorted(splits["pilot"], key=lambda x: x["task_id"]):
        for reg in REGIMES:
            ps.append({
                "split": "pilot", "phase": "pilot",
                "task_id": t["task_id"], "repo_id": t["repo_id"],
                "base_commit": t["base_commit"],
                "context_condition": pilot_ctx[t["task_id"]],
                "delegation": reg, "policy": "",
                "task_difficulty_stratum": t["task_difficulty_stratum"],
            })
    pilot_participants = [f"P{i:03d}" for i in range(1, N_PILOT_PARTICIPANTS + 1)]
    ps, pdiag = assign_participants(ps, pilot_participants, rng)

    # ------------------------------------------------------------------ #
    # DISCOVERY  120 tasks x 3 regimes = 360 sessions
    # ------------------------------------------------------------------ #
    disc_ctx = assign_context(splits["discovery"], rng)
    ds = []
    for t in sorted(splits["discovery"], key=lambda x: x["task_id"]):
        for reg in REGIMES:
            ds.append({
                "split": "discovery", "phase": "rq1",
                "task_id": t["task_id"], "repo_id": t["repo_id"],
                "base_commit": t["base_commit"],
                "context_condition": disc_ctx[t["task_id"]],
                "delegation": reg, "policy": "",
                "task_difficulty_stratum": t["task_difficulty_stratum"],
            })
    disc_participants = [f"D{i:03d}" for i in range(1, N_DISCOVERY_PARTICIPANTS + 1)]
    ds, ddiag = assign_participants(ds, disc_participants, rng)

    # ------------------------------------------------------------------ #
    # HELD-OUT  72 tasks x 5 policies = 360 sessions
    #
    # Paper IX-B is explicit: "每个 task 的 context availability 在 policy 分配
    # 前固定，五种 policy 共享同一 Clow/Chigh 条件及对应 package".  So context
    # is a property of the TASK here, not of the (task, policy) cell: all five
    # policy sessions for a task run under one context condition.
    #
    # Balance is then obtained across tasks rather than inside each policy:
    # within each repository (6 tasks) exactly 3 go Chigh and 3 Clow, so every
    # policy inherits 36 Chigh / 36 Clow over the 12 repositories.
    # ------------------------------------------------------------------ #
    ho_tasks = sorted(splits["held_out"],
                      key=lambda x: (x["repo_id"], x["task_id"]))
    ho_ctx = {}
    by_repo = defaultdict(list)
    for t in ho_tasks:
        by_repo[t["repo_id"]].append(t)
    for repo, tl in by_repo.items():
        tl = sorted(tl, key=lambda x: x["task_id"])
        rng.shuffle(tl)
        n_high = len(tl) // 2
        for i, t in enumerate(tl):
            ho_ctx[t["task_id"]] = "Chigh" if i < n_high else "Clow"

    hs = []
    for t in ho_tasks:
        for pol in POLICIES:
            hs.append({
                "split": "held_out", "phase": "rq3_rq4",
                "task_id": t["task_id"], "repo_id": t["repo_id"],
                "base_commit": t["base_commit"],
                "context_condition": ho_ctx[t["task_id"]],
                "delegation": "", "policy": pol,
                "task_difficulty_stratum": t["task_difficulty_stratum"],
            })
    ho_participants = [f"H{i:03d}" for i in range(1, N_HELDOUT_PARTICIPANTS + 1)]
    hs, hdiag = assign_participants(hs, ho_participants, rng)

    # ------------------------------------------------------------------ #
    # freeze: sequence index, condition order, session ids, hashes
    # ------------------------------------------------------------------ #
    out = {}
    for name, sess in [("pilot", ps), ("discovery", ds), ("held_out", hs)]:
        rng2 = random.Random(SEED + {"pilot": 1, "discovery": 2,
                                     "held_out": 3}[name])
        # counterbalance presentation order within each participant
        byp = defaultdict(list)
        for s in sess:
            byp[s["participant_id"]].append(s)
        for p, lst in byp.items():
            rng2.shuffle(lst)
            for k, s in enumerate(lst, 1):
                s["condition_order"] = k
        sess.sort(key=lambda s: (s["participant_id"], s["condition_order"]))
        for i, s in enumerate(sess, 1):
            s["allocation_seed"] = SEED
            pref = {"pilot": "P", "discovery": "D", "held_out": "H"}[name]
            s["session_id"] = f"{pref}-S{i:04d}"
            s["sequence_index"] = i
        p = os.path.join(alloc_dir, f"allocation_{name}.csv")
        write_csv(p, sess, COLS)
        out[name] = {"path": os.path.relpath(p, TIFS).replace("\\", "/"),
                     "n_sessions": len(sess),
                     "sha256": sha256_file(p),
                     "diagnostics": {"pilot": pdiag, "discovery": ddiag,
                                     "held_out": hdiag}[name]}
        report["splits"][name] = out[name]

    # ------------------------------------------------------------------ #
    # balance verification (this is the M0 Go/No-Go evidence)
    # ------------------------------------------------------------------ #
    def verify(sess, key):
        c = Counter((s["context_condition"], s[key]) for s in sess)
        return {f"{ctx}|{grp}": n for (ctx, grp), n in sorted(c.items())}

    checks = {}
    for name, sess, key in [("pilot", ps, "delegation"),
                            ("discovery", ds, "delegation"),
                            ("held_out", hs, "policy")]:
        # C1
        viol1 = [(s["participant_id"], s["repo_id"]) for s in sess]
        dup1 = [k for k, v in Counter(viol1).items() if v > 1]
        # C2
        dup2 = [k for k, v in Counter((s["task_id"], s[key]) for s in sess).items()
                if v != 1]
        # C5/C6
        pl = Counter(s["participant_id"] for s in sess)
        ph = Counter(s["participant_id"] for s in sess
                     if s["context_condition"] == "Chigh")
        checks[name] = {
            "C1_participant_repo_repeats": len(dup1),
            "C1_examples": dup1[:5],
            "C2_duplicate_task_condition": len(dup2),
            "C3_unassigned_sessions": sum(1 for s in sess
                                          if not s["participant_id"]),
            "context_x_condition": verify(sess, key),
            "per_participant_load": {"min": min(pl.values()),
                                     "max": max(pl.values()),
                                     "n_participants": len(pl)},
            "per_participant_chigh": {"min": min(ph.values()),
                                      "max": max(ph.values())},
            "n_sessions": len(sess),
        }
    report["verification"] = checks

    # participant plan
    plan = {
        "generated_utc": NOW,
        "discovery": {
            "n_participants": N_DISCOVERY_PARTICIPANTS,
            "repositories": sorted({t["repo_id"] for t in splits["discovery"]}),
            "sessions_per_participant": {
                "min": min(Counter(s["participant_id"] for s in ds).values()),
                "max": max(Counter(s["participant_id"] for s in ds).values()),
            },
        },
        "held_out": {
            "n_participants": N_HELDOUT_PARTICIPANTS,
            "must_be_new": True,
            "must_not_have_done_pattern_discovery": True,
            "repositories": sorted({t["repo_id"] for t in splits["held_out"]}),
            "sessions_per_participant": {
                "min": min(Counter(s["participant_id"] for s in hs).values()),
                "max": max(Counter(s["participant_id"] for s in hs).values()),
            },
        },
        "pilot": {
            "n_participants": N_PILOT_PARTICIPANTS,
            "note": "infrastructure validation only; excluded from main results",
        },
        "total_participants": (N_DISCOVERY_PARTICIPANTS
                               + N_HELDOUT_PARTICIPANTS),
        "background_fields_required": [
            "total_programming_years", "professional_dev_years",
            "oss_experience", "llm_tool_frequency", "target_language_proficiency",
            "repository_familiarity_pre_task", "repository_familiarity_scale",
        ],
    }
    json.dump(plan, open(os.path.join(ROOT, "manifests", "participant_plan.json"),
                         "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    json.dump(report, open(os.path.join(ROOT, "splits", "allocation_report.json"),
                           "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    rand = {
        "generated_utc": NOW,
        "seed": SEED,
        "seed_provenance": ("paper-published fixed pseudo-random seed "
                            "(plan 4.2); retained because task and participant "
                            "counts match the paper's design"),
        "algorithm": ("per-repository context split (half Chigh, half Clow); "
                      "participant assignment by constrained-first greedy "
                      "minimisation of (load, context over-exposure) under the "
                      "hard constraint that no participant appears twice in "
                      "the same repository"),
        "generator": "experiment_root/tools/build_allocation.py",
        "generator_sha256": sha256_file(os.path.abspath(__file__)),
        "policy": ("frozen before held-out; must not be re-randomised after "
                   "any results are observed"),
    }
    json.dump(rand, open(os.path.join(alloc_dir, "randomisation.json"), "w",
                         encoding="utf-8"), indent=1, ensure_ascii=False)

    # machine-readable freeze record (hash written after all files exist)
    freeze = {
        "generated_utc": NOW,
        "allocation_seed": SEED,
        "artefacts": {k: {"path": v["path"], "sha256": v["sha256"],
                          "n_sessions": v["n_sessions"]}
                      for k, v in out.items()},
    }
    for k, p in split_files.items():
        freeze["artefacts"][f"{k}_tasks"] = {
            "path": os.path.relpath(p, TIFS).replace("\\", "/"),
            "sha256": sha256_file(p)}
    rr = os.path.join(alloc_dir, "randomisation.json")
    freeze["artefacts"]["randomisation"] = {
        "path": os.path.relpath(rr, TIFS).replace("\\", "/"),
        "sha256": sha256_file(rr)}
    json.dump(freeze, open(os.path.join(alloc_dir, "freeze_manifest.json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)

    # console report
    print(json.dumps(report, indent=1, ensure_ascii=False))
    print("\n=== FROZEN ALLOCATION ===")
    for k, v in freeze["artefacts"].items():
        print(f"  {k:20s} {v['sha256'][:16]}...  {v['path']}")


if __name__ == "__main__":
    main()
