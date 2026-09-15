import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import build_understanding_quiz as q

for tid in ("python-attrs__attrs-1372", "instructlab__instructlab-612",
            "beeware__briefcase-1598", "kozea__weasyprint-2041"):
    meta, inv, snap = q.load(tid)
    src = {p: v for p, v in snap.get("files", {}).items()
           if v.get("kind") == "verbatim"}
    mod2path, edges = q.build_imports(src)
    tests = [f["path"] for f in inv["files"] if q.is_test_path(f["path"])]
    headers = [p for p, v in snap.get("files", {}).items()
               if v.get("kind") == "test_header"]
    print(f"\n=== {tid}")
    print(f"  verbatim src files : {len(src)}   py modules: {sum(1 for p in src if p.endswith('.py'))}")
    print(f"  internal edges     : {len(edges)}  (with targets: {sum(1 for v in edges.values() if v)})")
    print(f"  test paths         : {len(tests)}  test headers: {len(headers)}")
    print(f"  test dirs          : {sorted({os.path.dirname(t) or '.' for t in tests})[:6]}")
    print(f"  n_items built      : {len(q.build_quiz(tid)['items'])}")
