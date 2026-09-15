# project

Repository-level software defect repair: business code (`code/`) and dataset (`dataset/`), covering 216 tasks from 38 repositories.

## Environment

```bash
python -m pip install -r code/requirements.txt     # standard library + PyYAML only
```

Requires Python 3.11 (verified on 3.11.7), git, and network access to github.com / codeload.github.com.

## Commands

```bash
python code/verify.py                              # byte-identity check of the code copy + full syntax check
python code/run.py --list                          # list every runnable script
python code/run.py <script> [args]                 # run any script through the unified launcher

# common entry points
python code/run.py 10_audit/audit.py                       # full audit
python code/run.py 05_evaluation/aggregate_metrics.py      # metric aggregation
python code/run.py 05_evaluation/evaluate.py --session-id D-S0001
python code/run.py 08_rq3_policy/online_policy.py --self-test
python code/run.py 09_rq1_rq4_analysis/check_pipeline.py   # pipeline self-check
```
