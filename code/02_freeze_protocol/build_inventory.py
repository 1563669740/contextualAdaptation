#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase A -- Task manifests  (plan sections 3, 12.2; milestone M0)

Produces, for each of the 216 frozen tasks, a task manifest that carries
everything the runner needs and nothing the participant must not see.

Critical separation enforced here:

  participant-visible  ->  task_manifest.yaml        (issue text, base commit,
                                                      visible test entry point)
  evaluation-only      ->  evaluation_spec.yaml      (test patch, F2P/P2P
                                                      oracle, gold commit)

`visibility: participant_visible` / `visibility: evaluation_only` is written
into every manifest so the hidden-evaluation isolation check (plan 13.1) can be
audited mechanically rather than by inspection.

Sources
  dataset/tasks/<task_id>/issue.json        issue + problem statement + hints
  dataset/tasks/<task_id>/metadata.json     difficulty, gold size, split
  dataset/gold/commits.csv                  base_commit, gold commit, split
  dataset/benchmark_tests/<task_id>/        F2P/P2P lists, oracle, test cmd
  dataset/environments/docker/<task_id>/    upstream image provenance
  dataset/repositories/<repo>/              local clone (partial)
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

csv.field_size_limit(10 ** 9)

DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
TASKS_OUT = os.path.join(ROOT, "manifests", "tasks")
EVAL_OUT = os.path.join(ROOT, "evaluation_spec")

RUNNER_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# minimal deterministic YAML emitter (PyYAML is available but we want byte
# stability across versions; sorting keys guarantees reproducible hashes)
# --------------------------------------------------------------------------- #
def _scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s.strip() != s or any(c in s for c in ":#{}[]&*!|>'\"%@`,") \
            or s.lower() in ("yes", "no", "true", "false", "null", "~") \
            or s[0] in "-? " or "\n" in s:
        return json.dumps(s, ensure_ascii=False)
    return s


def yaml_dump(obj, indent=0):
    sp = "  " * indent
    out = []
    if isinstance(obj, dict):
        for k in obj:
            v = obj[k]
            if isinstance(v, (dict, list)) and v:
                out.append(f"{sp}{k}:")
                out.append(yaml_dump(v, indent + 1))
            elif isinstance(v, (dict, list)):
                out.append(f"{sp}{k}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                out.append(f"{sp}{k}: {_scalar(v)}")
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, (dict, list)) and it:
                body = yaml_dump(it, indent + 1).split("\n")
                out.append(f"{sp}- {body[0].strip()}")
                out.extend(body[1:])
            else:
                out.append(f"{sp}- {_scalar(it)}")
    return "\n".join(out)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Redaction of patch text embedded in an issue body (plan 3.1 condition 6).
#
# The comment-thread leak is handled by simply not exposing `hints_text` (see
# audit/design_decisions.md D1).  One task still embeds a `diff` inside the
# issue *body* itself, so the body needs the same treatment.  Redaction is used
# for exactly these cases and is never applied to issue text that merely
# describes the problem.
# --------------------------------------------------------------------------- #
DIFF_START_RE = re.compile(r"^diff --git a/\S+ b/\S+\s*$", re.M)
FENCED_RE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.S)
REDACTION_MARK = ("[a proposed code change was removed from this issue by the "
                  "experiment operators before the task was admitted: it is not "
                  "available in this condition]")


def redact_embedded_diffs(text):
    """Return (redacted_text, n_fenced_removed, n_bare_removed)."""
    if not isinstance(text, str) or not DIFF_START_RE.search(text):
        return text, 0, 0
    n_fenced = [0]

    def repl(m):
        if DIFF_START_RE.search(m.group(1)):
            n_fenced[0] += 1
            return REDACTION_MARK
        return m.group(0)

    out = FENCED_RE.sub(repl, text)
    n_bare = len(DIFF_START_RE.findall(out))
    if n_bare:
        # a diff that was not inside a fence: cut from the marker to the end of
        # that block (blank-line separated paragraph)
        out = DIFF_START_RE.sub(REDACTION_MARK + "\n", out)
    return out, n_fenced[0], n_bare


def read_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def main():
    os.makedirs(TASKS_OUT, exist_ok=True)
    os.makedirs(EVAL_OUT, exist_ok=True)

    commits = {r["task_id"]: r for r in csv.DictReader(
        open(os.path.join(DS, "gold", "commits.csv"), newline="",
             encoding="utf-8"))}

    task_dirs = sorted(os.listdir(os.path.join(DS, "tasks")))
    index = []
    problems = []

    for tid in task_dirs:
        td = os.path.join(DS, "tasks", tid)
        meta = read_json(os.path.join(td, "metadata.json"), {})
        issue = read_json(os.path.join(td, "issue.json"), {})
        gc = commits.get(tid, {})

        bt = os.path.join(DS, "benchmark_tests", tid)
        oracle = read_json(os.path.join(bt, "oracle.json"), {})
        test_cmd_sh = os.path.join(bt, "test_command.sh")
        test_patch = os.path.join(bt, "test_patch.diff")
        f2p_p = os.path.join(bt, "FAIL_TO_PASS.json")
        p2p_p = os.path.join(bt, "PASS_TO_PASS.json")
        env_meta = read_json(os.path.join(
            DS, "environments", "docker", tid, "environment_metadata.json"), {})

        base_commit = (meta.get("base_commit")
                       or gc.get("base_commit")
                       or (open(os.path.join(td, "base_commit.txt"),
                                encoding="utf-8").read().strip()
                           if os.path.exists(os.path.join(td, "base_commit.txt"))
                           else ""))
        repo = meta.get("repo") or issue.get("repo") or gc.get("repo")
        split = meta.get("split") or gc.get("split")

        missing = []
        for need, val in [("base_commit", base_commit), ("repo", repo),
                          ("split", split),
                          ("problem_statement", issue.get("problem_statement")),
                          ("test_patch", os.path.exists(test_patch)),
                          ("FAIL_TO_PASS", os.path.exists(f2p_p)),
                          ("PASS_TO_PASS", os.path.exists(p2p_p)),
                          ("oracle", bool(oracle))]:
            if not val:
                missing.append(need)
        if missing:
            problems.append({"task_id": tid, "missing": missing})

        repo_slug = repo.replace("/", "__")
        local_clone = os.path.join(DS, "repositories", repo_slug)

        # plan 3.1(6): strip any code-change diff embedded in the issue body
        raw_ps = issue.get("problem_statement") or ""
        ps_visible, n_fenced, n_bare = redact_embedded_diffs(raw_ps)
        redaction = {
            "fenced_removed": n_fenced,
            "bare_removed": n_bare,
            "original_chars": len(raw_ps),
            "visible_chars": len(ps_visible),
        }

        # ---- participant-visible manifest -------------------------------- #
        pv = {
            "schema_version": SCHEMA_VERSION,
            "visibility": "participant_visible",
            "task_id": tid,
            "repo_id": repo,
            "repo_slug": repo_slug,
            "issue_number": meta.get("issue_number") or issue.get("issue_number"),
            "issue_url": issue.get("issue_url"),
            "issue_title": issue.get("issue_title"),
            "split": split,
            "language": meta.get("language") or "python",
            "task_type": meta.get("task_type"),
            "task_difficulty_stratum": meta.get("estimated_difficulty"),
            "base_commit": base_commit,
            "repo_url": f"https://github.com/{repo}.git",
            "local_clone": local_clone if os.path.isdir(local_clone) else None,
            "gold_files_changed": meta.get("gold_files_changed"),
            "gold_loc_changed": meta.get("gold_loc_changed"),
            "fail_to_pass_count": meta.get("fail_to_pass_count"),
            "pass_to_pass_count": meta.get("pass_to_pass_count"),
            "log_parser": meta.get("log_parser"),
            "visible_to_participant": {
                # Plan 6: Clow gives exactly the raw issue + base repo + tools.
                #
                # `hints_text` / `all_hints_text` are deliberately NOT here.
                # They are the harvested GitHub *comment thread*, and plan 3.1
                # condition 6 forbids text that reveals the fix.  Screening
                # (tools/screen_answer_leakage.py) found that the threads for
                # 6 of the 216 tasks embed a unified diff touching the very
                # files the gold patch changes -- e.g. sphinx-12598 carries
                # three such diffs, urllib3-3527 two.  The issue body itself is
                # clean in all but one case, so the exposure rule is
                # "issue body only", recorded in audit/design_decisions.md.
                "problem_statement": ps_visible,
                "issue_title": issue.get("issue_title"),
            },
            "redaction_applied": {
                "applied": bool(redaction["fenced_removed"] or
                                redaction["bare_removed"]),
                "fenced_diff_blocks_removed": redaction["fenced_removed"],
                "bare_diff_blocks_removed": redaction["bare_removed"],
                "original_chars": redaction["original_chars"],
                "visible_chars": redaction["visible_chars"],
                "reason": ("plan 3.1 condition 6: the issue body embedded a "
                           "proposed code change"),
            },
            "withheld_from_participant": [
                "gold_patch", "test_patch", "fail_to_pass_list",
                "pass_to_pass_list", "gold_commit", "gold_commit_urls",
                "holdout_tests", "semantic_review",
                "hints_text (issue comment thread: answer-leakage risk)",
            ],
            "test_entry_point": {
                "visible_smoke": True,
                "command_template": "pytest -rA",
                "note": ("echoed from upstream environment metadata; the "
                         "evaluation command is in evaluation_spec.yaml and is "
                         "not shown to the participant"),
            },
            "manifest_generated_utc": NOW,
            "runner_version": RUNNER_VERSION,
        }

        # ---- evaluation-only spec ---------------------------------------- #
        f2p = read_json(f2p_p, [])
        p2p = read_json(p2p_p, [])
        ev = {
            "schema_version": SCHEMA_VERSION,
            "visibility": "evaluation_only",
            "task_id": tid,
            "repo_id": repo,
            "split": split,
            "base_commit": base_commit,
            "gold_commit": gc.get("gold_commit"),
            "gold_commit_urls": gc.get("commit_urls"),
            "gold_patch_file": gc.get("gold_patch_file"),
            "test_patch_file": os.path.relpath(test_patch, DS)
                               .replace("\\", "/"),
            "test_command": env_meta.get("test_command") or oracle.get("test_cmds"),
            "test_cmds": oracle.get("test_cmds"),
            "log_parser": oracle.get("log_parser"),
            "fail_to_pass": f2p,
            "pass_to_pass": p2p,
            "fail_to_pass_count": len(f2p),
            "pass_to_pass_count": len(p2p),
            "resolution_rule": oracle.get("resolution_rule"),
            "upstream_image": {
                "reference": env_meta.get("image_reference"),
                "digest": env_meta.get("image_digest"),
                "size_mb": env_meta.get("image_size_mb"),
            },
            "holdout_tests": None,
            "holdout_status": "not_authored",
            # Kept for provenance and for the leakage reviewers (plan 3.2), who
            # inspect the issue thread against the gold patch.  Never shown to a
            # participant or an agent.
            "issue_thread_not_shown_to_participant": {
                "hints_text": issue.get("hints_text"),
                "all_hints_text": issue.get("all_hints_text"),
                "why_withheld": ("the harvested comment thread can embed a "
                                 "proposed patch; see "
                                 "screening/answer_leakage.json"),
            },
            # the unredacted issue body, kept so the plan-3.2 reviewers can see
            # exactly what was removed and adjudicate it
            "issue_body_redaction_review": {
                "redaction_applied": bool(redaction["fenced_removed"] or
                                          redaction["bare_removed"]),
                "fenced_diff_blocks_removed": redaction["fenced_removed"],
                "bare_diff_blocks_removed": redaction["bare_removed"],
                "original_problem_statement": raw_ps,
                "original_chars": redaction["original_chars"],
                "visible_chars": redaction["visible_chars"],
            },
            "artefact_hashes": {
                "test_patch_sha256": sha256_file(test_patch)
                if os.path.exists(test_patch) else None,
                "fail_to_pass_sha256": sha256_file(f2p_p)
                if os.path.exists(f2p_p) else None,
                "pass_to_pass_sha256": sha256_file(p2p_p)
                if os.path.exists(p2p_p) else None,
                "oracle_sha256": sha256_file(os.path.join(bt, "oracle.json"))
                if os.path.exists(os.path.join(bt, "oracle.json")) else None,
            },
            "spec_generated_utc": NOW,
        }

        with open(os.path.join(TASKS_OUT, tid + ".yaml"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(f"# participant-visible task manifest -- task {tid}\n")
            f.write(f"# generated {NOW} by build_inventory.py "
                    f"(runner {RUNNER_VERSION})\n")
            f.write(yaml_dump(pv) + "\n")
        with open(os.path.join(EVAL_OUT, tid + ".yaml"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(f"# evaluation-only spec -- task {tid}\n")
            f.write("# NEVER expose to participant or agent (plan 13.1)\n")
            f.write(yaml_dump(ev) + "\n")

        index.append({
            "task_id": tid,
            "repo_id": repo,
            "split": split,
            "base_commit": base_commit,
            "language": pv["language"],
            "task_difficulty_stratum": pv["task_difficulty_stratum"],
            "gold_files_changed": pv["gold_files_changed"],
            "gold_loc_changed": pv["gold_loc_changed"],
            "fail_to_pass_count": pv["fail_to_pass_count"],
            "pass_to_pass_count": pv["pass_to_pass_count"],
            "manifest_file": f"manifests/tasks/{tid}.yaml",
            "evaluation_spec_file": f"evaluation_spec/{tid}.yaml",
            "manifest_sha256": sha256_file(
                os.path.join(TASKS_OUT, tid + ".yaml")),
            "evaluation_spec_sha256": sha256_file(
                os.path.join(EVAL_OUT, tid + ".yaml")),
        })

    index.sort(key=lambda r: (r["split"] or "", r["repo_id"] or "",
                              r["task_id"]))
    json.dump({"generated_utc": NOW, "n_tasks": len(index), "tasks": index},
              open(os.path.join(ROOT, "manifests", "task_index.json"), "w",
                   encoding="utf-8"), indent=1, ensure_ascii=False)

    print(f"tasks written        : {len(index)}")
    print(f"participant manifests: {len(os.listdir(TASKS_OUT))}")
    print(f"evaluation specs     : {len(os.listdir(EVAL_OUT))}")
    if problems:
        print(f"PROBLEMS ({len(problems)}):")
        for p in problems[:40]:
            print("  ", p)
    else:
        print("problems             : none")


if __name__ == "__main__":
    main()
