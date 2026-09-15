#!/usr/bin/env bash
# Official SWE-bench-Live execution recipe (log_parser: pytest).
set -euo pipefail
cd /testbed
git checkout -- . && git checkout {base_commit}
git apply -v /tmp/test_patch.diff          # benchmark tests
git apply -v /tmp/model_patch.diff         # participant / agent patch
pytest --numprocesses 4 --dist loadfile -rA
