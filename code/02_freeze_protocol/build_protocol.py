#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase E -- Protocol, codebook, policy and model manifests (plan 7, 9, 10, 11, 14)

Everything in this file is a *frozen definition*: the delegation-regime rules,
the event schema, the P1-P6 process signals, the Adaptive Policy thresholds and
the measurement definitions.  They are transcribed from the approved plan
document and written once so that M4 ("freeze codebook / extractor / policy /
thresholds") is a hash comparison rather than an argument.

The point of freezing these before data collection is plan 14: the online
extractor and the policy state machine must not be re-tuned after any result is
observed, and held-out must run against the frozen definitions only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
PROTO = os.path.join(ROOT, "protocol")
CODEBOOK = os.path.join(ROOT, "codebook")
POLICY = os.path.join(ROOT, "policy")
MANIFESTS = os.path.join(ROOT, "manifests")
AUDIT = os.path.join(ROOT, "audit")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SESSION_CAP_MIN = 75
WINDOW_MIN = 6
EARLY_FRACTION = 0.24          # first 18 min of a 75 min cap
FAMILIARITY_HIGH = 4           # >= 4/5 is high familiarity


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
PROTOCOL_MD = f"""# Frozen experiment protocol

Generated: {NOW}
Source: 《无Docker_论文复现实验数据采集实施方案》v1.0
Status: **frozen** — changes after the first formal session require a documented
protocol amendment and invalidate affected sessions.

## 1. Design

| Factor | Levels | Notes |
|---|---|---|
| Context availability | `Clow` (Cold-Thin), `Chigh` (Context-Enriched) | between-task manipulation |
| Delegation regime | `AI-led`, `Shared-control`, `Human-led` | the experimental treatment |
| Split | pilot / discovery / held-out | repository-level isolation |
| Session cap | {SESSION_CAP_MIN} minutes, hard | enforced in the runner |

Discovery: 120 tasks x 3 regimes = 360 sessions, all six
Context x Delegation cells exactly 60 (see `splits/allocation_report.json`).

Held-out: 72 tasks x 5 policies = 360 sessions; context balanced 36/36 inside
every policy.

## 2. What each condition may see

| | Clow | Chigh |
|---|---|---|
| Issue text (problem statement) | yes | yes |
| Base repository at `base_commit` | yes | yes |
| Standard development tools | yes | yes |
| Search / read code / run visible tests | yes | yes |
| `context_packages/<task_id>.md` | **no** | yes (per regime permissions) |

Never visible in either condition, to human or agent: gold patch, benchmark test
patch, `FAIL_TO_PASS` / `PASS_TO_PASS` lists, holdout tests, semantic review.

Context-preparation time under Chigh is recorded separately and is **not** part
of task-phase human active time.

## 3. Delegation regimes

### 3.1 AI-led
| Phase | Control |
|---|---|
| Locate / diagnose | AI autonomous; human does not intervene in real time |
| Repair plan | AI decides autonomously |
| Edit and test | AI edits, selects and runs tests autonomously |
| Final authority | AI finishes within budget and submits; human evaluates only afterwards |

Runner enforcement: the interface must **not accept** human correction messages
during the session. Any attempt is logged as `protocol_violation`.

### 3.2 Shared-control
| Phase | Control |
|---|---|
| Locate / diagnose | AI explores first; a **diagnosis checkpoint** must be reviewed and corrected by the human |
| Repair plan | AI proposes; human approves or modifies |
| Edit and test | AI executes the approved plan; contradictions or failures may trigger extra checks |
| Final authority | three standard checkpoints: diagnosis, plan, final patch |

Runner enforcement: the session cannot advance past a checkpoint without a
recorded human decision (`approve` / `modify` / `reject`).

### 3.3 Human-led
| Phase | Control |
|---|---|
| Locate / diagnose | human leads |
| Root-cause judgement | human decides |
| Repair plan | human decides |
| Edit and test | human edits, or delegates narrowly-scoped local edits to AI |
| Final authority | human decides next step and stopping condition |

Runner enforcement: end-to-end handover to AI (`take over the whole task`) is
**rejected**. Only bounded local requests are accepted, each recorded with its
scope. Violations are logged as `protocol_violation`.

## 4. Session SOP (plan 8)

1. Check-in and background check (incl. pre-task repository familiarity)
2. Restore environment from the clean task snapshot; verify `base_commit`,
   `env_hash`, empty `git status`
3. Condition preparation (Chigh package load, separately timed)
4. Start logging: session clock, terminal capture, AI gateway, IDE file events,
   resource monitor; write `session_start.json`
5. Task start: formal timing begins at the frozen `base_commit`
6. Continuous recording into `events.jsonl`
7. Stop condition: participant declares done, agent declares done, budget
   exhausted, or {SESSION_CAP_MIN} min reached — whichever comes first
8. Result freeze: final worktree, candidate patch, visible test log, full
   trajectory, environment fingerprint, file hashes; session data is immutable
   afterwards
9. Hidden evaluation in an independent clean workspace
10. Post-task questionnaire
11. Stimulated recall for the RQ2 theoretical sample only

Steps 2 and 9 must run in a workspace with **no state shared** with the previous
session. `git reset --hard` alone is insufficient; use a snapshot/clone.

## 5. Stop conditions
- participant declares completion
- agent declares completion (AI-led / Shared-control)
- budget exhausted
- {SESSION_CAP_MIN} minutes of wall clock in the task phase

## 6. Treatment fidelity
- permission-level blocking, not instruction-level requests
- `protocol_violation` recorded per session with the specific event ids
- violation handling frozen here, before held-out: a session with a
  `protocol_violation` is retained but flagged, and is included in a
  pre-registered sensitivity analysis excluding flagged sessions
"""


EVENT_SCHEMA = {
    "schema_version": "1.0",
    "frozen_utc": NOW,
    "format": "JSONL, one event per line, appended in monotonic order",
    "timestamps": {
        "timestamp_utc": "wall clock, ISO-8601 Z, for cross-source merging",
        "monotonic_ms": "milliseconds since session_start; immune to clock drift",
    },
    "required_fields": [
        "session_id", "event_id", "timestamp_utc", "monotonic_ms", "actor",
        "event_type", "payload", "source",
    ],
    "recommended_fields": [
        "working_tree_hash", "visible_to_human", "visible_to_ai",
    ],
    "actors": ["human", "AI", "system", "evaluator"],
    "event_types": {
        "session_start": "clock start; payload carries condition + manifest hashes",
        "session_end": "clock stop; payload carries stop_reason",
        "message": "chat / utterance; payload carries text and channel",
        "tool_call": "agent tool invocation; payload carries name, args, result",
        "shell": "terminal command; payload carries command, exit_code, stdout_ref",
        "search": "code or text search; payload carries query and scope",
        "open": "file opened in the IDE; payload carries path",
        "read": "file read; payload carries path and line range",
        "edit": "file modification; payload carries path and diff_ref",
        "diff": "worktree diff snapshot; payload carries diff_ref and hash",
        "test": "test execution; payload carries command, exit_code, summary",
        "checkpoint": "Shared-control gate; payload carries checkpoint, decision, note",
        "context_load": "Chigh package exposure; payload carries package hash",
        "delegation_request": "Human-led bounded AI request; payload carries scope",
        "protocol_violation": "attempted action blocked by the runner",
        "freeze": "session data frozen; payload carries artefact hashes",
    },
    "example": [
        {"session_id": "D-S0001", "event_id": 1,
         "timestamp_utc": "2026-09-14T09:00:00.000Z", "monotonic_ms": 0,
         "actor": "system", "event_type": "session_start",
         "payload": {"task_id": "T001", "base_commit": "..."},
         "source": "runner"},
        {"session_id": "D-S0001", "event_id": 2,
         "timestamp_utc": "2026-09-14T09:00:15.320Z", "monotonic_ms": 15320,
         "actor": "AI", "event_type": "search",
         "payload": {"query": "symbol_name", "scope": "repo"},
         "source": "ai_gateway"},
        {"session_id": "D-S0001", "event_id": 3,
         "timestamp_utc": "2026-09-14T09:01:01.422Z", "monotonic_ms": 61422,
         "actor": "human", "event_type": "checkpoint",
         "payload": {"checkpoint": "diagnosis", "decision": "modify",
                     "note": "..."},
         "source": "checkpoint_cli"},
    ],
    "integrity": {
        "heartbeat_event_type": "logger_heartbeat",
        "heartbeat_interval_sec": 30,
        "gap_detection": ("a gap longer than 120 s with no event of any source "
                          "marks the session for logger_health review"),
    },
}


CODEBOOK_SPEC = {
    "version": "1.0",
    "frozen_utc": NOW,
    "purpose": ("confirmatory replication of the paper's process signals; "
                "coder must NOT be told the P1-P5 labels when doing a "
                "discovery-style RQ2 (plan 10 preamble)"),
    "signals": {
        "P1": {
            "name": "search space expansion",
            "frozen_definition": ("in 2 consecutive {w}-minute decision windows "
                                  "the set of candidate source files/modules "
                                  "keeps growing and the root cause has not "
                                  "stabilised").format(w=WINDOW_MIN),
            "required_events": ["search", "open", "read", "diagnosis_note"],
            "decision_rule": (
                "window_k candidate set C_k; P1 fires when "
                "|C_k| > |C_(k-1)| > |C_(k-2)| over two consecutive windows "
                "AND no diagnosis note in those windows names a stable root "
                "cause"),
            "window_sec": WINDOW_MIN * 60,
        },
        "P2": {
            "name": "hypothesis reversal",
            "frozen_definition": ("the root-cause hypothesis is negated by "
                                  "later evidence at least twice, each time "
                                  "producing a new search or edit direction"),
            "required_events": ["diagnosis text", "contradicting evidence",
                                "subsequent action"],
            "decision_rule": ("count windows in which a previously stated "
                              "hypothesis is contradicted by test output, a "
                              "read result or a failing repro; P2 fires at "
                              "count >= 2"),
        },
        "P3": {
            "name": "repair-boundary drift",
            "frozen_definition": ("modified source files / initially planned "
                                  "source files >= 1.5, OR edits cross an "
                                  "original top-level module boundary"),
            "required_events": ["initial_plan", "realtime diff", "module set"],
            "decision_rule": ("ratio = |modified source files| / "
                              "max(1, |planned source files|); fires when "
                              "ratio >= 1.5 or the top-level component set of "
                              "modified files is not a subset of the planned "
                              "component set"),
            "ratio_threshold": 1.5,
        },
        "P4": {
            "name": "verification evidence convergence",
            "frozen_definition": ("over 2 consecutive verification cycles the "
                                  "target test plus at least one independent "
                                  "visible regression test support the same "
                                  "causal hypothesis, with no newly affected "
                                  "module"),
            "required_events": ["test results", "diagnosis", "module set"],
            "decision_rule": ("two consecutive verification cycles where the "
                              "target test passes AND >=1 independent visible "
                              "regression test passes AND no new component "
                              "appears in the diff"),
        },
        "P5": {
            "name": "oracle conflict",
            "frozen_definition": ("substantive inconsistency between the "
                                  "issue's stated intent, the visible tests, "
                                  "and the observed runtime behaviour"),
            "required_events": ["issue statement", "test outcome",
                                "runtime evidence", "diagnosis"],
            "decision_rule": ("a window where the participant records that the "
                              "issue intent and the visible tests cannot both "
                              "be satisfied, or that observed behaviour "
                              "contradicts the issue text"),
        },
        "P6": {
            "name": "environment / tool instability",
            "frozen_definition": ("non-code build or tool failures recur; an "
                                  "infrastructure variable only, excluded from "
                                  "the main policy"),
            "required_events": ["build/tool error events"],
            "decision_rule": ("two or more failures with the same signature "
                              "whose cause is not participant code"),
            "excluded_from_policy": True,
        },
    },
    "coding": {
        "unit": "session",
        "granularity": "decision window",
        "window_sec": WINDOW_MIN * 60,
        "non_overlapping": True,
        "reliability": ("two independent coders on a 20% random sample; "
                        "report Cohen's kappa per signal; disagreements "
                        "adjudicated by a third coder"),
    },
}


POLICY_SPEC = {
    "version": "1.0",
    "frozen_utc": NOW,
    "name": "Adaptive Policy",
    "frozen_before": "held-out data collection (plan 14)",
    "thresholds": {
        "pre_task_familiarity_high": FAMILIARITY_HIGH,
        "familiarity_scale_max": 5,
        "process_window_sec": WINDOW_MIN * 60,
        "early_process_fraction": EARLY_FRACTION,
        "early_process_sec": int(round(SESSION_CAP_MIN * 60 * EARLY_FRACTION)),
        "session_cap_sec": SESSION_CAP_MIN * 60,
    },
    "transitions": [
        {"when": "P1 or P2 observed",
         "action": "escalate to shared_control",
         "id": "T1"},
        {"when": ("P3 and P5 co-occur, OR after escalation any of P1-P3 "
                  "persists for 2 consecutive windows without resolving"),
         "action": "escalate to human_led",
         "id": "T2"},
        {"when": "P4 observed",
         "action": "permit return to AI execution",
         "id": "T3"},
    ],
    "observable_inputs": ["P1", "P2", "P3", "P4", "P5"],
    "excluded_inputs": ["P6"],
    "initial_regime": "ai_led",
    "state_machine": {
        "states": ["ai_led", "shared_control", "human_led"],
        "monotonic_upward": ["ai_led -> shared_control", "shared_control -> human_led"],
        "allowed_downward": ["shared_control -> ai_led", "human_led -> ai_led"],
        "downward_condition": "T3 (P4 observed)",
        "note": ("T3 is the only downward transition; it returns to AI "
                 "execution, and T1/T2 may re-escalate"),
    },
    "evaluation": {
        "comparison": ["always_ai_led", "always_shared_control",
                       "always_human_led", "developer_ad_hoc",
                       "adaptive_policy"],
        "prospective": True,
        "must_not_be_tuned_after_heldout_begins": True,
    },
}


MODEL_MANIFEST = {
    "schema_version": "1.0",
    "frozen_utc": NOW,
    "status": "TO_BE_COMPLETED_BEFORE_FIRST_SESSION",
    "required_fields": [
        "model_snapshot", "agent_version", "reasoning_level",
        "tool_config_hash", "gateway_version", "temperature", "max_tokens",
        "request_identifier_scheme", "cost_accounting",
    ],
    "note": ("plan 9.1: every model call must pass through one gateway that "
             "records the full prompt, response, tool trace, model snapshot, "
             "reasoning level, request id and token/cost. Fill this in and "
             "hash it before the first formal session; it is part of M0."),
    "values": {
        "model_snapshot": None,
        "agent_version": None,
        "reasoning_level": None,
        "tool_config_hash": None,
        "gateway_version": None,
        "temperature": None,
        "max_tokens": None,
    },
}


ENV_SPEC = {
    "schema_version": "1.0",
    "frozen_utc": NOW,
    "docker_used": False,
    "replication_character": "non-containerized replication / infrastructure adaptation",
    "threat_to_validity": ("the paper used a reproducible Docker environment; "
                           "this replication does not, so the execution "
                           "environment is not identical to the original and "
                           "must be reported as a separate validity threat"),
    "isolation_model": {
        "recommended": ("fixed Linux VM base image + per-task snapshot/clone + "
                        "git worktree + language-level virtualenv"),
        "fallback": "bare metal with per-session workspace and language env",
        "per_task_workspace": True,
        "no_global_installs": True,
        "reset_after_session": ["kill session processes",
                                "snapshot the worktree",
                                "git reset --hard && git clean -fdx",
                                "delete the task virtualenv / node_modules"],
    },
    "fingerprint_fields": [
        "uname_or_os_build", "kernel", "cpu_model", "cpu_cores", "ram_gb",
        "disk_fs", "python_version", "pip_freeze_sha256", "node_version",
        "package_manager", "java_version", "rust_version", "go_version",
        "locale", "timezone", "path_sanitised", "git_version",
        "gcc_version", "clang_version", "service_versions",
    ],
    "hash_targets": [
        "lockfiles", "runner", "context_package", "allocation",
        "evaluation_harness", "model_manifest", "policy", "codebook",
    ],
    "network_policy": {
        "setup": "allow-package-mirrors",
        "task": "deny-external-by-default",
    },
    "resource_limits": {"cpu": 4, "memory_gb": 8, "disk_gb": 30},
}


def main():
    for d in (PROTO, CODEBOOK, POLICY, MANIFESTS, AUDIT):
        os.makedirs(d, exist_ok=True)
    h = {}
    h["protocol"] = w(os.path.join(PROTO, "protocol_v1.md"), PROTOCOL_MD)
    h["event_schema"] = w(os.path.join(PROTO, "event_schema.json"),
                          json.dumps(EVENT_SCHEMA, indent=1, ensure_ascii=False))
    h["delegation_regimes"] = w(
        os.path.join(PROTO, "delegation_regimes.json"),
        json.dumps({
            "frozen_utc": NOW,
            "regimes": {
                "ai_led": {
                    "label": "AI-led",
                    "human_realtime_intervention": False,
                    "runtime_enforced": True,
                    "enforcement": ["human correction messages rejected",
                                    "no checkpoint gates"],
                    "final_authority": "AI",
                },
                "shared_control": {
                    "label": "Shared-control",
                    "checkpoints": ["diagnosis", "plan", "final_patch"],
                    "checkpoint_decisions": ["approve", "modify", "reject"],
                    "runtime_enforced": True,
                    "enforcement": ["cannot advance past a checkpoint without a "
                                    "recorded human decision"],
                    "final_authority": "human approves, AI executes",
                },
                "human_led": {
                    "label": "Human-led",
                    "end_to_end_ai_takeover": False,
                    "runtime_enforced": True,
                    "enforcement": ["takeover requests rejected",
                                    "each delegated edit recorded with a scope"],
                    "final_authority": "human",
                },
            },
        }, indent=1, ensure_ascii=False))
    h["codebook"] = w(os.path.join(CODEBOOK, "codebook_v1.json"),
                      json.dumps(CODEBOOK_SPEC, indent=1, ensure_ascii=False))
    h["policy"] = w(os.path.join(POLICY, "adaptive_policy_v1.json"),
                    json.dumps(POLICY_SPEC, indent=1, ensure_ascii=False))
    h["model_manifest"] = w(os.path.join(MANIFESTS, "model_manifest.json"),
                            json.dumps(MODEL_MANIFEST, indent=1,
                                       ensure_ascii=False))
    h["environment_spec"] = w(os.path.join(MANIFESTS, "environment_spec.json"),
                              json.dumps(ENV_SPEC, indent=1, ensure_ascii=False))

    # measurement definitions (plan 11.3)
    h["measurement"] = w(os.path.join(PROTO, "measurements.json"),
                         json.dumps({
                             "frozen_utc": NOW,
                             "metrics": {
                                 "wall_clock_time": "formal task start to result freeze; excludes pre-task context building",
                                 "human_active_time": "reading, typing, reviewing, editing, deciding after task start",
                                 "context_preparation_time": "Chigh pre-task package reading and warm-up; reported separately",
                                 "ai_execution_time": "model/agent execution time",
                                 "api_cost": "tokens and cost",
                                 "Tinitial": "task start to first candidate repair",
                                 "Tinspection": "human active time inspecting candidate repairs",
                                 "Trework": "extra repair activity caused by error, regression or uncertainty",
                                 "interaction_count": "number of human-AI interactions",
                                 "checkpoint_wait": "time waiting at checkpoints",
                                 "files_explored": "distinct files opened/read",
                                 "files_modified": "distinct files edited",
                                 "tests_run": "test commands executed",
                             },
                             "aggregation_warning": ("Tinitial, Tinspection and "
                                                     "Trework are activity "
                                                     "measures that may overlap "
                                                     "in time and must NOT be "
                                                     "summed as wall clock"),
                             "correctness": {
                                 "benchmark_resolved": "all fail_to_pass pass AND all pass_to_pass still pass",
                                 "enhanced_resolved": "benchmark resolved AND all independent holdout tests pass",
                                 "semantic_correctness": "blind review: patch satisfies issue intent with no unrelated behaviour change",
                                 "regression_count": "count of failing pre-existing or new regression tests",
                                 "unintended_change": "blind-review-detected behaviour change unrelated to the issue",
                             },
                             "notes": ("enhanced_resolved deliberately does "
                                       "NOT use gold-patch similarity"),
                         }, indent=1, ensure_ascii=False))

    json.dump({"frozen_utc": NOW, "artefacts": h},
              open(os.path.join(AUDIT, "protocol_hashes.json"), "w",
                   encoding="utf-8"), indent=1, ensure_ascii=False)

    print("frozen protocol artefacts:")
    for k, v in h.items():
        print(f"  {k:22s} {v[:16]}...")


if __name__ == "__main__":
    main()
