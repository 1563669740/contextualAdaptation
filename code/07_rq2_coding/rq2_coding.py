#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Roles B and C -- semantic review machinery and RQ2 coding machinery.

B  blind semantic review (paper V-G)
   The paper has two reviewers who do not know delegation, context, participant
   identity or benchmark results, judge a frozen rubric, and report raw
   agreement 88.9% and Cohen's kappa 0.82 (95% CI 0.78-0.86), with a third
   reviewer arbitrating.  The reviewers are human; the blinding, the packet, the
   sheet and the reliability statistic are machinery, and that is what this
   builds.  A rehearsal on synthetic reviewers proves the kappa path works,
   because a reliability number nobody can reproduce is worthless.

C  RQ2 theoretical sampling and coding reliability (paper VII-B, VII-C)
   The paper codes 360 trajectories, double-codes 72 of them and reports raw
   agreement 86.1% and kappa 0.79 (95% CI 0.74-0.84).  It also uses theoretical
   sampling: maximum-variation first (success/failure x context x delegation),
   then deliberate opposite cases for any concept concentrated in few
   repositories or a single strategy.  This module produces that sampling plan
   deterministically from the frozen allocation, and the reliability calculator
   the coders will use.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
SEED = 20260301


def w(rel, obj):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    txt = json.dumps(obj, indent=1, ensure_ascii=False)
    open(p, "w", encoding="utf-8", newline="\n").write(txt + "\n")
    return p


# --------------------------------------------------------------------------- #
# reliability: Cohen's kappa with a Wald interval
# --------------------------------------------------------------------------- #
def cohen_kappa(a, b, labels=None, bootstrap=2000, seed=20260301):
    """Cohen's kappa for two raters, with a bootstrap confidence interval.

    Implemented directly rather than pulled from a library so the exact
    estimator behind the paper's reported numbers is visible and auditable.

    The interval is bootstrapped, not Wald.  With very high agreement the Wald
    standard error collapses toward zero and produces an interval that excludes
    the observed value -- a well-known pathology that would have made the
    reported CI look implausibly tight.
    """
    if len(a) != len(b):
        raise ValueError("rater vectors differ in length")
    n = len(a)
    if n == 0:
        return None
    labels = labels or sorted(set(a) | set(b))
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)

    def kappa_of(xs, ys):
        m = [[0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            m[idx[x]][idx[y]] += 1
        po = sum(m[i][i] for i in range(k)) / len(xs)
        row = [sum(m[i]) / len(xs) for i in range(k)]
        col = [sum(m[i][j] for i in range(k)) / len(xs) for j in range(k)]
        pe = sum(row[i] * col[i] for i in range(k))
        if pe == 1:
            return None, po, pe
        return (po - pe) / (1 - pe), po, pe

    kappa, po, pe = kappa_of(a, b)
    rng = random.Random(seed)
    boots = []
    for _ in range(bootstrap):
        pick = [rng.randrange(n) for _ in range(n)]
        kk, _, _ = kappa_of([a[i] for i in pick], [b[i] for i in pick])
        if kk is not None:
            boots.append(kk)
    boots.sort()
    ci = None
    if len(boots) > 20:
        lo = boots[int(0.025 * len(boots))]
        hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]
        ci = [round(lo, 4), round(hi, 4)]
    m = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        m[idx[x]][idx[y]] += 1
    return {"n": n, "observed_agreement": round(po, 4),
            "expected_agreement": round(pe, 4),
            "cohen_kappa": round(kappa, 4) if kappa is not None else None,
            "ci_method": "bootstrap_percentile",
            "n_bootstrap": len(boots),
            "ci95": ci, "labels": labels, "confusion": m}


# --------------------------------------------------------------------------- #
# B  semantic review
# --------------------------------------------------------------------------- #
def build_review_packet(session_id, out_dir):
    """Assemble a blinded packet: issue + candidate patch + base repo, nothing
    that identifies the condition."""
    sdir = os.path.join(ROOT, "sessions", session_id)
    if not os.path.isdir(sdir):
        return None
    meta = json.load(open(os.path.join(sdir, "session_meta.json"),
                          encoding="utf-8")) if os.path.exists(
        os.path.join(sdir, "session_meta.json")) else {}
    task_id = meta.get("task_id")
    import yaml
    man = yaml.safe_load(open(os.path.join(ROOT, "manifests", "tasks",
                                           task_id + ".yaml"),
                              encoding="utf-8"))
    patch_p = os.path.join(sdir, "final.patch")
    os.makedirs(out_dir, exist_ok=True)
    packet = {
        "packet_id": f"semrev-{session_id}",
        "blinded": True,
        "must_not_contain": ["delegation", "context", "participant_id",
                            "benchmark_resolved", "holdout", "gold"],
        "issue_text": (man.get("visible_to_participant") or {}).get(
            "problem_statement"),
        "base_commit": man.get("base_commit"),
        "repo_id": man.get("repo_id"),
        "candidate_patch_present": os.path.exists(patch_p)
        and os.path.getsize(patch_p) > 0,
        "candidate_patch_path": patch_p if os.path.exists(patch_p) else None,
        "rubric_path": "protocol/semantic_review_rubric.json",
    }
    # blinding audit: scan ONLY the content the reviewer will read, never this
    # packet's own metadata.  The first version stringified the whole packet,
    # which of course contained the words "delegation" and "resolved" in its own
    # field names, so every packet reported a leak.
    content_blob = " ".join(str(x) for x in (
        packet["issue_text"], task_id, packet["repo_id"])).lower()
    patch_text = ""
    if packet["candidate_patch_path"] and os.path.exists(
            packet["candidate_patch_path"]):
        patch_text = open(packet["candidate_patch_path"], encoding="utf-8",
                          errors="replace").read().lower()
    scanned = content_blob + " " + patch_text
    packet["blinding_audit"] = {
        "scanned_fields": ["issue_text", "task_id", "repo_id",
                           "candidate_patch"],
        "scanned_chars": len(scanned),
        "leaks_condition": any(k in scanned for k in
                               ("delegation", "shared_control", "human_led",
                                "ai_led", "chigh", "clow")),
        "leaks_participant": "participant" in scanned,
        "leaks_outcome": any(k in scanned for k in
                             ("benchmark_resolved", "enhanced_resolved",
                              "holdout")),
        "leaks_gold": "gold patch" in scanned,
    }
    packet["blinding_ok"] = not any(
        v for k, v in packet["blinding_audit"].items()
        if k.startswith("leaks_"))
    p = os.path.join(out_dir, f"{session_id}.json")
    json.dump(packet, open(p, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    return packet


def rehearse_semantic_review():
    """Prove the kappa path with synthetic raters.

    Two reviewers agree on a realistic proportion of cases and disagree on the
    rest; the reported statistics must land near the paper's targets, which
    shows the estimator is wired correctly.  These are NOT results.
    """
    rng = random.Random(SEED)
    n = 90
    truth = [rng.random() < 0.7 for _ in range(n)]      # would-accept
    A, B = [], []
    for t in truth:
        # 89% raw agreement, which is the paper's reported figure
        if rng.random() < 0.889:
            A.append(t); B.append(t)
        else:
            A.append(t); B.append(not t)
    ka = cohen_kappa(A, B, [True, False])
    # ordinal item, three levels
    lv = ["yes", "partly", "no"]
    A2 = [rng.choice(lv) for _ in range(n)]
    B2 = [a if rng.random() < 0.889 else rng.choice(lv) for a in A2]
    kb = cohen_kappa(A2, B2, lv)
    return {
        "rehearsal_utc": NOW,
        "synthetic": True,
        "NOT_A_RESULT": ("raters are simulated, so these numbers validate the "
                         "estimator only; the paper's 88.9% / kappa 0.82 come "
                         "from real reviewers"),
        "would_accept": ka,
        "issue_intent_satisfied": kb,
        "paper_targets": {"raw_agreement": 0.889, "kappa": 0.82,
                          "ci95": [0.78, 0.86]},
        "estimator_check": {
            "observed_agreement_matches_target":
                abs(ka["observed_agreement"] - 0.889) < 0.06,
            "kappa_in_plausible_range": 0.5 < (ka["cohen_kappa"] or 0) < 1.0,
            "ci_computed": ka["ci95"] is not None,
        },
    }


# --------------------------------------------------------------------------- #
# C  theoretical sampling + coding reliability
# --------------------------------------------------------------------------- #
def load_alloc(split):
    p = os.path.join(ROOT, "splits", f"allocation_{split}.csv")
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def theoretical_sample(rows, want_double_coded=72, per_cell=6):
    """Maximum-variation first, then deliberate opposite cases.

    Stage 1: cover every (context x delegation) cell, the RQ2 'maximum
    difference' sample.
    Stage 2: for each repository, add a case from a different condition than the
    one already sampled, which is the paper's negative-case step for concepts
    that cluster in few repositories or a single strategy.
    Stage 3: fill the double-coding quota by even spread.
    """
    rng = random.Random(SEED)
    by_cell = {}
    for r in rows:
        key = (r["context_condition"], r["delegation"] or r["policy"])
        by_cell.setdefault(key, []).append(r)
    chosen, seen = [], set()

    for key, cell in sorted(by_cell.items()):
        pool = [r for r in cell if r["repo_id"] not in
                {c["repo_id"] for c in chosen}]
        rng.shuffle(pool)
        for r in (pool or cell)[:per_cell]:
            if r["session_id"] not in seen:
                chosen.append(r); seen.add(r["session_id"])

    by_repo = {}
    for r in rows:
        by_repo.setdefault(r["repo_id"], []).append(r)
    already = {c["repo_id"] for c in chosen}
    for repo, rs in sorted(by_repo.items()):
        conds = {c["context_condition"] for c in chosen if c["repo_id"] == repo}
        opp = [r for r in rs
               if r["context_condition"] not in conds
               or (r["delegation"] or r["policy"]) !=
               next((c["delegation"] or c["policy"] for c in chosen
                     if c["repo_id"] == repo), None)]
        rng.shuffle(opp)
        for r in opp[:1]:
            if r["session_id"] not in seen:
                chosen.append(r); seen.add(r["session_id"])
                already.add(repo)

    rest = [r for r in rows if r["session_id"] not in seen]
    rng.shuffle(rest)
    for r in rest:
        if len(chosen) >= want_double_coded:
            break
        chosen.append(r); seen.add(r["session_id"])

    cells = {}
    for c in chosen:
        k = f"{c['context_condition']}|{c['delegation'] or c['policy']}"
        cells[k] = cells.get(k, 0) + 1
    return chosen[:max(want_double_coded, len(by_cell) * per_cell)], cells


def rehearse_codebook_reliability():
    """Exercise the coder-reliability path with synthetic coders.

    The paper double-codes 72 trajectories and reports 86.1% raw agreement and
    kappa 0.79 (0.74-0.84).  Simulating that lets us show the reported statistic
    is computed by the same code the coders will use.
    """
    rng = random.Random(SEED)
    signals = ["P1", "P2", "P3", "P4", "P5", "P6"]
    n = 72
    per_signal = {}
    for s in signals:
        base = rng.random() * 0.5 + 0.2
        A = [rng.random() < base for _ in range(n)]
        B = [a if rng.random() < 0.861 else (not a) for a in A]
        per_signal[s] = cohen_kappa(A, B, [True, False])
    kappas = [v["cohen_kappa"] for v in per_signal.values()
              if v["cohen_kappa"] is not None]
    return {
        "rehearsal_utc": NOW,
        "synthetic": True,
        "NOT_A_RESULT": ("coders are simulated; the paper's 86.1% / kappa 0.79 "
                         "come from real double coding"),
        "n_trajectories": n,
        "per_signal": per_signal,
        "mean_kappa": round(sum(kappas) / len(kappas), 4) if kappas else None,
        "paper_targets": {"n_double_coded": 72, "raw_agreement": 0.861,
                          "kappa": 0.79, "ci95": [0.74, 0.84],
                          "stability": "last 48: 0 new concepts, 2 boundary revisions"},
        "computed_with": "cohen_kappa() in tools/rq2_coding.py",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semantic-output", default="evaluation/_semantic_packets")
    ap.add_argument("--session", action="append", default=[])
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()

    out = {}

    # semantic review packets for whatever sessions exist
    sdir = os.path.join(ROOT, "sessions")
    sessions = a.session or (sorted(os.listdir(sdir))
                             if os.path.isdir(sdir) else [])
    packets, leaks, examples = 0, 0, []
    for sid in sessions:
        pkt = build_review_packet(sid, os.path.join(ROOT, a.semantic_output))
        if not pkt:
            continue
        packets += 1
        if not pkt.get("blinding_ok", False):
            leaks += 1
            examples.append({"session_id": sid,
                             "audit": pkt["blinding_audit"]})
    out["semantic_review_packets"] = {
        "built": packets, "blinding_leaks": leaks,
        "leak_examples": examples[:5],
        "dir": a.semantic_output,
        "note": ("packets contain the issue, the candidate patch and the "
                 "rubric; the audit scans ONLY that reviewer-visible content, "
                 "so packet metadata naming a field does not count as a leak"),
    }

    if a.rehearse or not a.sample:
        out["semantic_rehearsal"] = rehearse_semantic_review()
        out["codebook_rehearsal"] = rehearse_codebook_reliability()

    if a.sample or a.rehearse:
        rows = load_alloc("discovery")
        chosen, cells = theoretical_sample(rows)
        plan = {
            "generated_utc": NOW,
            "paper_reference": "Section VII-B, VII-C step 5",
            "method": ("stage 1 maximum-variation coverage of all "
                       "context x delegation cells; stage 2 deliberate opposite "
                       "case per repository; stage 3 fill the double-coding quota"),
            "n_selected": len(chosen),
            "cell_coverage": cells,
            "double_coding_quota": 72,
            "stability_check": ("the final 48 trajectories must introduce no new "
                                "top-level concept and at most a boundary "
                                "revision, per the paper"),
            "sessions": [{"session_id": r["session_id"],
                          "task_id": r["task_id"], "repo_id": r["repo_id"],
                          "context_condition": r["context_condition"],
                          "delegation": r["delegation"]} for r in chosen],
        }
        w("codebook/rq2_sampling_plan.json", plan)
        out["rq2_sampling_plan"] = {"n_selected": len(chosen),
                                    "cells": len(cells),
                                    "file": "codebook/rq2_sampling_plan.json"}

    w("audit/role_bc_report.json", {"generated_utc": NOW, **out})
    print(json.dumps(out, indent=1, ensure_ascii=False)[:2600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
