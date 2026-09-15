#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase K -- Answer-leakage adjudication workbench (plan 3.2)

Plan 3.2 requires at least two researchers to read the issue, the gold patch and
the tests independently for every candidate task, record their conclusions, and
send disagreements to a third researcher for arbitration.  `answer_leakage` is
one of the recorded fields.

`tools/screen_answer_leakage.py` computes the *machine* verdict.  This tool is
the human half:

  sheet     write review/A-<task>.md and review/B-<task>.md, self-contained
            evidence packs so each reviewer can work independently and blind to
            the other's conclusion
  record    write one reviewer's verdict for one task
  status    show outstanding adjudications and inter-reviewer agreement
  summary   write screening/adjudication_summary.md for the study record

Reviewer instructions embedded in each sheet are the plan's, not this tool's
invention: reviewers judge `answer_leakage: none | minor | major` against the
gold patch, and a disagreement goes to arbitration.  Reviewers never see each
other's verdict before recording their own, which is what makes the reliability
statistic meaningful.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import yaml

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
SCREEN = os.path.join(ROOT, "screening")
REVIEW = os.path.join(SCREEN, "review")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

REVIEW_FIELDS = ["build_reproducible", "offline_capable", "corrective_repair",
                 "estimated_minutes", "answer_leakage",
                 "external_dependency_risk", "reviewer", "conclusion",
                 "reason"]


def load_screening():
    p = os.path.join(SCREEN, "answer_leakage.json")
    if not os.path.exists(p):
        sys.exit("run tools/screen_answer_leakage.py first")
    return json.load(open(p, encoding="utf-8"))


def save_screening(data):
    data["adjudication_updated_utc"] = NOW
    json.dump(data, open(os.path.join(SCREEN, "answer_leakage.json"), "w",
                         encoding="utf-8"), indent=1, ensure_ascii=False)


def load_verdicts():
    p = os.path.join(REVIEW, "verdicts.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"schema_version": "1.0", "verdicts": {}}


def save_verdicts(v):
    os.makedirs(REVIEW, exist_ok=True)
    v["updated_utc"] = NOW
    json.dump(v, open(os.path.join(REVIEW, "verdicts.json"), "w",
                      encoding="utf-8"), indent=1, ensure_ascii=False)


def task_record(data, task_id):
    for t in data["tasks"]:
        if t["task_id"] == task_id:
            return t
    sys.exit(f"{task_id} not in screening data")


def gold_patch_text(task_id, limit=6000):
    p = os.path.join(DS, "gold", "patches", task_id + ".patch")
    if not os.path.exists(p):
        return "(gold patch not found)"
    return open(p, encoding="utf-8", errors="replace").read()[:limit]


def issue_body(task_id):
    mp = os.path.join(ROOT, "manifests", "tasks", task_id + ".yaml")
    man = yaml.safe_load(open(mp, encoding="utf-8"))
    return (man.get("visible_to_participant") or {}).get("problem_statement") or ""


def issue_thread(task_id):
    sp = os.path.join(ROOT, "evaluation_spec", task_id + ".yaml")
    spec = yaml.safe_load(open(sp, encoding="utf-8"))
    th = spec.get("issue_thread_not_shown_to_participant") or {}
    return th.get("all_hints_text") or th.get("hints_text") or ""


def embedded_diffs(task_id, rec):
    """The literal diff blocks the machine flagged, so the reviewer sees the
    same evidence the rule saw."""
    out = []
    for b in rec.get("diff_blocks", []):
        if b.get("gold_files_touched"):
            out.append(b)
    return out


def cmd_sheet(a):
    data = load_screening()
    os.makedirs(REVIEW, exist_ok=True)
    todo = [t for t in data["tasks"]
            if t.get("answer_leakage") in ("major", "minor")]
    if a.task_id:
        todo = [t for t in todo if t["task_id"] in set(a.task_id)]
    written = []
    for rec in todo:
        tid = rec["task_id"]
        for reviewer in ("A", "B"):
            path = os.path.join(REVIEW, f"{reviewer}-{tid}.md")
            L = []
            A = L.append
            A(f"# Answer-leakage review sheet — reviewer {reviewer}")
            A("")
            A(f"**Task:** `{tid}`  ")
            A(f"**Repository:** {rec.get('repo_id')}  ")
            A(f"**Split:** {rec.get('split')}  ")
            A(f"**Machine verdict (`answer_leakage`):** "
              f"`{rec.get('answer_leakage')}`  ")
            A(f"**Generated:** {NOW}")
            A("")
            A("## Your task (plan 3.2)")
            A("")
            A("Read the issue text, the gold patch and the flagged excerpts "
              "below, then record independently:")
            A("")
            A("| field | your value | allowed values |")
            A("|---|---|---|")
            A("| `answer_leakage` | | `none` / `minor` / `major` |")
            A("| `corrective_repair` | | `yes` / `no` |")
            A("| `build_reproducible` | | `yes` / `no` |")
            A("| `offline_capable` | | `yes` / `no` / `partial` |")
            A("| `estimated_minutes` | | number (>75 is an exclusion candidate) |")
            A("| `external_dependency_risk` | | `low` / `medium` / `high` |")
            A("| `conclusion` | | `keep` / `exclude` |")
            A("| `reason` | | free text |")
            A("")
            A("Definitions: **none** = participant-visible text neither shows "
              "nor names anything the gold patch touches. **minor** = it names "
              "a file the gold patch touches but shows no change to it. "
              "**major** = it shows an actual code change to a file the gold "
              "patch changes, or otherwise hands over the fix.")
            A("")
            A(f"## Participants see this text")
            A("")
            A(f"Characters: {len(issue_body(tid))}  ·  "
              f"`diff --git` blocks in it: "
              f"{issue_body(tid).count('diff --git')}")
            A("")
            A("The full participant-visible issue body is in "
              f"`manifests/tasks/{tid}.yaml` under "
              "`visible_to_participant.problem_statement`.")
            A("")
            A("## Gold patch (evaluation-only)")
            A("")
            A("```diff")
            A(gold_patch_text(tid))
            A("```")
            A("")
            A("## Machine-flagged excerpts")
            A("")
            blocks = embedded_diffs(tid, rec)
            if not blocks:
                nm = rec.get("named_gold_files") or []
                A(f"No embedded diff touches a gold file. The text merely "
                  f"names: {', '.join('`'+x+'`' for x in nm)}")
            for b in blocks:
                A(f"### `{b['field']}` — {b['n_hunks']} hunk(s), "
                  f"{b['n_lines']} line(s)")
                A("")
                A(f"- files in the block: "
                  f"{', '.join('`'+x+'`' for x in b['files'])}")
                A(f"- **gold files this block touches:** "
                  f"{', '.join('`'+x+'`' for x in b['gold_files_touched'])}")
                A(f"- gold added-lines reproduced verbatim: "
                  f"**{b['gold_added_lines_reused']}**")
                A("")
            A("## Non-participant-visible context (withheld thread)")
            A("")
            th = issue_thread(tid)
            A(f"Characters: {len(th)}. This thread is **not** shown to "
              f"participants; it is reproduced so you can see the original "
              f"discussion. Flagged blocks above came from here unless the "
              f"field says `problem_statement`.")
            A("")
            A("## Record your verdict")
            A("")
            A(f"```")
            A(f"python tools/adjudicate_leakage.py record {tid} "
              f"--reviewer {reviewer} --answer-leakage <none|minor|major> "
              f"--corrective-repair <yes|no> --conclusion <keep|exclude> "
              f"--reason \"...\"")
            A("```")
            A("")
            open(path, "w", encoding="utf-8", newline="\n").write("\n".join(L))
            written.append(os.path.relpath(path, ROOT))
    print(f"wrote {len(written)} review sheets")
    for w in written:
        print("  ", w)


def cmd_record(a):
    v = load_verdicts()
    v["verdicts"].setdefault(a.task_id, {})
    rec = v["verdicts"][a.task_id].setdefault(a.reviewer, {})
    rec.update({
        "reviewer": a.reviewer,
        "answer_leakage": a.answer_leakage,
        "corrective_repair": a.corrective_repair,
        "build_reproducible": a.build_reproducible,
        "offline_capable": a.offline_capable,
        "estimated_minutes": a.estimated_minutes,
        "external_dependency_risk": a.external_dependency_risk,
        "conclusion": a.conclusion,
        "reason": a.reason,
        "recorded_utc": NOW,
    })
    save_verdicts(v)
    print(f"recorded reviewer {a.reviewer} verdict for {a.task_id}: "
          f"answer_leakage={a.answer_leakage} conclusion={a.conclusion}")


def cmd_status(a):
    data = load_screening()
    v = load_verdicts()["verdicts"]
    todo = [t["task_id"] for t in data["tasks"]
            if t.get("answer_leakage") in ("major", "minor")]
    agree = disagree = pending = arbitrate = 0
    rows = []
    for tid in todo:
        got = v.get(tid, {})
        la = got.get("A", {}).get("answer_leakage")
        lb = got.get("B", {}).get("answer_leakage")
        if not la or not lb:
            pending += 1
            state = f"pending ({'A' if not la else ''}{'B' if not lb else ''})"
        elif la == lb:
            agree += 1
            state = "agree"
        else:
            disagree += 1
            arb = got.get("C", {}).get("answer_leakage")
            if arb:
                state = f"arbitrated -> {arb}"
            else:
                arbitrate += 1
                state = f"NEEDS ARBITRATION (A={la} B={lb})"
        rows.append((tid, state))
    print(f"flagged tasks        : {len(todo)}")
    print(f"  both reviewers done: {agree + disagree}")
    print(f"  pending            : {pending}")
    print(f"  agreement          : {agree}")
    print(f"  disagreement       : {disagree}  (needs third reviewer: {arbitrate})")
    if agree + disagree:
        print(f"  raw agreement rate : "
              f"{agree/(agree+disagree):.2f}")
    print()
    for tid, state in rows:
        print(f"  {tid:52s} {state}")
    return 0


def cmd_summary(a):
    data = load_screening()
    v = load_verdicts()["verdicts"]
    os.makedirs(SCREEN, exist_ok=True)
    L = ["# Answer-leakage screening and adjudication", "",
         f"Generated {NOW}", "",
         "Plan references: 3.1 condition 6, 3.2 (`answer_leakage` field, "
         "two-reviewer screening, third-reviewer arbitration).", "",
         "## Machine screening", "",
         "| verdict | criterion | count |", "|---|---|---:|"]
    crit = data.get("criteria", {})
    dist = data.get("distribution", {})
    for k in ("major", "minor", "none"):
        L.append(f"| `{k}` | {crit.get(k, '')} | {dist.get(k, 0)} |")
    L += ["", "### By split", "",
          "| split | major | minor | none |", "|---|---:|---:|---:|"]
    for sp, c in sorted((data.get("by_split") or {}).items()):
        L.append(f"| {sp} | {c.get('major', 0)} | {c.get('minor', 0)} | "
                 f"{c.get('none', 0)} |")
    L += ["", "## Human adjudication", "",
          "| task | machine | reviewer A | reviewer B | arbitration | conclusion |",
          "|---|---|---|---|---|---|"]
    flagged = [t for t in data["tasks"]
               if t.get("answer_leakage") in ("major", "minor")]
    for t in flagged:
        tid = t["task_id"]
        g = v.get(tid, {})
        L.append(f"| `{tid}` | {t.get('answer_leakage')} | "
                 f"{g.get('A', {}).get('answer_leakage', '')} | "
                 f"{g.get('B', {}).get('answer_leakage', '')} | "
                 f"{g.get('C', {}).get('answer_leakage', '')} | "
                 f"{g.get('C', {}).get('conclusion') or g.get('A', {}).get('conclusion', '')} |")
    done = sum(1 for t in flagged
               if len([r for r in ("A", "B") if v.get(t["task_id"], {}).get(r)]) == 2)
    L += ["", f"**{done}/{len(flagged)} flagged tasks have both reviewer "
              f"verdicts recorded.**" if flagged else
              "No tasks were flagged.", ""]
    p = os.path.join(SCREEN, "adjudication_summary.md")
    open(p, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    print(f"wrote {p}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sheet")
    p.add_argument("--task-id", nargs="*", default=None)
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("record")
    p.add_argument("task_id")
    p.add_argument("--reviewer", required=True, choices=["A", "B", "C"])
    p.add_argument("--answer-leakage", required=True, dest="answer_leakage",
                   choices=["none", "minor", "major"])
    p.add_argument("--corrective-repair", default="", dest="corrective_repair",
                   choices=["", "yes", "no"])
    p.add_argument("--build-reproducible", default="", dest="build_reproducible",
                   choices=["", "yes", "no"])
    p.add_argument("--offline-capable", default="", dest="offline_capable",
                   choices=["", "yes", "no", "partial"])
    p.add_argument("--estimated-minutes", type=int, default=None,
                   dest="estimated_minutes")
    p.add_argument("--external-dependency-risk", default="",
                   dest="external_dependency_risk",
                   choices=["", "low", "medium", "high"])
    p.add_argument("--conclusion", default="", choices=["", "keep", "exclude"])
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("status")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("summary")
    p.set_defaults(fn=cmd_summary)

    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
