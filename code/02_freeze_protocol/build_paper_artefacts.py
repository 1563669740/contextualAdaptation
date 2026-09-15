#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase N -- Artefacts the *paper* requires that the implementation plan implied
but never materialised.

Reading the paper manuscript surfaced seven data requirements that have no
counterpart in the plan document or in what was already collected.  Each is
built here with the paper's own numbers as the acceptance criteria.

  V-A  manipulation check      a task-relevant repository-understanding quiz,
                               administered before and after, whose Chigh-Clow
                               gap is the manipulation check (paper: 8.4 vs 5.9
                               out of 10, difference 2.5, 95% CI 2.21-2.79)
  V-G  semantic review rubric  two blinded reviewers, frozen rubric, items for
                               issue intent / unrelated behaviour change /
                               boundary reasonableness, agreement 88.9% and
                               Cohen's kappa 0.82 (95% CI 0.78-0.86), third
                               reviewer arbitrates
  V-D  freeze record           timestamp, analysis/policy code version,
                               allocation file hash, split manifest, and the
                               anonymised release identifier
  VIII-A online extractor      the runtime signal extractor. The paper is
                               explicit that the held-out policy must NOT read
                               post-hoc human labels, that P1/P3/P4 are
                               deterministic rules over search / diff / test
                               events, and that P2/P5 need a frozen semantic
                               extractor. Extractor-vs-codebook agreement is
                               reported as precision/recall/F1 = 0.86.
  V-H  replayability           per-session state recovery points so a segment
                               can be replayed for stimulated recall
  G    holdout construction log what plan 11.2 requires to be recorded per
                               holdout test, as a machine-readable schema
  V-D  threshold selection     5-fold, repository-grouped cross-validation
                               inside Discovery only, routing agreement primary
                               and unnecessary-escalation secondary

Outputs land under protocol/, policy/, evaluation/ and audit/.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TIFS = r"C:\Users\Administrator\Desktop\TIFS"


def w(rel, obj):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    txt = json.dumps(obj, indent=1, ensure_ascii=False)
    open(p, "w", encoding="utf-8", newline="\n").write(txt + "\n")
    return hashlib.sha256((txt + "\n").encode("utf-8")).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# V-A  manipulation check
# --------------------------------------------------------------------------- #
QUIZ = {
    "schema_version": "1.0",
    "instrument_id": "repository_understanding_v1",
    "paper_reference": "Section V-A 'Manipulation and treatment-fidelity check'",
    "status": "template_frozen_structure_per_task_items_required",
    "frozen_utc": None,
    "why": ("The paper does not only compare outcomes; it first shows the "
            "context manipulation actually took effect. A null result is only "
            "interpretable if we can separate 'context was not manipulated' "
            "from 'context was manipulated but had no effect'."),
    "administration": {
        "when": ["pre_task: BEFORE the participant sees the repository",
                 "post_task: immediately after the session is frozen"],
        "who": "participants who carry a human diagnosis/review duty",
        "note": ("for AI-led sessions the human does not diagnose, so the "
                 "human-side quiz applies to shared-control, human-led and the "
                 "held-out policies that involve human diagnosis; the AI side "
                 "is verified by platform audit of the initial context instead"),
        "scoring": {"total_points": 10, "partial_credit": True},
    },
    "domains": {
        "module_responsibility": {
            "weight": 4,
            "paper_text": "module responsibilities covered",
            "item_template": {
                "id": "mr_{n}",
                "question": ("Which component is responsible for {behaviour}?"),
                "type": "single_choice",
                "options": ["<componentA>", "<componentB>", "<componentC>", "<componentD>"],
                "answer_index": None,
                "points": 2,
                "must_be_answerable_from": ["base_repository", "Chigh_package_only_if_Chigh"],
            },
        },
        "dependency_relations": {
            "weight": 3,
            "paper_text": "dependency relationships covered",
            "item_template": {
                "id": "dr_{n}",
                "question": ("Which module does {component} import or depend on "
                             "when handling {situation}?"),
                "type": "single_choice",
                "options": ["<moduleA>", "<moduleB>", "<moduleC>", "<moduleD>"],
                "answer_index": None,
                "points": 1.5,
                "source": "context_package section 3 (call/dependency graph)",
            },
        },
        "test_structure": {
            "weight": 3,
            "paper_text": "test structure covered",
            "item_template": {
                "id": "ts_{n}",
                "question": ("Where do the tests for {component} live, and how "
                             "are they run?"),
                "type": "single_choice",
                "options": ["<pathA>", "<pathB>", "<pathC>", "<pathD>"],
                "answer_index": None,
                "points": 1.5,
                "note": ("only asks about test LAYOUT and entry points -- never "
                         "about which test targets the defect, which would leak "
                         "the oracle"),
            },
        },
    },
    "per_task_item_authoring": {
        "required_items_per_task": 6,
        "domain_allocation": {"module_responsibility": 2,
                             "dependency_relations": 2,
                             "test_structure": 2},
        "authoring_rule": [
            "items are generated from the base repository and the Chigh package",
            "no item may reference the gold patch, the test patch, FAIL_TO_PASS "
            "or PASS_TO_PASS",
            "an item is admissible only if it is answerable WITHOUT the context "
            "package (otherwise it measures the package, not the repository) and "
            "is answered better WITH it",
            "pre and post versions use the same blueprint with different instances",
        ],
        "leakage_review": "same two-reviewer procedure as the context package",
    },
    "acceptance_criteria": {
        "paper_observed": {"Chigh_mean": 8.4, "Clow_mean": 5.9,
                           "difference": 2.5, "ci95": [2.21, 2.79],
                           "p": "<.001", "scale_max": 10},
        "our_gate": ("report Chigh vs Clow means with a 95% CI; if the "
                     "difference is not positive and materially large the "
                     "context manipulation did not take effect and RQ1 is not "
                     "interpretable"),
        "reporting": ["pre-task means by condition",
                      "post-task means by condition",
                      "within-session change",
                      "difference with 95% CI and test statistic"],
    },
    "ai_side_audit": {
        "paper_text": ("on the AI side, the platform audits the initial context "
                       "to confirm that the package is visible in every Chigh "
                       "session and not visible in Clow"),
        "procedure": [
            "for every session, read provenance_hashes.context_package from session_meta.json",
            "Chigh sessions must carry a non-null hash; Clow sessions must carry none",
            "the first AI prompt of the session must contain the package text in Chigh and must not in Clow",
        ],
        "implemented_by": "tools/audit_context_exposure.py --fill",
    },
}


# --------------------------------------------------------------------------- #
# V-G  semantic review rubric
# --------------------------------------------------------------------------- #
RUBRIC = {
    "schema_version": "1.0",
    "instrument_id": "semantic_review_v1",
    "paper_reference": "Section V-G 'Semantic correctness kept as an independent outcome'",
    "status": "frozen_structure_pending_human_reviewers",
    "frozen_utc": NOW,
    "reviewers": {
        "n": 2,
        "blinding": ["delegation regime", "context condition", "participant identity",
                     "benchmark result", "holdout result"],
        "sees": ["the issue text", "the candidate patch", "the base repository"],
        "arbitration": "a third reviewer resolves disagreements",
        "reliability_target": {"raw_agreement": 0.889, "cohen_kappa": 0.82,
                               "ci95": [0.78, 0.86]},
    },
    "items": [
        {"id": "issue_intent_satisfied", "type": "enum",
         "values": ["yes", "partly", "no"],
         "prompt": ("Does the candidate patch satisfy the intent stated in the "
                    "issue? Answer about behaviour, not about code shape."),
         "weight": "primary"},
        {"id": "unrelated_behaviour_change", "type": "enum",
         "values": ["none", "minor", "major"],
         "prompt": ("Does the patch change behaviour that the issue does not "
                    "concern? Ignore pure refactoring with identical behaviour."),
         "weight": "primary"},
        {"id": "modification_boundary_reasonable", "type": "enum",
         "values": ["yes", "questionable", "no"],
         "prompt": ("Is the set of modified files and functions reasonable for "
                    "the stated problem, or does it reach into unrelated "
                    "subsystems?"),
         "weight": "secondary"},
        {"id": "regression_risk_from_reading", "type": "enum",
         "values": ["low", "medium", "high"],
         "prompt": ("Reading the diff, how likely is it to break existing "
                    "behaviour not covered by the visible tests?"),
         "weight": "secondary"},
        {"id": "would_accept", "type": "boolean",
         "prompt": "Would you merge this patch for this issue?",
         "weight": "primary"},
        {"id": "note", "type": "text", "prompt": "Justify the judgement briefly.",
         "weight": "supporting"},
    ],
    "derived_metrics": {
        "semantic_correct": "issue_intent_satisfied == yes AND unrelated_behaviour_change == none AND would_accept is true",
        "unintended_change": "unrelated_behaviour_change != none",
        "reliability": ("Cohen's kappa over would_accept and over "
                        "issue_intent_satisfied; report raw agreement too"),
    },
    "review_packet_contents": [
        "issue text (participant-visible version, post-redaction)",
        "candidate patch (final.patch from the frozen session)",
        "base repository at base_commit (read-only)",
        "the rubric above",
    ],
    "must_not_contain": ["delegation label", "context label", "participant id",
                         "benchmark_resolved", "holdout results",
                         "gold patch"],
    "outputs": {
        "per_session": "evaluation/<session_id>/semantic_review/reviewer_{A,B}.json",
        "arbitration": "evaluation/<session_id>/semantic_review/arbitration.json",
        "aggregate": "analysis/semantic_review_agreement.json",
    },
}


# --------------------------------------------------------------------------- #
# VIII-A  online extractor
# --------------------------------------------------------------------------- #
EXTRACTOR = {
    "schema_version": "1.0",
    "extractor_id": "online_signal_extractor_v1",
    "paper_reference": "Section VIII-A 'From human-coded concepts to online signals'",
    "status": "TO_BE_FROZEN_BEFORE_HELD_OUT",
    "frozen_utc": None,
    "cardinal_rule": ("the held-out Adaptive Policy must never read post-hoc "
                      "human labels; the extractor consumes ONLY events already "
                      "produced at or before the current instant"),
    "must_not_read": ["holdout tests", "gold patch", "final outcome",
                      "any future event", "post-hoc codebook labels"],
    "windows": {"length_sec": 360, "non_overlapping": True,
                "early_process_sec": 1080,
                "early_process_fraction": 0.24},
    "signals": {
        "P1": {
            "name": "search space expansion",
            "method": "deterministic_rule",
            "inputs": ["search", "open", "read"],
            "outputs": ["candidate_source_set[] per window"],
            "rule": ("fire when |C_k| > |C_(k-1)| > |C_(k-2)| over two "
                     "consecutive windows and no diagnosis note stabilises a "
                     "root cause"),
        },
        "P2": {
            "name": "hypothesis reversal",
            "method": "frozen_semantic_extractor",
            "inputs": ["message", "checkpoint note", "test results"],
            "outputs": ["hypothesis_id", "negated_by_evidence_id"],
            "rule": ("map diagnosis text to a structured hypothesis field using "
                     "the frozen extractor, then count negations; fire at >= 2"),
            "why_semantic": ("negation of a stated hypothesis is not recoverable "
                             "by a deterministic rule over event metadata"),
        },
        "P3": {
            "name": "repair-boundary drift",
            "method": "deterministic_rule",
            "inputs": ["diff", "working_tree_hash", "initial_plan"],
            "outputs": ["planned_components[]", "modified_components[]", "ratio"],
            "rule": ("ratio = |modified source files| / max(1, |planned source "
                     "files|); fire when ratio >= 1.5 OR modified component set "
                     "is not a subset of the planned component set"),
            "ratio_threshold": 1.5,
        },
        "P4": {
            "name": "verification evidence convergence",
            "method": "deterministic_rule",
            "inputs": ["test results", "diff", "module set"],
            "outputs": ["verification_cycles[]"],
            "rule": ("two consecutive verification cycles where the target test "
                     "passes, >= 1 independent visible regression test passes, "
                     "and no new component appears in the diff"),
        },
        "P5": {
            "name": "oracle conflict",
            "method": "frozen_semantic_extractor",
            "inputs": ["issue text", "test outcome", "runtime evidence",
                       "diagnosis text"],
            "outputs": ["conflict_kind", "evidence_refs[]"],
            "rule": ("detect a substantive inconsistency between issue intent, "
                     "visible tests and observed behaviour"),
            "why_semantic": "requires interpreting intent against evidence",
        },
        "P6": {
            "name": "environment / tool instability",
            "method": "deterministic_rule",
            "inputs": ["build/tool error events"],
            "outputs": ["failure_signature"],
            "rule": "two or more failures with the same signature not caused by participant code",
            "in_main_policy": False,
        },
    },
    "validation": {
        "paper_reference": "independent human labels from the frozen codebook on Discovery trajectories not used for rule definition",
        "targets": {"precision": 0.86, "recall": 0.86, "f1": 0.86,
                    "cohen_kappa": 0.86, "per_signal_range": [0.80, 0.91]},
        "sensitivity_analyses": ["high-confidence signal subset",
                                 "human labels substituted offline"],
        "output": "policy/extractor_validation.json",
    },
    "consumer": {
        "policy": "policy/adaptive_policy_v1.json",
        "uses": ["P1", "P2", "P3", "P4", "P5"],
        "excludes": ["P6"],
        "note": ("signals are consumed per decision window; the transition "
                 "decision is evaluated at window boundaries only"),
    },
    "threshold_selection": {
        "paper_reference": "Section VIII-B",
        "where": "Discovery repositories only",
        "scheme": "5-fold cross-validation grouped by repository",
        "primary_criterion": "routing agreement",
        "secondary_criterion": "lower unnecessary-escalation rate",
        "forbidden": "tuning on held-out repositories",
        "frozen_artefact": "policy/threshold_selection.json",
    },
}


# --------------------------------------------------------------------------- #
# V-D  freeze record (paper-shaped) + release identifiers
# --------------------------------------------------------------------------- #
def freeze_record():
    alloc = os.path.join(ROOT, "splits", "allocation_discovery.csv")
    alloc_hash = sha256_file(alloc) if os.path.exists(alloc) else None
    fr = {
        "schema_version": "1.0",
        "paper_reference": "Section III-D 'Frozen record and reproducibility'",
        "why": ("the paper only calls content 'frozen' when it carries a "
                "verifiable timestamp, and its own record names a timestamp, a "
                "code version, an allocation hash and the split manifest"),
        "created_utc": NOW,
        "paper_example": {"timestamp": "2026-05-29 18:00",
                          "policy_analysis_code_version": "1.3.0",
                          "allocation_file_hash": "572641903817",
                          "release_identifier": "20260717-4821"},
        "record": {
            "freeze_timestamp_utc": NOW,
            "policy_analysis_code_version": None,
            "allocation_file": "splits/allocation_discovery.csv",
            "allocation_file_sha256": alloc_hash,
            "split_manifest": "manifests/task_index.json",
            "split_manifest_sha256": sha256_file(
                os.path.join(ROOT, "manifests", "task_index.json")),
            "task_list_hash": sha256_file(
                os.path.join(ROOT, "splits", "discovery_tasks.csv")),
            "randomisation_seed": 20260301,
            "frozen_artefact_tree_digest": None,
            "release_identifier": None,
            "release_url": None,
        },
        "frozen_components": [
            "codebook/codebook_v1.json",
            "policy/adaptive_policy_v1.json",
            "policy/online_extractor_v1.json",
            "policy/threshold_selection.json",
            "protocol/measurements.json",
            "protocol/semantic_review_rubric.json",
            "protocol/repository_understanding_v1.json",
            "splits/allocation_*.csv",
            "splits/randomisation.json",
            "analysis/ (scripts)",
        ],
        "must_be_filled_before_held_out": [
            "policy_analysis_code_version",
            "frozen_artefact_tree_digest (from audit/freeze_manifest.json)",
            "release_identifier and release_url",
        ],
        "paper_statement": ("this paper calls content 'frozen' only when it "
                            "carries a verifiable timestamp, and never "
                            "substitutes post-hoc analysis for the pre-specified "
                            "primary test"),
    }
    return fr


# --------------------------------------------------------------------------- #
# V-H  replayability
# --------------------------------------------------------------------------- #
REPLAY = {
    "schema_version": "1.0",
    "paper_reference": "Section V-H 'To support RQ2, trajectories must also be replayable'",
    "status": "specification",
    "requirement": ("every key modification must have recoverable working-tree "
                    "state, test result and chat context around it"),
    "checkpoints": {
        "trigger": ["before and after every edit that changes a tracked file",
                    "before and after every test command",
                    "at every checkpoint",
                    "at first candidate repair"],
        "recorded_per_checkpoint": {
            "checkpoint_id": "monotonic index",
            "monotonic_ms": "position on the session clock",
            "working_tree_hash": "HEAD + index + hashes of dirty files",
            "diff_ref": "diffs/<n>.patch (git diff --binary)",
            "git_status_ref": "diffs/git_status_<n>.txt",
            "test_ref": "visible_tests/<n>.txt",
            "chat_span": "[first_event_id, last_event_id] covering the context window",
            "actor": "human | AI",
        },
        "storage": "sessions/<session_id>/checkpoints.jsonl",
        "restore_procedure": [
            "git -C <workdir> reset --hard <base_commit>",
            "git -C <workdir> apply --binary diffs/<n>.patch",
            "verify git status matches git_status_<n>.txt and the tree hash matches",
        ],
    },
    "session_summary": {
        "required": True,
        "paper_text": ("all events use a unified event schema and generate a "
                       "session-level summary"),
        "caveat": ("the automatic summary supports retrieval only; qualitative "
                   "coding follows the raw trajectory -- the "
                   "summary is a retrieval index, never the coding input"),
        "fields": ["session_id", "condition", "outcome", "wall_clock_sec",
                   "human_active_sec", "n_events", "per_signal_counts",
                   "checkpoint_decisions", "files_explored", "files_modified",
                   "tests_run", "violations"],
    },
    "recall_linkage": ("stimulated recall transcripts are aligned to event "
                       "timestamps so a quote can be anchored to the checkpoint "
                       "it explains"),
}


# --------------------------------------------------------------------------- #
# G  holdout construction log schema
# --------------------------------------------------------------------------- #
HOLDOUT_LOG = {
    "schema_version": "1.0",
    "paper_reference": "Section V-G 'Construction of the enhanced correctness oracle'",
    "status": "schema_ready_no_tests_authored",
    "authoring_constraints": [
        "author must not have run any session",
        "author must not see any candidate patch or delegation label",
        "author may see the issue, base commit, gold patch and public behaviour constraints",
    ],
    "admission_criteria": [
        "exposes the target defect or related erroneous behaviour at base_commit",
        "passes on the gold patch",
        "deterministic over 5 repeated runs in an isolated environment",
        "not merely a duplicate assertion of an existing benchmark test",
    ],
    "excluded": "tests that repeat a benchmark assertion without adding behaviour coverage",
    "paper_target": {"median_tests_per_task": 4, "iqr": [3, 6]},
    "per_test_record": {
        "holdout_id": "task_id::test_name",
        "task_id": "string",
        "file": "path to the test file or patch",
        "author_pseudonym": "string",
        "authored_utc": "ISO-8601",
        "behaviour_covered": "one sentence, what behaviour this pins down",
        "why_not_duplicate": "how it differs from existing benchmark assertions",
        "base_commit_result": "fail",
        "gold_patch_result": "pass",
        "determinism_runs": 5,
        "determinism_summaries": ["identical summaries across runs"],
        "verified_by": "evaluation/evaluate.py --verify-holdout",
        "admitted": True,
    },
    "per_task_log": "evaluation/holdout_construction_log.json",
    "task_ids_excluded_from_holdout": "string[] with reasons",
}


# --------------------------------------------------------------------------- #
def main():
    hashes = {}
    hashes["repository_understanding"] = w(
        "protocol/repository_understanding_v1.json", QUIZ)
    hashes["semantic_review_rubric"] = w(
        "protocol/semantic_review_rubric.json", RUBRIC)
    hashes["online_extractor"] = w("policy/online_extractor_v1.json", EXTRACTOR)
    hashes["freeze_record"] = w("protocol/freeze_record.json", freeze_record())
    hashes["replay_spec"] = w("protocol/replayability_v1.json", REPLAY)
    hashes["holdout_log_schema"] = w(
        "evaluation/holdout_construction_log.json", HOLDOUT_LOG)
    hashes["threshold_selection"] = w("policy/threshold_selection.json", {
        "schema_version": "1.0",
        "status": "TO_BE_RUN_ON_DISCOVERY",
        "paper_reference": "Section VIII-B",
        "scheme": "5-fold cross-validation grouped by repository",
        "scope": "Discovery repositories only",
        "primary_criterion": "routing agreement",
        "secondary_criterion": "unnecessary escalation rate",
        "forbidden": "any tuning on held-out repositories",
        "frozen_utc": None,
        "selected_thresholds": None,
        "cv_results": None,
        "note": ("routing agreement is a diagnostic of policy behaviour only; "
                 "the paper is explicit that it is NOT the main evidence of "
                 "engineering utility -- that comes from the RQ4 prospective "
                 "sessions"),
    })

    json.dump({"generated_utc": NOW, "artefacts": hashes},
              open(os.path.join(ROOT, "audit", "paper_requirements_hashes.json"),
                   "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    print("built paper-mandated artefacts:")
    for k, v in hashes.items():
        print(f"  {k:28s} {v[:16]}...")


if __name__ == "__main__":
    main()
