#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase J -- Answer-leakage screening of participant-visible text (plan 3.2)

Plan 3.2 requires every candidate task to be screened for
`answer_leakage: none | minor | major` **before** it is admitted, and plan 3.1
condition 6 says the problem description must not directly reveal the complete
repair code or the target patch.

The failure mode this tool exists for is specific and was found empirically:
SWE-bench-Live harvests the whole GitHub issue *thread*, and maintainers
routinely paste a proposed `diff` into a comment.  That text then lands in
`hints_text` / `all_hints_text` and is handed to the participant with the task.

For each task the scan:
  1. extracts every embedded unified-diff block from the participant-visible
     text (problem_statement, hints_text, all_hints_text)
  2. extracts the gold patch's changed file set
  3. classifies the overlap:
       major     -- an embedded diff modifies one or more gold files
       minor     -- the visible text names a gold file but embeds no diff to it
       none      -- no gold file is touched or named
  4. for `major`, also measures how much of the gold hunk *content* already
     appears verbatim, which separates "here is the fix" from "here is a
     reproduction patch for a different symptom in the same file"

Outputs
  screening/answer_leakage.csv     one row per task, reviewable by two humans
  screening/answer_leakage.json    same data plus the diff-block detail
  screening/redacted/<task_id>.json  a participant-safe variant of the visible
                                   text with embedded diff blocks removed, so
                                   the team can choose redaction over exclusion

Nothing here is applied automatically: plan 3.2 makes exclusion/adjudication a
human decision, and this tool's job is to make that decision informed.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter

import yaml

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
OUT = os.path.join(ROOT, "screening")

DIFF_START = re.compile(r"^diff --git a/(\S+) b/(\S+)\s*$", re.M)
HUNK = re.compile(r"^@@ ", re.M)
FENCE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.S)


def gold_files(task_id):
    p = os.path.join(DS, "gold", "patches", task_id + ".patch")
    if not os.path.exists(p):
        return set(), ""
    txt = open(p, encoding="utf-8", errors="replace").read()
    return set(re.findall(r"^diff --git a/(\S+)", txt, re.M)), txt


def gold_added_lines(gold_txt):
    """Non-trivial added lines, used to measure verbatim reuse."""
    out = set()
    for line in gold_txt.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            s = line[1:].strip()
            if len(s) >= 12 and not s.startswith("#"):
                out.add(s)
    return out


def diff_blocks(text):
    """Return [(block_text, files, n_hunks)] for every unified diff found."""
    blocks = []
    for m in DIFF_START.finditer(text):
        start = m.start()
        nxt = DIFF_START.search(text, m.end())
        end = nxt.start() if nxt else len(text)
        blk = text[start:end]
        # stop at a closing code fence if the diff was inside one
        fence_end = blk.find("\n```")
        if fence_end != -1:
            blk = blk[:fence_end]
        files = {m.group(1)} | set(re.findall(r"^diff --git a/(\S+) b/", blk, re.M))
        files |= set(re.findall(r"^\+\+\+ b/(\S+)", blk, re.M))
        files = {f for f in files if f and f != "/dev/null"}
        blocks.append((blk, files, len(HUNK.findall(blk))))
    return blocks


def named_files_in_text(text):
    """File paths merely *mentioned* (markdown links, backticks, prose)."""
    cands = set()
    for pat in (r"`([\w./-]+\.(?:py|js|ts|rst|toml|cfg|ini|txt|md|pyi))`",
                r"\b([\w-]+/[\w./-]+\.(?:py|js|ts|rst|toml|cfg|ini))"):
        for m in re.finditer(pat, text):
            cands.add(m.group(1))
    return cands


def analyse(task_id):
    mp = os.path.join(ROOT, "manifests", "tasks", task_id + ".yaml")
    man = yaml.safe_load(open(mp, encoding="utf-8"))
    vis = man.get("visible_to_participant") or {}
    gf, gold_txt = gold_files(task_id)
    gold_add = gold_added_lines(gold_txt)

    rec = {
        "task_id": task_id,
        "repo_id": man.get("repo_id"),
        "split": man.get("split"),
        "gold_files": sorted(gf),
        "n_gold_files": len(gf),
        "fields_with_diffs": [],
        "diff_blocks": [],
        "leaked_gold_files": [],
        "named_gold_files": [],
        "gold_added_lines_reused": 0,
        "answer_leakage": "none",
        "reviewer_A": "", "reviewer_B": "", "adjudication": "",
    }

    all_block_files = set()
    all_named = set()
    for field in ("problem_statement", "hints_text", "all_hints_text"):
        text = vis.get(field)
        if not isinstance(text, str) or not text:
            continue
        blocks = diff_blocks(text)
        if blocks:
            rec["fields_with_diffs"].append(field)
        for blk, files, nh in blocks:
            reused = sum(1 for l in blk.splitlines()
                         if l.startswith("+") and l[1:].strip() in gold_add)
            rec["diff_blocks"].append({
                "field": field, "files": sorted(files), "n_hunks": nh,
                "n_lines": len(blk.splitlines()),
                "gold_files_touched": sorted(files & gf),
                "gold_added_lines_reused": reused,
            })
            all_block_files |= files
        all_named |= named_files_in_text(text)

    rec["leaked_gold_files"] = sorted(all_block_files & gf)
    rec["named_gold_files"] = sorted(all_named & gf)
    rec["gold_added_lines_reused"] = sum(b["gold_added_lines_reused"]
                                         for b in rec["diff_blocks"])

    if rec["leaked_gold_files"]:
        rec["answer_leakage"] = "major"
    elif rec["named_gold_files"]:
        rec["answer_leakage"] = "minor"
    return rec


def redact(task_id, rec):
    """Participant-safe variant: strip embedded diff blocks from visible text."""
    mp = os.path.join(ROOT, "manifests", "tasks", task_id + ".yaml")
    man = yaml.safe_load(open(mp, encoding="utf-8"))
    vis = man.get("visible_to_participant") or {}
    out = {"task_id": task_id, "redacted_fields": []}
    for field in ("problem_statement", "hints_text", "all_hints_text"):
        text = vis.get(field)
        if not isinstance(text, str) or not DIFF_START.search(text):
            continue
        stripped = 0
        # replace every fenced block that contains a unified diff
        def repl(m):
            nonlocal stripped
            if DIFF_START.search(m.group(1)):
                stripped += 1
                return "[a proposed code change was removed from this thread: " \
                       "it is not available in this condition]"
            return m.group(0)
        new = FENCE.sub(repl, text)
        # any diff outside a fence
        new = DIFF_START.sub("[a proposed code change was removed: not available "
                             "in this condition]\n", new)
        if new != text:
            out[field] = new
            out["redacted_fields"].append({"field": field,
                                           "fenced_blocks_removed": stripped,
                                           "orig_chars": len(text),
                                           "new_chars": len(new)})
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "redacted"), exist_ok=True)
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]

    rows = []
    for i, t in enumerate(idx, 1):
        tid = t["task_id"]
        try:
            rec = analyse(tid)
        except Exception as e:
            rec = {"task_id": tid, "answer_leakage": "scan_error",
                   "error": f"{type(e).__name__}: {e}"}
        rows.append(rec)
        if rec.get("answer_leakage") == "major":
            json.dump(redact(tid, rec),
                      open(os.path.join(OUT, "redacted", tid + ".json"), "w",
                           encoding="utf-8"), indent=1, ensure_ascii=False)
        if i % 40 == 0:
            print(f"  scanned {i}/{len(idx)}", file=sys.stderr, flush=True)

    with open(os.path.join(OUT, "answer_leakage.csv"), "w", newline="",
              encoding="utf-8") as f:
        cols = ["task_id", "repo_id", "split", "answer_leakage",
                "n_gold_files", "leaked_gold_files", "named_gold_files",
                "gold_added_lines_reused", "fields_with_diffs",
                "reviewer_A", "reviewer_B", "adjudication"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (json.dumps(r.get(c), ensure_ascii=False)
                            if isinstance(r.get(c), list) else r.get(c, ""))
                        for c in cols})

    dist = Counter(r.get("answer_leakage") for r in rows)
    by_split = {}
    for r in rows:
        by_split.setdefault(r.get("split"), Counter())[r.get("answer_leakage")] += 1

    json.dump({
        "generated_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criteria": {
            "major": "an embedded unified diff in participant-visible text "
                     "modifies a file that the gold patch also modifies",
            "minor": "participant-visible text names a gold file but embeds no "
                     "diff touching it",
            "none": "no gold file is touched or named in participant-visible text",
        },
        "plan_reference": "3.1 condition 6, 3.2 answer_leakage field",
        "distribution": dict(dist),
        "by_split": {k: dict(v) for k, v in by_split.items()},
        "n_tasks": len(rows),
        "tasks": rows,
    }, open(os.path.join(OUT, "answer_leakage.json"), "w", encoding="utf-8"),
        indent=1, ensure_ascii=False)

    print(f"scanned {len(rows)} tasks")
    print(f"  distribution: {dict(dist)}")
    for sp, c in by_split.items():
        print(f"  {sp:10s}: {dict(c)}")
    maj = [r["task_id"] for r in rows if r.get("answer_leakage") == "major"]
    if maj:
        print(f"\nMAJOR ({len(maj)}) -- require adjudication under plan 3.2:")
        for t in maj:
            r = next(x for x in rows if x["task_id"] == t)
            print(f"  {t:52s} gold files touched by an embedded diff: "
                  f"{r['leaked_gold_files']}")


if __name__ == "__main__":
    main()
