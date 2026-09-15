# Contents

Generated 2026-09-15. Measured with `git ls-files -o --exclude-standard`.

## Summary

| | Files | Size |
|---|---:|---:|
| **In the repository** (`code/` + `dataset/`) | **3,563** | **96.6 MB** |
| Kept locally, not published | ~114,000 | ~5.0 GB |

The repository holds two parts: **business code** in `code/` (61 files) and the **dataset** in `dataset/` (3,499 files), plus the root documents (`README.md`, `INVENTORY.md`, `.gitignore`, `.gitattributes`). There are no experiment outputs, no participant data, no synthetic samples and no run workspaces.

The largest single file is 19.3 MB (`dataset/splits/discovery.csv`); every file is below GitHub's 100 MB per-file limit. Most of the volume comes from the split manifests and the F2P/P2P test-node listings.

## Repository contents

### `code/` — business code (61 files / 0.55 MB)

| Directory | Files | Paper section | Responsibility |
|---|---:|---|---|
| `01_infra_noncontainer/` | 3 | §IV-A, §V-E(2) | non-containerized environment base; fetching the 38 repositories and snapshotting base commits |
| `02_freeze_protocol/` | 9 | §III-B/C/D, §IV-B, §V-A/C | task list, splits and balanced allocation, freezing of protocol / event schema / codebook / policy, Chigh context packages, understanding check |
| `03_leakage/` | 2 | §IV-B(6), §V-A | automated answer-leakage screening and two-reviewer adjudication |
| `04_session/` | 3 | §V-B/C/E | session clock and event stream, permission guards for the three regimes, 75-minute hard stop, pilot gates |
| `05_evaluation/` | 6 | §V-F/G | hidden evaluation harness, metric aggregation (time accounting), pre-registered admission gate |
| `06_holdout/` | 14 | §V-G | holdout authoring with the three-condition admission, diff probes, feasibility calibration |
| `07_rq2_coding/` | 2 | §VII, §V-G | RQ2 coding manual / blinded packet / kappa estimator, agreement–kappa boundary check |
| `08_rq3_policy/` | 5 | §VIII-A/B | online signal extractor, adaptive policy state machine, threshold cross-validation rehearsal |
| `09_rq1_rq4_analysis/` | 2 | §VI, §IX | synthetic session generator + pipeline recovery check |
| `10_audit/` | 1 | §III-D, §XII | A–I audit groups, QA report, full freeze manifest |
| `99_scratch/` | 8 | — | one-off diagnostics, path repair, PDF extraction (not a paper artefact) |
| 7 root files | 7 | — | `code_map.json`, `sync.py`, `verify.py`, `run.py`, `requirements.txt`, `CODE_INDEX.md`, `CODE_INDEX.json` |

Per-file purpose, paper anchor, source path and SHA256 are in `code/CODE_INDEX.md`.

### `dataset/` — dataset (3,499 files / 96 MB)

| Directory | Files | Size | Nature | Origin |
|---|---:|---:|---|---|
| `tasks/` | 648 | 2.15 MB | 216 tasks: `issue.json`, `metadata.json`, `base_commit.txt` | derived from the upstream dataset |
| `benchmark_tests/` | 1,080 | 41.85 MB | F2P / P2P listings, oracle, test patch, `test_command.sh` | upstream |
| `gold/` | 1,320 | 10.83 MB | gold patch per task + `commits.csv` (commit URL, lines changed, modules changed) | upstream PRs/commits |
| `environments/` | 433 | 0.28 MB | upstream `Dockerfile`, `environment_metadata.json`, `reproduction.csv` | upstream |
| `splits/` | 3 | 40.55 MB | pilot / discovery / held-out task lists (including test-node listings) | this study |
| `holdout_tests/` | 14 | 0.10 MB | holdout suites that passed admission + `_calibration/` | this study |
| `screening/` | 1 | 0.26 MB | automatic screening: difficulty, buildability, external dependencies, leakage risk | this study |

No participant identifiers, questionnaires, trajectories or timing data: those are experiment outputs and are not in the repository.

## Kept locally, not published

### Excluded by `.gitignore` (shipped with the repository, so it also applies to any clone)

| Path | Files | Size | Why | How to restore |
|---|---:|---:|---|---|
| `dataset/raw/` | 29 | 1,361 MB | upstream monthly parquet/jsonl archives and the paper PDF | download from upstream into `dataset/raw/` |
| `dataset/tasks.csv` | 1 | 342 MB | full export of the same dataset (70,280 rows × 63 columns), **above GitHub's 100 MB file limit**; per-task material is already in `dataset/tasks/` | same as above |
| `dataset/repositories/` | 3,140 | 177 MB | 5 third-party repository snapshots (with `.git`); licences belong to upstream | `python code/run.py 01_infra_noncontainer/fetch_repos.py` |

### Excluded by `.git/info/exclude` (local assets; these rules are not shipped)

| Path | Files | Size | Why | How to restore |
|---|---:|---:|---|---|
| `experiment_root/` | 34,386 | 3,244 MB | experiment outputs and frozen assets: `manifests` (216), `context_packages` (216), `evaluation_spec` (216), `protocol`, `splits`, `tools`, plus `sessions`, `evaluation`, `codebook`, `interview`, `screening`, `policy`, `audit`, `analysis` | re-run the build scripts in `02_freeze_protocol/` and friends |
| `work/` | 38,175 | 96.6 MB | synthetic analysis-sample tree (SYNTHETIC / NOT_A_RESULT, 792 sessions) | `work/experiment_root/tools/sim_*.py` |
| `run/` | 38,184 | 96.8 MB | same, plus the de-identified release package under `run/release/` | same as above |
| `_docx_extract/` | 20 | 1.0 MB | XML/text extraction of the implementation-plan `.docx` | re-unpack the `.docx` |
| root `_*.py` / `_*.json` / `_*.txt` | 30 | 0.05 MB | one-off probe scripts | none needed (copies live in `code/99_scratch/`) |

`experiment_root/` contains **no real participant data**: `sessions/` is an empty directory and the 792 formal sessions are listed as "not yet collected" in `STATUS.md` §5.

## Things to know before uploading

1. **Absolute paths in the code are unchanged**: 55 of the 62 files in `code/` contain hardcoded paths pointing at `<repository root>\experiment_root` — 101 references in total (67 to `experiment_root/`, 21 to `dataset/`, 13 to the repository root). Scripts that only read the dataset and the algorithms run as-is; the full collection and evaluation chain needs a local `experiment_root/`.
2. **Answer material is published with the repository**: `dataset/gold/` (10.8 MB of fix patches) and `dataset/benchmark_tests/` (41.9 MB of F2P/P2P) are effectively the answers. If the repository is public and the same tasks will still be used for live data collection, consider adding both to `.gitignore`.
3. **Secret scan is clean**: the only hit across `dataset/` is the original issue text of `patroni__patroni-3045`, which contains the upstream-redacted `password: 'REDACTED'` — not a real credential.

## Upload performed

```powershell
cd <repository root>

git add .
git commit -m "project: repository-level repair delegation study -- code and dataset"
git remote add origin https://github.com/1563669740/contextualAdaptation.git
git push -u origin main
```

Remote: `https://github.com/1563669740/contextualAdaptation`, branch `main`, 3,565 files. Before committing, the repository-level `core.autocrlf` was set to `false` and `.gitattributes` was added (`* text=auto eol=lf`) so that the line endings of `dataset/gold/patches/*.patch` and `dataset/holdout_tests/*/*.diff` are not rewritten to CRLF.
