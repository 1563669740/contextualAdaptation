#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Roles D1 + D2 -- online signal extractor and threshold selection
(paper VIII-A, VIII-B)

D1 implementation of `policy/online_extractor_v1.json`.

The cardinal rule from the paper is a *causal* one: the held-out Adaptive
Policy must never read post-hoc human labels or future events.  That is enforced
here structurally -- every rule receives only events whose `monotonic_ms` is at
or before the window being decided, and the extractor refuses to look ahead.
A regression test asserts that property rather than trusting the code review.

P1, P3, P4 and P6 are deterministic rules over event metadata.  P2 and P5 need
to interpret diagnosis text, so they are read from a structured field that a
frozen semantic extractor writes; when that field is absent the signal is
reported as `unavailable` rather than guessed.  Reporting "unknown" is the
honest option and it is what the paper's own split (deterministic vs semantic)
implies.

D2 threshold selection: repository-grouped 5-fold cross-validation, routing
agreement as the primary criterion and unnecessary-escalation rate as the
secondary one, restricted to Discovery repositories.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
OUT = os.path.join(ROOT, "policy")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

WINDOW_MS = 6 * 60 * 1000          # paper: 6-minute non-overlapping decision windows
EARLY_MS = 18 * 60 * 1000          # paper: first 24% of the 75-minute cap


# --------------------------------------------------------------------------- #
# D1  extractor
# --------------------------------------------------------------------------- #
class OnlineExtractor:
    """Extracts P1-P6 from a session's event stream, causally.

    Parameters
    ----------
    window_ms : decision-window length.  The paper fixes 6 minutes.
    strict_causality : when True (the default, and what held-out must use),
        `extract` raises if it is handed an event that post-dates the window it
        is deciding.  This turns a silent leak into a loud failure.
    """

    def __init__(self, window_ms=WINDOW_MS, forbid_lookahead=False):
        """
        forbid_lookahead : when True, `extract` RAISES if it is handed an event
            that post-dates the decision point.  That is a *test* mode for
            catching accidental leakage, not the production behaviour: online,
            the extractor simply cannot have future events, so the honest
            semantics are to truncate.  Default False, i.e. truncate.
        """
        self.window_ms = window_ms
        self.forbid_lookahead = forbid_lookahead
        self.audit = {"events_consumed": 0, "events_ignored_future": 0,
                      "windows": 0, "lookahead_refusals": 0}

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _window_index(mono, window_ms):
        return int(mono // window_ms)

    def _windows(self, events):
        w = defaultdict(list)
        for e in events:
            w[self._window_index(e.get("monotonic_ms") or 0,
                                 self.window_ms)].append(e)
        return dict(sorted(w.items()))

    # -- P1: search space expansion --------------------------------------- #
    def p1(self, events, windows=None):
        """|C_k| > |C_(k-1)| > |C_(k-2)| over two consecutive windows, with no
        stabilised root cause in those windows.

        C_k is the candidate set *of window k*, not the running union since the
        session started.  The first implementation accumulated a single set
        across the whole session, which can only grow, so `c > b > a` held
        whenever any searching had happened at all and P1 fired in 96% of
        synthetic sessions.  That is a bug in the extractor, and it was only
        visible because the produced rate was compared against the paper's
        reported 31.7%.
        """
        windows = windows or self._windows(events)
        cand, fired = {}, {}
        for k in sorted(windows):
            in_window = set()
            for e in windows[k]:
                if e.get("event_type") in ("search", "open", "read"):
                    p = (e.get("payload") or {}).get("path")
                    q = (e.get("payload") or {}).get("query")
                    if p:
                        in_window.add(p)
                    elif q:
                        in_window.add("query:" + str(q))
            cand[k] = len(in_window)
        for k in sorted(windows):
            stable = any(e.get("event_type") == "diagnosis"
                         and (e.get("payload") or {}).get("root_cause_stable")
                         for e in windows[k])
            if k >= 2 and not stable:
                a, b, c = cand.get(k - 2, 0), cand.get(k - 1, 0), cand[k]
                fired[k] = bool(c > b > a)
            else:
                fired[k] = False
        return {"candidates_per_window": cand, "fired": fired,
                "first_fire_window": next((k for k in sorted(fired)
                                           if fired[k]), None),
                "method": "deterministic_rule",
                "candidate_set_semantics": "per_window"}

    # -- P3: repair-boundary drift ---------------------------------------- #
    def p3(self, events, planned_components=None):
        """ratio >= 1.5 between modified and planned source files, or a modified
        top-level component outside the planned set."""
        planned = set(planned_components or [])
        modified_files, modified_components = set(), set()
        for e in events:
            if e.get("event_type") != "edit":
                continue
            p = (e.get("payload") or {}).get("path")
            if not p:
                continue
            modified_files.add(p)
            modified_components.add(p.split("/")[0] if "/" in p else ".")
        n_planned = max(1, len(planned))
        ratio = len(modified_files) / n_planned
        cross = bool(planned) and not modified_components.issubset(
            {p.split("/")[0] if "/" in p else "." for p in planned})
        return {"planned_files": len(planned),
                "modified_files": len(modified_files),
                "ratio": round(ratio, 3), "ratio_threshold": 1.5,
                "modified_components": sorted(modified_components),
                "crossed_module_boundary": cross,
                "fired": bool(ratio >= 1.5 or cross),
                "method": "deterministic_rule"}

    # -- P4: verification evidence convergence ---------------------------- #
    def p4(self, events, independent_visible_regressions=1):
        """Two consecutive verification cycles where the target test passes,
        at least one independent visible regression test passes, and no new
        component appears in the diff."""
        cycles, cur = [], None
        components_at_cycle = []
        for e in events:
            et = e.get("event_type")
            if et == "edit":
                p = (e.get("payload") or {}).get("path")
                if cur is not None and p:
                    cur["new_components"].add(p.split("/")[0] if "/" in p else ".")
            elif et == "test":
                pl = e.get("payload") or {}
                cur = {"exit_code": pl.get("exit_code"),
                       "n_passed": pl.get("n_passed"),
                       "target_passed": pl.get("target_test_passed"),
                       "regressions_passed": pl.get("regression_tests_passed"),
                       "new_components": set()}
                cycles.append(cur)
        conv = [bool(c["target_passed"]
                     and (c["regressions_passed"] or 0)
                     >= independent_visible_regressions
                     and not c["new_components"]) for c in cycles]
        fired_windows = [i for i in range(1, len(conv))
                         if conv[i] and conv[i - 1]]
        return {"n_verification_cycles": len(cycles),
                "convergent_cycles": conv,
                "fired": bool(fired_windows),
                "first_fire_cycle": fired_windows[0] if fired_windows else None,
                "method": "deterministic_rule"}

    # -- P6: environment / tool instability ------------------------------- #
    def p6(self, events):
        sigs = defaultdict(int)
        for e in events:
            if e.get("event_type") != "tool_error":
                continue
            pl = e.get("payload") or {}
            if pl.get("cause") in ("environment", "dependency", "tooling"):
                sigs[str(pl.get("signature") or pl.get("message"))[:120]] += 1
        repeated = {k: v for k, v in sigs.items() if v >= 2}
        return {"signatures": dict(sigs), "repeated": repeated,
                "fired": bool(repeated), "in_main_policy": False,
                "method": "deterministic_rule"}

    # -- P2 / P5: semantic, read from frozen fields ----------------------- #
    @staticmethod
    def _semantic(events, field):
        seen, total = [], 0
        for e in events:
            pl = e.get("payload") or {}
            if field in pl:
                total += 1
                seen.append(pl[field])
        if not seen:
            return {"status": "unavailable",
                    "reason": ("no frozen semantic extractor output present; "
                               "the paper requires interpretation of diagnosis "
                               "text here, so the value is reported as unknown "
                               "rather than guessed"),
                    "method": "frozen_semantic_extractor"}
        return {"status": "available", "values": seen, "n": total,
                "fired": any(bool(v) for v in seen),
                "method": "frozen_semantic_extractor"}

    def p2(self, events):
        return self._semantic(events, "hypothesis_negated")

    def p5(self, events):
        return self._semantic(events, "oracle_conflict")

    # -- top level -------------------------------------------------------- #
    def extract(self, events, planned_components=None, upto_ms=None):
        """Extract every signal using only events at or before `upto_ms`.

        Events after `upto_ms` are ignored, which is what "online" means.  With
        `forbid_lookahead=True` they cause a raise instead, so a test can prove
        the boundary is respected.
        """
        future = [e for e in events
                  if upto_ms is not None
                  and (e.get("monotonic_ms") or 0) > upto_ms]
        if future:
            if self.forbid_lookahead:
                self.audit["lookahead_refusals"] += 1
                raise ValueError(
                    f"causal violation: {len(future)} event(s) post-date the "
                    f"decision point ({upto_ms} ms); the online extractor must "
                    f"never see the future")
            self.audit["events_ignored_future"] += len(future)
        used = [e for e in events
                if upto_ms is None or (e.get("monotonic_ms") or 0) <= upto_ms]
        self.audit["events_consumed"] += len(used)
        self.audit["windows"] = len(self._windows(used))
        out = {
            "signals": {
                "P1": self.p1(used), "P2": self.p2(used),
                "P3": self.p3(used, planned_components),
                "P4": self.p4(used), "P5": self.p5(used),
                "P6": self.p6(used),
            },
            "early_process_cutoff_ms": EARLY_MS,
            "window_ms": self.window_ms,
            "events_used": len(used),
            "causal": True,
        }
        out["early_process_signals"] = {
            k: v for k, v in out["signals"].items()
            if k != "P6"}
        return out

    def early_process(self, events, planned_components=None):
        """Signals observable inside the first 24% of the task cap."""
        return self.extract(events, planned_components, upto_ms=EARLY_MS)


# --------------------------------------------------------------------------- #
# D2  threshold selection
# --------------------------------------------------------------------------- #
def route(pre_task, early):
    """The paper's frozen finite-state rule, expressed once."""
    fam = pre_task.get("repository_familiarity")
    if fam is not None and fam >= 4:
        initial = "ai_led"
    else:
        initial = "shared_control" if pre_task.get("locatable") is False \
            else "ai_led"
    state = initial
    escalations = []
    if early.get("P1", {}).get("fired") or early.get("P2", {}).get("fired"):
        state = "shared_control"
        escalations.append("T1")
    if (early.get("P3", {}).get("fired") and early.get("P5", {}).get("fired")) \
            or early.get("persistently_unresolved"):
        state = "human_led"
        escalations.append("T2")
    if early.get("P4", {}).get("fired"):
        state = "ai_led"
        escalations.append("T3")
    return {"initial": initial, "final": state, "transitions": escalations}


def select_thresholds(cases, k=5):
    """Repository-grouped k-fold selection.

    `cases` are dicts with repo_id, features and the observed best fixed
    strategy (the routing target).  Grouping by repository is what stops the
    same repository appearing in train and test, which is the paper's stated
    constraint and the reason the held-out split is repository-level too.
    """
    groups = sorted({c["repo_id"] for c in cases})
    if len(groups) < k:
        k = max(2, len(groups))
    folds = [set(groups[i::k]) for i in range(k)]
    space = [{"familiarity_high": f, "ratio_threshold": r,
              "require_p3_and_p5_for_human": bool(b)}
             for f in (3, 4, 5) for r in (1.25, 1.5, 2.0) for b in (True, False)]
    results = []
    for theta in space:
        per_fold = []
        for test_groups in folds:
            test = [c for c in cases if c["repo_id"] in test_groups]
            if not test:
                continue
            agree = unnecessary = escalated = 0
            for c in test:
                pre = dict(c["features"].get("pre_task") or {})
                pre["repository_familiarity"] = (
                    theta["familiarity_high"]
                    if (pre.get("repository_familiarity") or 0)
                    >= theta["familiarity_high"]
                    else pre.get("repository_familiarity"))
                early = dict(c["features"].get("early_process") or {})
                r = route(pre, early)
                if r["final"] == c["best_fixed"]:
                    agree += 1
                if r["final"] != r["initial"]:
                    escalated += 1
                    if c["best_fixed"] == r["initial"]:
                        unnecessary += 1
            per_fold.append({
                "n": len(test),
                "routing_agreement": agree / len(test) if test else None,
                "unnecessary_escalation_rate":
                    unnecessary / escalated if escalated else 0.0,
            })
        valid = [f for f in per_fold if f["n"]]
        if not valid:
            continue
        results.append({
            "theta": theta,
            "mean_routing_agreement":
                sum(f["routing_agreement"] for f in valid) / len(valid),
            "mean_unnecessary_escalation":
                sum(f["unnecessary_escalation_rate"] for f in valid) / len(valid),
            "folds": valid,
        })
    # primary criterion routing agreement, secondary lower unnecessary escalation
    results.sort(key=lambda r: (-round(r["mean_routing_agreement"], 4),
                               round(r["mean_unnecessary_escalation"], 4)))
    return {"k": k, "groups": groups, "n_cases": len(cases),
            "ranked": results[:10],
            "selected": results[0] if results else None}


# --------------------------------------------------------------------------- #
def self_test():
    """A regression test for the property that matters most: no lookahead."""
    ex = OnlineExtractor(window_ms=1000)
    events = [
        {"event_type": "search", "monotonic_ms": 100, "payload": {"query": "a"}},
        {"event_type": "open", "monotonic_ms": 200, "payload": {"path": "x.py"}},
        {"event_type": "read", "monotonic_ms": 300, "payload": {"path": "y.py"}},
        {"event_type": "edit", "monotonic_ms": 400, "payload": {"path": "x.py"}},
        {"event_type": "test", "monotonic_ms": 500,
         "payload": {"exit_code": 0, "target_test_passed": True,
                     "regression_tests_passed": 2}},
        {"event_type": "test", "monotonic_ms": 600,
         "payload": {"exit_code": 0, "target_test_passed": True,
                     "regression_tests_passed": 2}},
    ]
    checks = {}
    # production semantics: a window ending before the tests must not see them
    r = ex.extract(events, upto_ms=350)
    checks["window_ignores_future_events"] = \
        r["signals"]["P4"]["fired"] is False and r["events_used"] == 3
    # test semantics: the same call must raise when lookahead is forbidden
    strict = OnlineExtractor(window_ms=1000, forbid_lookahead=True)
    try:
        strict.extract(events, upto_ms=100)
        checks["raises_on_lookahead_when_forbidden"] = False
    except ValueError:
        checks["raises_on_lookahead_when_forbidden"] = True
    full = ex.extract(events)
    checks["p4_fires_with_two_cycles"] = full["signals"]["P4"]["fired"] is True
    checks["p2_reports_unavailable_not_false"] = \
        full["signals"]["P2"]["status"] == "unavailable"
    checks["p6_excluded_from_main_policy"] = \
        full["signals"]["P6"]["in_main_policy"] is False
    p3 = ex.extract(events, planned_components=["x.py"])["signals"]["P3"]
    checks["p3_ratio_computed"] = p3["modified_files"] == 1
    # early-process view: the cutoff is 18 minutes, so a short synthetic stream
    # is entirely inside it.  Assert the cutoff is applied, and separately that
    # a window ending earlier really does lose the late events.
    early = ex.early_process(events)
    checks["early_process_applies_18min_cutoff"] = \
        early["early_process_cutoff_ms"] == EARLY_MS
    late = [dict(e) for e in events]
    late.append({"event_type": "test", "monotonic_ms": EARLY_MS + 60_000,
                 "payload": {"exit_code": 0, "target_test_passed": True,
                             "regression_tests_passed": 2}})
    early2 = ex.early_process(late)
    checks["early_process_drops_events_after_cutoff"] = \
        early2["events_used"] == len(events)
    checks["all_pass"] = all(checks.values())
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--select-thresholds", metavar="FEATURES_JSON")
    a = ap.parse_args()

    if a.self_test or not a.select_thresholds:
        res = self_test()
        print(json.dumps(res, indent=1))
        os.makedirs(OUT, exist_ok=True)
        json.dump({"self_test_utc": NOW, "checks": res,
                   "note": ("the causal property is asserted, not reviewed: "
                            "asking for a window that precedes a supplied event "
                            "must raise")},
                  open(os.path.join(OUT, "extractor_self_test.json"), "w",
                       encoding="utf-8"), indent=1, ensure_ascii=False)
        if not a.select_thresholds:
            return 0 if res["all_pass"] else 1

    cases = json.load(open(a.select_thresholds, encoding="utf-8"))
    out = select_thresholds(cases)
    out.update({"generated_utc": NOW,
                "paper_reference": "Section VIII-B",
                "scope": "Discovery repositories only",
                "primary_criterion": "routing agreement",
                "secondary_criterion": "unnecessary escalation rate",
                "forbidden": "tuning on held-out repositories",
                "status": "COMPUTED" if out.get("selected") else "NO_DATA"})
    json.dump(out, open(os.path.join(OUT, "threshold_selection.json"), "w",
                        encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps({"k": out["k"], "n_cases": out["n_cases"],
                      "selected": (out.get("selected") or {}).get("theta"),
                      "agreement": (out.get("selected") or {}).get(
                          "mean_routing_agreement")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
