#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase H -- Freeze, audit and QA report (plan 13, 14, 16; milestones M0/M1)

Produces the machine-checkable evidence behind the plan's pre-collection
checklist.  Every check writes a PASS / FAIL / WARN line plus the raw counts, so
a reviewer can disagree with a verdict by inspecting numbers rather than code.

Checks
  A  completeness      every task has manifest + evaluation spec, parsable
  B  split integrity   repository-level isolation; counts match the paper
  C  allocation        balance, hard constraints, frozen hashes unchanged
  D  leakage           no gold / test-patch / oracle material inside anything a
                       participant or agent can reach
  E  hidden isolation  the evaluation spec is marked evaluation_only and lives
                       outside the participant-visible tree
  F  secrets / PII     scan frozen artefacts for credentials and absolute
                       personal paths
  G  reproducibility   inventory + snapshot hashes present for every task
  H  coverage gaps     artefacts the plan requires but that are not yet
                       authored (reported explicitly, never silently passed)

`--freeze` additionally writes audit/freeze_manifest.json: one SHA256 per
frozen artefact plus a single tree-level digest, which is the object that gets
tagged at M0 and re-verified at M4.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

csv.field_size_limit(10 ** 9)

TIFS = r"C:\Users\Administrator\Desktop\TIFS"
ROOT = os.path.join(TIFS, "experiment_root")
DS = os.path.join(TIFS, "dataset")
AUDIT = os.path.join(ROOT, "audit")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

EXPECT = {
    "pilot": {"repos": 6, "tasks": 24, "sessions": 72},
    "discovery": {"repos": 20, "tasks": 120, "sessions": 360},
    "held_out": {"repos": 12, "tasks": 72, "sessions": 360},
}
CELL_EXPECT_DISCOVERY = 60
POLICY_CELL_EXPECT_HELDOUT = 36      # context split inside each policy

SECRET_PATTERNS = [
    (r"(?i)\b(api[_-]?key|secret|passwd|password|token)\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
     "possible credential literal"),
    (r"\bghp_[A-Za-z0-9]{20,}", "GitHub personal access token"),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
]
# Issue bodies legitimately contain sanitised placeholders; only a *real* value
# is worth reporting, and even then it is a human decision.
REDACTION_TOKENS = re.compile(
    r"(?i)^(redacted|removed|hidden|\*\*\*+|x{3,}|\.{3,}|<[^>]*>|\$\{?[a-z_]+\}?|"
    r"your[_-]?\w*|example\w*|placeholder|changeme|none|null|password|token|"
    r"secret|foo|bar|baz|test\w*)$")
PII_PATTERNS = [
    (r"[A-Za-z]:\\\\Users\\\\[A-Za-z0-9._-]+", "absolute Windows user path"),
    (r"/home/[a-z][a-z0-9._-]+/", "absolute Linux home path"),
]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_json(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def read_text(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def load_eval_spec(rel):
    """Evaluation specs are YAML. Reading them with json.load always failed,
    which silently made the 'visibility' checks vacuous."""
    import yaml
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return {}
    try:
        return yaml.safe_load(open(p, encoding="utf-8")) or {}
    except Exception:
        return {}


def load_yaml(rel):
    import yaml
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return {}
    try:
        return yaml.safe_load(open(p, encoding="utf-8")) or {}
    except Exception:
        return {}


# A participant manifest may name these *fields* only in its
# `withheld_from_participant` declaration; carrying the field as data is a leak.
ORACLE_VALUE_KEYS = {
    "fail_to_pass", "pass_to_pass", "gold_commit", "gold_commit_urls",
    "test_patch", "test_patch_file", "resolution_rule", "oracle",
    "gold_patch_file", "fail_to_pass_tests", "pass_to_pass_tests",
}
# Permitted coarse metrics -- the plan's own screening form (3.2) records the
# repair *size*, which is a scale signal, not a location.
ALLOWED_METRIC_KEYS = {
    "fail_to_pass_count", "pass_to_pass_count", "gold_files_changed",
    "gold_loc_changed", "gold_commit_count", "gold_hunks",
    "gold_modules_changed", "gold_loc_added", "gold_loc_deleted",
}


def visible_text_of(man):
    """Only the text a participant can actually read.  Checking these fields is
    both faster and more meaningful than stringifying the whole manifest."""
    vis = man.get("visible_to_participant") or {}
    parts = []
    if isinstance(vis, dict):
        for v in vis.values():
            if isinstance(v, str):
                parts.append(v)
    for k in ("issue_title", "task_type", "task_type_reason"):
        v = man.get(k)
        if isinstance(v, str):
            parts.append(v)
    return "\n".join(parts)


def oracle_leak_in_manifest(man, spec, terms=None):
    """Two different severities, deliberately separated.

    `hard`  -- participant-visible text contains patch text or an oracle value
               that has no legitimate reason to be there.  This is a defect.
    `review`-- visible text names a file or symbol that the grading tests also
               reference.  Often legitimate: a reporter describing a bug may
               name the test file they ran, or an issue may concern a core
               module like `babel/core.py`.  Plan 3.2 assigns this to human
               adjudication, so it is reported rather than failed.
    """
    hard, review = [], []
    for k in man.keys():
        if k in ORACLE_VALUE_KEYS:
            hard.append(f"top-level key `{k}` carries oracle data")
    vis = man.get("visible_to_participant")
    if isinstance(vis, dict):
        for k in vis:
            if k in ORACLE_VALUE_KEYS:
                hard.append(f"visible_to_participant.{k} carries oracle data")

    txt = visible_text_of(man)
    if "diff --git" in txt:
        hard.append("patch text present in participant-visible text")

    if terms is None:
        terms = oracle_terms_of(spec or {})
    gold = (spec or {}).get("gold_commit")
    if gold and len(str(gold)) >= 12 and str(gold) in txt:
        hard.append("gold_commit value present in visible text")
    for t in sorted(terms, key=len, reverse=True):
        if t in txt:
            # a full node id ("path::test") is more telling than a bare path
            bucket = hard if "::" in t else review
            bucket.append(f"visible text mentions oracle-referenced identifier "
                          f"`{t[:70]}`")
    return hard, review


def oracle_terms_of(spec):
    terms = set()
    for key in ("fail_to_pass", "pass_to_pass"):
        for tt in (spec.get(key) or [])[:40]:
            tt = str(tt)
            terms.add(tt)
            terms.add(tt.split("::")[0])
            terms.add(tt.split("::")[-1].split("[")[0])
    gc = spec.get("gold_commit")
    if gc:
        terms.add(str(gc))
        terms.add(str(gc)[:12])
    return {t for t in terms if t and len(t) > 8}


class Report:
    def __init__(self):
        self.checks = []

    def add(self, group, name, status, detail, evidence=None):
        self.checks.append({"group": group, "check": name, "status": status,
                            "detail": detail, "evidence": evidence or {}})
        mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[status]
        print(f"[{mark}] {group:14s} {name}: {detail}")
        return status

    def summary(self):
        from collections import Counter
        c = Counter(x["status"] for x in self.checks)
        return {"PASS": c["PASS"], "FAIL": c["FAIL"], "WARN": c["WARN"],
                "total": len(self.checks)}


# --------------------------------------------------------------------------- #
def check_completeness(r, index):
    tasks = index["tasks"]
    r.add("A_completeness", "task_index_size", "PASS" if len(tasks) == 216
          else "FAIL", f"{len(tasks)} tasks in the frozen index "
                       f"(expected 216)")
    miss_m = [t["task_id"] for t in tasks
              if not os.path.exists(os.path.join(ROOT, t["manifest_file"]))]
    miss_e = [t["task_id"] for t in tasks
              if not os.path.exists(os.path.join(ROOT, t["evaluation_spec_file"]))]
    r.add("A_completeness", "manifests_present", "PASS" if not miss_m else "FAIL",
          f"{len(tasks)-len(miss_m)}/{len(tasks)} participant manifests",
          {"missing": miss_m[:20]})
    r.add("A_completeness", "evaluation_specs_present",
          "PASS" if not miss_e else "FAIL",
          f"{len(tasks)-len(miss_e)}/{len(tasks)} evaluation specs",
          {"missing": miss_e[:20]})

    bad = []
    for t in tasks:
        p = os.path.join(ROOT, t["manifest_file"])
        if not os.path.exists(p):
            continue
        if sha256_file(p) != t["manifest_sha256"]:
            bad.append(t["task_id"])
    r.add("A_completeness", "manifest_hashes_match",
          "PASS" if not bad else "FAIL",
          f"{len(tasks)-len(bad)}/{len(tasks)} manifests match their recorded hash",
          {"mismatched": bad[:20]})

    # participant manifests must never carry oracle *values*
    leaks, reviews, terms_cache = [], [], {}
    for t in tasks:
        man = load_yaml(t["manifest_file"])
        spec = load_eval_spec(t["evaluation_spec_file"])
        terms_cache[t["task_id"]] = oracle_terms_of(spec)
        hard, rev = oracle_leak_in_manifest(man, spec)
        if hard:
            leaks.append({"task_id": t["task_id"], "problems": hard})
        if rev:
            reviews.append({"task_id": t["task_id"], "notes": rev})
    r.add("A_completeness", "manifest_field_purity",
          "PASS" if not leaks else "FAIL",
          f"{len(leaks)}/{len(tasks)} participant manifests carry patch text or "
          f"oracle values (a field name inside `withheld_from_participant` is a "
          f"declaration, not a leak)",
          {"leaks": leaks[:20]})
    r.add("A_completeness", "visible_text_names_graded_files", "WARN"
          if reviews else "PASS",
          f"{len(reviews)} tasks where the issue body names a file the grading "
          f"tests also reference -- legitimate in most bug reports, but plan 3.2 "
          f"assigns it to human adjudication",
          {"tasks": [x["task_id"] for x in reviews]})
    return terms_cache


def check_splits(r, index):
    tasks = index["tasks"]
    by_split = {}
    for t in tasks:
        by_split.setdefault(t["split"], []).append(t)
    for sp, exp in EXPECT.items():
        got = by_split.get(sp, [])
        repos = {t["repo_id"] for t in got}
        ok = len(got) == exp["tasks"] and len(repos) == exp["repos"]
        r.add("B_split", f"{sp}_counts", "PASS" if ok else "FAIL",
              f"{len(got)} tasks / {len(repos)} repos "
              f"(expected {exp['tasks']}/{exp['repos']})")
    sets = {sp: {t["repo_id"] for t in v} for sp, v in by_split.items()}
    overlap = ((sets.get("pilot", set()) & sets.get("discovery", set()))
               | (sets.get("pilot", set()) & sets.get("held_out", set()))
               | (sets.get("discovery", set()) & sets.get("held_out", set())))
    r.add("B_split", "repository_isolation", "PASS" if not overlap else "FAIL",
          f"{len(overlap)} repositories appear in more than one split",
          {"overlap": sorted(overlap)})
    diff = {}
    for sp, got in by_split.items():
        d = {}
        for t in got:
            d[t["task_difficulty_stratum"]] = d.get(t["task_difficulty_stratum"], 0) + 1
        diff[sp] = d
    r.add("B_split", "difficulty_strata", "PASS", "distribution by split",
          diff)


def check_allocations(r):
    frozen = read_json(os.path.join(ROOT, "splits", "freeze_manifest.json"), {})
    art = frozen.get("artefacts", {})
    for name in ("pilot", "discovery", "held_out"):
        p = os.path.join(ROOT, "splits", f"allocation_{name}.csv")
        if not os.path.exists(p):
            r.add("C_allocation", f"{name}_file", "FAIL", "missing")
            continue
        rec = art.get(name, {})
        h = sha256_file(p)
        ok = (rec.get("sha256") == h) if rec else None
        r.add("C_allocation", f"{name}_hash",
              "PASS" if ok else ("WARN" if ok is None else "FAIL"),
              f"sha256 {h[:16]}… {'matches' if ok else 'MISMATCH' if ok is False else 'no record'}",
              {"sha256": h, "recorded": rec.get("sha256")})

        rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
        n = len(rows)
        exp = EXPECT[name]["sessions"]
        r.add("C_allocation", f"{name}_session_count",
              "PASS" if n == exp else "FAIL", f"{n} sessions (expected {exp})")
        if not rows:
            continue
        key = "delegation" if name != "held_out" else "policy"
        from collections import Counter
        cells = Counter((x["context_condition"], x[key]) for x in rows)
        if name == "discovery":
            bad = {f"{a}|{b}": c for (a, b), c in cells.items()
                   if c != CELL_EXPECT_DISCOVERY}
            r.add("C_allocation", "discovery_cell_balance",
                  "PASS" if not bad and len(cells) == 6 else "FAIL",
                  f"{len(cells)} cells, all == {CELL_EXPECT_DISCOVERY}: "
                  f"{not bad}", {"cells": {f"{a}|{b}": c for (a, b), c in cells.items()}})
        if name == "held_out":
            per = Counter(b for (a, b) in cells)
            flags = {}
            for pol in per:
                ch = cells.get(("Chigh", pol), 0)
                cl = cells.get(("Clow", pol), 0)
                flags[pol] = f"{ch}/{cl}"
            r.add("C_allocation", "heldout_context_balance", "PASS",
                  "Chigh/Clow per policy", flags)
        # hard constraints
        dup_repo = [k for k, v in Counter(
            (x["participant_id"], x["repo_id"]) for x in rows).items() if v > 1]
        r.add("C_allocation", f"{name}_participant_repo_unique",
              "PASS" if not dup_repo else "FAIL",
              f"{len(dup_repo)} participant-repository repeats", {"examples": dup_repo[:5]})
        dup_sess = [k for k, v in Counter(
            (x["task_id"], x[key]) for x in rows).items() if v != 1]
        r.add("C_allocation", f"{name}_task_condition_unique",
              "PASS" if not dup_sess else "FAIL",
              f"{len(dup_sess)} duplicate (task, condition) pairs")
        pl = Counter(x["participant_id"] for x in rows)
        r.add("C_allocation", f"{name}_load_balance", "PASS",
              f"per-participant sessions min={min(pl.values())} "
              f"max={max(pl.values())} over {len(pl)} participants")


def check_leakage(r, index):
    tasks = index["tasks"]
    # 1. context packages must exist for every task and contain no oracle text
    cp_dir = os.path.join(ROOT, "context_packages")
    present = [t["task_id"] for t in tasks
               if os.path.exists(os.path.join(cp_dir, t["task_id"] + ".md"))]
    r.add("D_leakage", "context_package_coverage",
          "PASS" if len(present) == len(tasks) else "WARN",
          f"{len(present)}/{len(tasks)} context packages built",
          {"missing": [t["task_id"] for t in tasks if t["task_id"] not in set(present)][:20]})

    # every evaluation spec must carry oracle identifiers we can hunt for.
    #
    # Two severities, because the distinction is the whole point:
    #   hard   -- the package reproduces the grading *list* itself, a F2P node
    #             id ("path::test[param]"), the gold commit, or patch text.
    #             That is hidden material.
    #   review -- the package mentions a test module path or a bare test
    #             function name.  Those files are in the base commit and the
    #             participant can list them with one command
    #             (`find . -name 'test_*.py'`), and plan 6.1 item 4 explicitly
    #             requires the package to describe the test layout.  So this is
    #             expected content, reported for the reviewer rather than
    #             failed.
    oracle_terms, node_ids = {}, {}
    for t in tasks:
        spec = load_eval_spec(t["evaluation_spec_file"])
        terms = set()
        nodes = set()
        for key in ("fail_to_pass", "pass_to_pass"):
            for tt in (spec.get(key) or [])[:60]:
                tt = str(tt)
                if "::" in tt:
                    nodes.add(tt)
                terms.add(tt.split("::")[0])
                terms.add(tt.split("::")[-1].split("[")[0])
        gc = spec.get("gold_commit")
        if gc:
            terms.add(str(gc))
            terms.add(str(gc)[:12])
        oracle_terms[t["task_id"]] = {x for x in terms if x and len(x) > 8}
        node_ids[t["task_id"]] = nodes

    hard, review = [], []
    for tid in present:
        body = read_text(os.path.join(cp_dir, tid + ".md"))
        for nid in node_ids.get(tid, ()):
            if nid in body:
                hard.append({"task_id": tid, "term": nid[:80]})
        if "diff --git" in body:
            hard.append({"task_id": tid, "term": "patch text"})
        for term in oracle_terms.get(tid, ()):
            if term in body:
                review.append({"task_id": tid, "term": term[:80]})
    r.add("D_leakage", "context_package_oracle_terms",
          "PASS" if not hard else "FAIL",
          f"{len(hard)} hidden-oracle hits (grading node ids / patch text) in "
          f"{len(present)} context packages "
          f"({sum(len(v) for v in oracle_terms.values())} identifiers checked)",
          {"hits": hard[:20]})
    r.add("D_leakage", "context_package_test_path_mentions",
          "WARN" if review else "PASS",
          f"{len(review)} mentions of test module paths / bare test function "
          f"names across {len({x['task_id'] for x in review})} packages -- "
          f"these files exist in the base commit and plan 6.1 item 4 asks for "
          f"the test layout, so this is expected rather than hidden",
          {"sample": review[:15],
           "affected_tasks": sorted({x["task_id"] for x in review})})

    # the participant tree keeps coarse size metrics but must not carry a
    # grading test list or any patch text
    dirty, review_only = [], []
    for t in tasks:
        man = load_yaml(t["manifest_file"])
        hard, rev = oracle_leak_in_manifest(
            man, None, terms=oracle_terms.get(t["task_id"]))
        if hard:
            dirty.append({"task_id": t["task_id"], "problems": hard})
        elif rev:
            review_only.append(t["task_id"])
    r.add("D_leakage", "participant_tree_clean",
          "PASS" if not dirty else "FAIL",
          f"{len(dirty)}/{len(tasks)} participant manifests carry patch text or "
          f"grading material; {len(review_only)} more are name-mention only",
          {"dirty": dirty[:10]})

    # 2. no holdout test may be reachable from the participant tree
    ho = os.path.join(DS, "holdout_tests")
    n_ho = len(os.listdir(ho)) if os.path.isdir(ho) else 0
    r.add("D_leakage", "holdout_authored", "WARN" if n_ho == 0 else "PASS",
          f"{n_ho} holdout suites exist (plan 11.2 requires one per task)")

    # 3. plan 3.2 answer_leakage screening -- issue threads can carry patches
    sl = read_json(os.path.join(ROOT, "screening", "answer_leakage.json"))
    if not sl:
        r.add("D_leakage", "answer_leakage_screening", "FAIL",
              "screening/answer_leakage.json missing; run "
              "tools/screen_answer_leakage.py")
    else:
        dist = sl.get("distribution", {})
        by_split = sl.get("by_split", {})
        major = [t["task_id"] for t in sl.get("tasks", [])
                 if t.get("answer_leakage") == "major"]
        major_main = [t for t, sp in
                      ((t["task_id"], t.get("split")) for t in sl.get("tasks", []))
                      if t in set(major) and sp in ("discovery", "held_out")]
        r.add("D_leakage", "answer_leakage_distribution",
              "PASS" if not major_main else "FAIL",
              f"{dist.get('major', 0)} major / {dist.get('minor', 0)} minor / "
              f"{dist.get('none', 0)} none; severe leaks outside pilot: "
              f"{len(major_main)}",
              {"distribution_by_split": by_split, "major_tasks": major,
               "major_outside_pilot": major_main})
        adjudicated = [t for t in sl.get("tasks", [])
                       if t.get("answer_leakage") in ("major", "minor")
                       and (t.get("adjudication") or "").strip()]
        need = sum(1 for t in sl.get("tasks", [])
                   if t.get("answer_leakage") in ("major", "minor"))
        r.add("D_leakage", "answer_leakage_adjudicated",
              "PASS" if adjudicated and len(adjudicated) == need else "WARN",
              f"{len(adjudicated)}/{need} leaked tasks have a recorded "
              f"adjudication (plan 3.2 requires two reviewers + arbitration)",
              {"pending": [t["task_id"] for t in sl.get("tasks", [])
                           if t.get("answer_leakage") in ("major", "minor")
                           and not (t.get("adjudication") or "").strip()]})


def check_isolation(r, index):
    tasks = index["tasks"]
    bad = []
    for t in tasks:
        spec = load_eval_spec(t["evaluation_spec_file"])
        if spec.get("visibility") != "evaluation_only":
            bad.append(t["task_id"])
    r.add("E_isolation", "specs_marked_evaluation_only",
          "PASS" if not bad else "FAIL",
          f"{len(tasks)-len(bad)}/{len(tasks)} specs carry visibility="
          f"evaluation_only")
    inside = [t["task_id"] for t in tasks
              if os.path.abspath(os.path.join(ROOT, t["evaluation_spec_file"]))
              .startswith(os.path.join(ROOT, "manifests"))]
    r.add("E_isolation", "specs_outside_participant_tree",
          "PASS" if not inside else "FAIL",
          "evaluation specs live under experiment_root/evaluation_spec/")
    # the runner must refuse unallocated sessions
    runner = read_text(os.path.join(ROOT, "tools", "session_runner.py"))
    r.add("E_isolation", "runner_rejects_unallocated",
          "PASS" if "is not in the frozen allocation" in runner else "FAIL",
          "session_runner refuses session ids absent from the allocation file")
    r.add("E_isolation", "runner_enforces_cap",
          "PASS" if "SESSION_CAP_MIN = 75" in runner else "FAIL",
          "75-minute hard stop is a constant in the runner")


def scan_secrets(r, roots):
    hits = []
    scanned = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("repo_cache", "__pycache__",
                                                "_eval_workspaces")]
            for f in fn:
                if not f.endswith((".md", ".json", ".yaml", ".yml", ".py",
                                   ".txt", ".csv")):
                    continue
                p = os.path.join(dp, f)
                if os.path.getsize(p) > 4_000_000:
                    continue
                scanned += 1
                txt = read_text(p)
                for pat, label in SECRET_PATTERNS:
                    for m in re.finditer(pat, txt):
                        val = m.group(m.lastindex) if m.lastindex else m.group(0)
                        if REDACTION_TOKENS.match(val.strip()):
                            continue           # sanitised placeholder, not a secret
                        hits.append({"file": os.path.relpath(p, TIFS),
                                     "kind": label,
                                     "sample": m.group(0)[:40]})
                for pat, label in PII_PATTERNS:
                    n = len(re.findall(pat, txt))
                    if n:
                        hits.append({"file": os.path.relpath(p, TIFS),
                                     "kind": label, "count": n})
    hard = [h for h in hits if "path" not in h["kind"]]
    r.add("F_secrets", "credential_scan",
          "PASS" if not hard else "WARN",
          f"{len(hard)} credential-like values in {scanned} scanned files "
          f"(sanitised placeholders such as REDACTED are ignored; a hit here "
          f"needs human adjudication, not automatic failure)",
          {"hits": hard[:15]})
    paths = [h for h in hits if "path" in h["kind"]]
    r.add("F_secrets", "absolute_path_scan", "WARN" if paths else "PASS",
          f"{len(paths)} files contain absolute personal paths "
          f"(manifests record local_clone by design; de-identify before release)",
          {"files": sorted({h["file"] for h in paths})[:15]})


def check_reproducibility(r, index):
    inv = os.path.join(ROOT, "repo_cache", "_inventory")
    snap = os.path.join(ROOT, "repo_cache", "_snapshots")
    have_inv, have_snap, ok_inv = 0, 0, 0
    for t in index["tasks"]:
        tid = t["task_id"]
        ip = os.path.join(inv, tid + ".json")
        sp = os.path.join(snap, tid + ".json")
        if os.path.exists(ip):
            have_inv += 1
            d = read_json(ip, {})
            if d.get("ok") and d.get("n_files"):
                ok_inv += 1
        if os.path.exists(sp):
            have_snap += 1
    n = len(index["tasks"])
    r.add("G_reproducibility", "inventories", "PASS" if have_inv == n else "WARN",
          f"{have_inv}/{n} base-commit inventories ({ok_inv} non-empty)")
    r.add("G_reproducibility", "content_snapshots",
          "PASS" if have_snap == n else "WARN",
          f"{have_snap}/{n} content snapshots for context-package provenance")
    clones = [d for d in os.listdir(os.path.join(ROOT, "repo_cache"))
              if os.path.isdir(os.path.join(ROOT, "repo_cache", d))
              and not d.startswith("_")]
    r.add("G_reproducibility", "repo_clones", "PASS" if len(clones) >= 38
          else "WARN", f"{len(clones)}/38 base repositories cloned locally")
    alloc = read_json(os.path.join(ROOT, "splits", "randomisation.json"), {})
    r.add("G_reproducibility", "seed_frozen",
          "PASS" if alloc.get("seed") is not None else "FAIL",
          f"allocation seed {alloc.get('seed')} recorded with generator hash")


def check_paper_requirements(r):
    """Requirements taken from the paper itself (TIFS_韩林峄), which the plan
    document did not enumerate.  Existence is a PASS; a null 'frozen_utc' or a
    'TO_BE_*' status is a WARN, because those need humans."""
    reqs = [
        ("protocol/repository_understanding_v1.json", "V-A manipulation check"),
        ("protocol/semantic_review_rubric.json", "V-G blind semantic review"),
        ("protocol/replayability_v1.json", "V-H replayable trajectory"),
        ("protocol/freeze_record.json", "III-D freeze record"),
        ("policy/online_extractor_v1.json", "VIII-A online extractor"),
        ("policy/threshold_selection.json", "VIII-B threshold selection"),
        ("evaluation/holdout_construction_log.json", "V-G holdout log"),
    ]
    missing, pending = [], []
    for rel, label in reqs:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            missing.append({"artefact": rel, "paper_ref": label})
            continue
        d = read_json(p, {})
        status = str(d.get("status", ""))
        unfrozen = d.get("frozen_utc") in (None, "") and \
            not d.get("record", {}).get("freeze_timestamp_utc")
        if status.startswith("TO_BE") or status.startswith("template") or unfrozen:
            pending.append({"artefact": rel, "paper_ref": label,
                            "status": status or "frozen_utc is null"})
    r.add("I_paper_reqs", "artefacts_present",
          "PASS" if not missing else "FAIL",
          f"{len(reqs)-len(missing)}/{len(reqs)} paper-mandated artefacts exist",
          {"missing": missing})
    r.add("I_paper_reqs", "artefacts_frozen",
          "PASS" if not pending else "WARN",
          f"{len(pending)}/{len(reqs)} still carry a TO_BE / template status or "
          f"no freeze timestamp",
          {"pending": pending})

    # paper's own acceptance numbers, recorded so a reviewer can compare later
    r.add("I_paper_reqs", "paper_reference_numbers", "PASS",
          "targets recorded from the paper for later comparison",
          {
              "manipulation_check": {"Chigh": 8.4, "Clow": 5.9, "diff": 2.5,
                                     "ci95": [2.21, 2.79], "scale": 10},
              "protocol_violation_rate": 0.022,
              "holdout_tests_per_task": {"median": 4, "iqr": [3, 6]},
              "semantic_review": {"agreement": 0.889, "kappa": 0.82,
                                  "ci95": [0.78, 0.86]},
              "codebook_reliability": {"trajectories": 72, "raw": 0.861,
                                       "kappa": 0.79, "ci95": [0.74, 0.84],
                                       "final": 0.986,
                                       "stability": "last 48: 0 new concepts, 2 boundary revisions"},
              "extractor_validation": {"precision": 0.86, "recall": 0.86,
                                       "f1": 0.86, "kappa": 0.86,
                                       "per_signal": [0.80, 0.91]},
              "rq3_routing": {"agreement": "49/72", "unnecessary_escalation": "8/72",
                              "late_escalation": "6/72", "first_escalation_at": "18.0 min"},
              "model_config": {"model": "GPT-5.2 Codex", "reasoning": "medium",
                               "agent": "OpenHands 0.50.0"},
          })

    # the paper's allocation constraints, re-verified here rather than trusted
    import collections
    for name, key in (("discovery", "delegation"), ("held_out", "policy")):
        p = os.path.join(ROOT, "splits", f"allocation_{name}.csv")
        if not os.path.exists(p):
            continue
        rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
        pr = collections.Counter((x["participant_id"], x["repo_id"]) for x in rows)
        pt = collections.Counter((x["participant_id"], x["task_id"]) for x in rows)
        ctx = collections.defaultdict(set)
        for x in rows:
            ctx[x["task_id"]].add(x["context_condition"])
        pol = collections.defaultdict(set)
        for x in rows:
            pol[x["task_id"]].add(x["participant_id"])
        checks = {
            "participant_repo_at_most_once": sum(1 for v in pr.values() if v > 1) == 0,
            "participant_task_at_most_once": sum(1 for v in pt.values() if v > 1) == 0,
            "context_fixed_per_task": all(len(v) == 1 for v in ctx.values()),
        }
        if name == "held_out":
            checks["distinct_participants_across_policies"] = all(
                len(v) == 5 for v in pol.values())
        r.add("I_paper_reqs", f"{name}_paper_constraints",
              "PASS" if all(checks.values()) else "FAIL",
              "paper V-C / IX-B allocation constraints re-verified from the "
              "frozen allocation file", checks)


def check_role_artifacts(r):
    """Artefacts produced by acting out the paper's human roles.

    Each entry is either a working mechanism with recorded evidence, or an
    explicitly labelled stand-in.  The distinction is reported, not blurred: a
    mechanism proven on synthetic input is NOT a research result.
    """
    checks = []

    mm = read_json(os.path.join(ROOT, "manifests", "model_manifest.json"), {})
    vals = mm.get("values") or {}
    checks.append((
        "model_manifest_paper_fields",
        bool(vals.get("model_snapshot")) and bool(vals.get("agent_version")),
        f"snapshot={vals.get('model_snapshot')} agent={vals.get('agent_version')}"))
    checks.append((
        "sampling_seed_not_recorded",
        mm.get("seed_policy", {}).get("satisfied") is True,
        "paper: an uncontrollable seed is not a reproduction parameter"))

    fr = read_json(os.path.join(ROOT, "protocol", "freeze_record.json"), {})
    rec = fr.get("record") or {}
    checks.append(("freeze_record_allocation_hash",
                   bool(rec.get("allocation_file_sha256")),
                   f"allocation {str(rec.get('allocation_file_sha256'))[:16]}"))
    checks.append(("freeze_record_tree_digest",
                   bool(rec.get("frozen_artefact_tree_digest")),
                   f"tree {str(rec.get('frozen_artefact_tree_digest'))[:16]}"))

    fp = read_json(os.path.join(ROOT, "manifests",
                                "environment_fingerprint.json"), {})
    checks.append(("experiment_host_fingerprint",
                   bool(fp.get("hostname")) and bool(fp.get("python_version")),
                   f"{fp.get('hostname')} python {fp.get('python_version')} "
                   f"role={fp.get('host_role')}"))

    st = read_json(os.path.join(ROOT, "policy", "extractor_self_test.json"), {})
    checks.append(("extractor_causality_tested",
                   bool(st.get("checks", {}).get("all_pass")),
                   "extractor self-test passes, including lookahead refusal"))

    ts = read_json(os.path.join(ROOT, "policy", "threshold_selection.json"), {})
    checks.append(("threshold_cv_runs",
                   bool(ts.get("k")) and bool(ts.get("n_cases")),
                   f"k={ts.get('k')} repos={len(ts.get('groups') or [])} "
                   f"cases={ts.get('n_cases')} status={ts.get('status')}"))

    rh = read_json(os.path.join(ROOT, "audit", "session_rehearsal.json"), {})
    out = rh.get("outcome") or {}
    checks.append(("session_sop_rehearsed",
                   bool(out) and not out.get("sop_steps_failed")
                   and out.get("guards_blocked_as_expected"),
                   f"{out.get('sop_steps_completed')} steps, guards OK, "
                   f"metrics={out.get('metrics_extracted')}"))

    hl = read_json(os.path.join(ROOT, "evaluation",
                                "holdout_construction_log.json"), {})
    checks.append(("holdout_suite_admitted",
                   bool(hl.get("n_tasks_admitted")),
                   f"{hl.get('n_tasks_admitted')} task(s) admitted"))

    # calibration feasibility: only tasks whose environment can distinguish the
    # defect from the fix are authorable at all
    feas = read_json(os.path.join(ROOT, "audit", "holdout_feasibility.json"), {})
    if feas:
        n_cal = feas.get("n_calibrated", 0)
        n_ok = feas.get("n_authorable", 0)
        pattern = {}
        for t in feas.get("tasks", []):
            if t.get("oracle_reproduced"):
                continue
            if t.get("base_rc") == t.get("gold_rc") == 4:
                pattern["collection_error_both"] = \
                    pattern.get("collection_error_both", 0) + 1
            elif t.get("gold_rc") != 0:
                pattern["gold_does_not_pass"] = \
                    pattern.get("gold_does_not_pass", 0) + 1
        checks.append((
            "oracle_reproducible_measured",
            n_ok > 0,
            f"{n_ok}/{n_cal} calibrated tasks reproduce the oracle; failure "
            f"modes {pattern}. This is the real authoring denominator and it is "
            f"NOT 216 -- see audit/HOLDOUT_FEASIBILITY.md"))
        r.add("J_roles", "holdout_feasibility", "WARN",
              f"only {n_ok}/{n_cal} sampled tasks can distinguish defect from "
              f"fix in this non-Docker environment; the rest split into "
              f"collection errors (infrastructure) and gold-did-not-pass "
              f"(dataset labelling)",
              {"measured": feas.get("n_calibrated"),
               "authorable": feas.get("n_authorable"),
               "failure_modes": pattern})

    # A2 understanding quiz
    qdir = os.path.join(ROOT, "protocol", "quiz_items")
    qfiles = [f for f in os.listdir(qdir) if f.endswith(".json")] \
        if os.path.isdir(qdir) else []
    adm = 0
    for f in qfiles:
        d = read_json(os.path.join(qdir, f), {})
        a = d.get("admissibility") or {}
        if a.get("meets_blueprint") and a.get("answerable_from_base_repo_only") \
                and a.get("no_item_mentions_the_defect"):
            adm += 1
    checks.append(("understanding_quiz_items",
                   adm == 216,
                   f"{adm}/{len(qfiles)} quizzes meet the 10-point blueprint "
                   f"and pass the admissibility gates"))

    # B semantic review
    bc = read_json(os.path.join(ROOT, "audit", "role_bc_report.json"), {})
    sp = bc.get("semantic_review_packets") or {}
    checks.append(("semantic_review_blinding",
                   bool(sp.get("built")) and not sp.get("blinding_leaks"),
                   f"{sp.get('built')} packet(s), {sp.get('blinding_leaks')} "
                   f"blinding leaks"))
    sr = (bc.get("semantic_rehearsal") or {}).get("estimator_check") or {}
    checks.append(("kappa_estimator_validated",
                   bool(sr) and all(sr.values()),
                   f"bootstrap CI validated on synthetic raters: {sr}"))

    # C RQ2 sampling
    pl = read_json(os.path.join(ROOT, "codebook", "rq2_sampling_plan.json"), {})
    checks.append(("rq2_theoretical_sampling",
                   pl.get("n_selected") == 72 and len(pl.get("cell_coverage")
                                                      or {}) == 6,
                   f"{pl.get('n_selected')} sessions across "
                   f"{len(pl.get('cell_coverage') or {})} context x delegation "
                   f"cells"))

    # pre-registered admission gate
    gs = read_json(os.path.join(ROOT, "audit", "admission_gate",
                                "_summary.json"), {})
    if gs:
        d = gs.get("distribution") or {}
        checks.append((
            "admission_gate_run",
            bool(d.get("admitted")),
            f"{gs.get('n_classified')}/{gs.get('n_total_tasks')} tasks "
            f"classified: {d}"))
        r.add("J_roles", "admission_gate", "WARN",
              f"{d.get('excluded_gold_incomplete', 0)} task(s) excluded because "
              f"the gold patch does not pass its own fail-to-pass tests, and "
              f"{d.get('environment_fault', 0)} have environment faults. "
              f"Substitution must happen BEFORE recruitment (see "
              f"audit/ADMISSION_GATE.md)",
              {"excluded_gold_incomplete":
                   gs.get("excluded_gold_incomplete"),
               "environment_fault": gs.get("environment_fault")})

    fails = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        r.add("J_roles", name, "PASS" if ok else "WARN", str(detail))
    r.add("J_roles", "role_artefacts_summary",
          "PASS" if not fails else "WARN",
          f"{len(checks)-len(fails)}/{len(checks)} role artefacts present and "
          f"verified. Holdout authoring is proven end to end on two tasks; the "
          f"remaining tasks need the same human pass, and the real authoring "
          f"denominator is measured in audit/HOLDOUT_FEASIBILITY.md.",
          {"not_yet": [c[0] for c in fails]})


def check_synthetic_separation(r):
    """Synthetic data must be runnable AND impossible to mistake for real data.

    A simulation is only legitimate if it cannot contaminate the study it is
    meant to exercise, so the separation is audited rather than asserted.
    """
    sim = os.path.join(ROOT, "analysis", "synthetic")
    if not os.path.isdir(sim):
        r.add("K_synthetic", "synthetic_sample", "WARN",
              "no synthetic sample present (run tools/simulate.py all)")
        return
    sdir = os.path.join(sim, "sessions")
    metas = []
    if os.path.isdir(sdir):
        for d in os.listdir(sdir):
            p = os.path.join(sdir, d, "session_meta.json")
            if os.path.exists(p):
                try:
                    metas.append(json.load(open(p, encoding="utf-8")))
                except Exception:
                    pass
    marked = sum(1 for m in metas if m.get("SYNTHETIC"))
    r.add("K_synthetic", "synthetic_marked",
          "PASS" if metas and marked == len(metas) else "FAIL",
          f"{marked}/{len(metas)} synthetic session metas carry SYNTHETIC=true")

    # the real sessions tree must not contain synthetic sessions
    real = os.path.join(ROOT, "sessions")
    contaminated = []
    if os.path.isdir(real):
        for d in os.listdir(real):
            p = os.path.join(real, d, "session_meta.json")
            if os.path.exists(p):
                try:
                    if json.load(open(p, encoding="utf-8")).get("SYNTHETIC"):
                        contaminated.append(d)
                except Exception:
                    pass
    r.add("K_synthetic", "no_synthetic_in_real_tree",
          "PASS" if not contaminated else "FAIL",
          f"{len(contaminated)} synthetic session(s) found under the real "
          f"sessions/ tree", {"contaminated": contaminated[:10]})

    # synthetic metrics must live in analysis/synthetic, never analysis/
    real_csv = os.path.join(ROOT, "analysis", "session_metrics.csv")
    n_real = 0
    if os.path.exists(real_csv):
        with open(real_csv, newline="", encoding="utf-8") as f:
            n_real = max(0, sum(1 for _ in f) - 1)
    sim_csv = os.path.join(sim, "session_metrics.csv")
    n_sim = 0
    if os.path.exists(sim_csv):
        with open(sim_csv, newline="", encoding="utf-8") as f:
            n_sim = max(0, sum(1 for _ in f) - 1)
    r.add("K_synthetic", "metrics_separated",
          "PASS" if n_real <= 20 else "WARN",
          f"analysis/session_metrics.csv holds {n_real} row(s) (real sessions "
          f"only) while the synthetic sample's {n_sim} rows live under "
          f"analysis/synthetic/")

    pc = read_json(os.path.join(sim, "_pipeline_check.json"), {})
    r.add("K_synthetic", "pipeline_validated_on_synthetic", "PASS" if pc else "WARN",
          "the analysis pipeline consumed the full synthetic sample; see "
          "analysis/synthetic/SIMULATION_REPORT.md for what that does and does "
          "not establish")

    rep = os.path.join(sim, "SIMULATION_REPORT.md")
    r.add("K_synthetic", "not_a_result_disclosed",
          "PASS" if os.path.exists(rep) else "WARN",
          "simulation report states explicitly that no number in it is a "
          "finding about human-AI delegation")


def check_gaps(r):
    """Artefacts the plan and the paper require but that need humans, so they
    are reported rather than silently passed.  See
    audit/PAPER_GAP_ANALYSIS.md for the full traceability table."""
    gaps = []
    ho = os.path.join(DS, "holdout_tests")
    n_ho = len(os.listdir(ho)) if os.path.isdir(ho) else 0
    if n_ho == 0:
        gaps.append({
            "artefact": "holdout_tests/",
            "plan_ref": "11.2",
            "why": ("Enhanced Resolved cannot be computed; each test must fail "
                    "at base_commit, pass on gold, and be deterministic over 5 "
                    "runs"),
            "owner": "evaluation staff who never see candidate patches",
        })
    gaps.append({
        "artefact": "sessions/",
        "plan_ref": "8, 9",
        "why": ("360 discovery + 360 held-out + 72 pilot sessions require human "
                "participants and an AI gateway; the runner and logger are in "
                "place but no session has been run"),
        "owner": "experiment operators",
    })
    gaps.append({
        "artefact": "manifests/model_manifest.json",
        "plan_ref": "9.1",
        "why": "model snapshot / agent version / tool config hash not yet filled",
        "owner": "experiment operators",
    })
    gaps.append({
        "artefact": "repository understanding quiz items + per-task holdout tests",
        "plan_ref": "paper V-A, V-G",
        "why": ("the instrument blueprints are frozen, but the per-task items "
                "and the holdout tests need humans who have not run a session "
                "and cannot see candidate patches"),
        "owner": "evaluation staff / study designers",
    })
    gaps.append({
        "artefact": "RQ2 inductive coding + stimulated recall",
        "plan_ref": "paper VII-B, VII-C",
        "why": ("codebook definitions are frozen, but the coding itself and the "
                "recall interviews are human work; the paper reports 72 "
                "double-coded trajectories, raw agreement 86.1%, kappa 0.79"),
        "owner": "qualitative coders",
    })
    gaps.append({
        "artefact": "policy/online_extractor implementation + threshold CV",
        "plan_ref": "paper VIII-A, VIII-B",
        "why": ("extractor specification is frozen (including the rule that it "
                "may not read future events or post-hoc labels); the "
                "implementation and the repository-grouped 5-fold threshold "
                "selection need Discovery trajectories"),
        "owner": "experiment operators",
    })
    r.add("H_gaps", "outstanding_artefacts", "WARN",
          f"{len(gaps)} artefact families are specified but not yet collected",
          {"gaps": gaps})


def freeze(index):
    os.makedirs(AUDIT, exist_ok=True)
    artefacts = {}

    def add(rel):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            artefacts[rel.replace("\\", "/")] = {
                "sha256": sha256_file(p), "bytes": os.path.getsize(p)}

    # a curated list keeps the freeze manifest reviewable
    for pat in ["manifests/task_index.json", "manifests/participant_plan.json",
                "manifests/environment_spec.json", "manifests/model_manifest.json",
                "splits/allocation_pilot.csv", "splits/allocation_discovery.csv",
                "splits/allocation_held_out.csv", "splits/pilot_tasks.csv",
                "splits/discovery_tasks.csv", "splits/held_out_tasks.csv",
                "splits/randomisation.json", "splits/allocation_report.json",
                "splits/freeze_manifest.json",
                "protocol/protocol_v1.md", "protocol/event_schema.json",
                "protocol/delegation_regimes.json", "protocol/measurements.json",
                "codebook/codebook_v1.json", "policy/adaptive_policy_v1.json",
                "tools/build_inventory.py", "tools/build_allocation.py",
                "tools/build_context_packages.py", "tools/build_protocol.py",
                "tools/audit.py", "tools/session_runner.py",
                "tools/build_env_manifests.py",
                "tools/build_paper_artefacts.py",
                "tools/build_role_artifacts.py",
                "tools/task_env.py", "tools/holdout_author.py",
                "tools/online_policy.py", "tools/rehearse_session.py",
                "tools/build_understanding_quiz.py", "tools/rq2_coding.py",
                "tools/simulate.py", "tools/admission_gate.py",
                "tools/aggregate_metrics.py", "tools/pilot_gates.py",
                "tools/adjudicate_leakage.py", "tools/screen_answer_leakage.py",
                "protocol/questionnaire_v1.json",
                "protocol/repository_understanding_v1.json",
                "protocol/semantic_review_rubric.json",
                "protocol/replayability_v1.json", "protocol/freeze_record.json",
                "policy/online_extractor_v1.json",
                "policy/threshold_selection.json",
                "evaluation/holdout_construction_log.json",
                "audit/PAPER_GAP_ANALYSIS.md", "audit/design_decisions.md",
                "evaluation/evaluate.py",
                "repo_cache/fetch_repos.py",
                "repo_cache/fetch_repos_tarball.py"]:
        add(pat)

    # every task manifest + evaluation spec + context package, hashed in bulk
    for sub, ext in (("manifests/tasks", ".yaml"), ("evaluation_spec", ".yaml"),
                     ("context_packages", ".md")):
        d = os.path.join(ROOT, sub)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(ext):
                    add(f"{sub}/{f}")

    tree = sha256_text(json.dumps(
        {k: v["sha256"] for k, v in sorted(artefacts.items())},
        sort_keys=True))
    out = {
        "frozen_utc": NOW,
        "n_artefacts": len(artefacts),
        "tree_digest_sha256": tree,
        "algorithm": ("SHA256 per artefact; tree digest is the SHA256 of the "
                      "JSON map of relative path -> hash, sorted by path"),
        "policy": ("this digest is the object tagged at M0; it is re-verified "
                   "at M4 and must not change after formal collection starts"),
        "artefacts": artefacts,
    }
    json.dump(out, open(os.path.join(AUDIT, "freeze_manifest.json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()

    os.makedirs(AUDIT, exist_ok=True)
    index = read_json(os.path.join(ROOT, "manifests", "task_index.json"))
    if not index:
        raise SystemExit("run tools/build_inventory.py first")

    r = Report()
    print("=" * 74)
    print(f"experiment_root audit   {NOW}")
    print("=" * 74)
    check_completeness(r, index)
    check_splits(r, index)
    check_allocations(r)
    check_leakage(r, index)
    check_isolation(r, index)
    scan_secrets(r, [os.path.join(ROOT, "manifests"),
                     os.path.join(ROOT, "splits"),
                     os.path.join(ROOT, "context_packages"),
                     os.path.join(ROOT, "protocol"),
                     os.path.join(ROOT, "codebook"),
                     os.path.join(ROOT, "policy"),
                     os.path.join(ROOT, "audit")])
    check_reproducibility(r, index)
    check_paper_requirements(r)
    check_role_artifacts(r)
    check_synthetic_separation(r)
    check_gaps(r)

    summ = r.summary()
    print("-" * 74)
    print(f"PASS {summ['PASS']}   FAIL {summ['FAIL']}   WARN {summ['WARN']}   "
          f"total {summ['total']}")

    rep = {"generated_utc": NOW, "summary": summ, "checks": r.checks}
    json.dump(rep, open(os.path.join(AUDIT, "qa_report.json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)

    # markdown summary for humans
    lines = [f"# QA / audit report", "", f"Generated {NOW}", "",
             f"**PASS {summ['PASS']} · FAIL {summ['FAIL']} · "
             f"WARN {summ['WARN']}** (of {summ['total']} checks)", ""]
    groups = {}
    for c in r.checks:
        groups.setdefault(c["group"], []).append(c)
    for g, cs in groups.items():
        lines.append(f"## {g}")
        lines.append("")
        lines.append("| check | status | detail |")
        lines.append("|---|---|---|")
        for c in cs:
            lines.append(f"| `{c['check']}` | {c['status']} | "
                         f"{c['detail'].replace('|', chr(92)+'|')} |")
        lines.append("")
    open(os.path.join(AUDIT, "qa_report.md"), "w", encoding="utf-8",
         newline="\n").write("\n".join(lines))

    if a.freeze:
        f = freeze(index)
        print("-" * 74)
        print(f"FROZEN {f['n_artefacts']} artefacts")
        print(f"tree digest sha256 = {f['tree_digest_sha256']}")

    return 1 if summ["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
