import io
import os
import re

# --- fix evaluate.py: the gold_patch_file value is repo-relative and already
#     carries the "gold/patches/..." prefix, so joining it onto TIFS is wrong.
p = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\evaluation\evaluate.py"
s = open(p, encoding="utf-8").read()

old = """    gold = os.path.join(DS, spec["gold_patch_file"]) if spec.get(
        "gold_patch_file") else None"""
new = """    gold = resolve_dataset_path(spec.get("gold_patch_file"))"""
assert old in s, "verify_holdout gold path not found"
s = s.replace(old, new)

old2 = """def load_spec(task_id):"""
new2 = '''def resolve_dataset_path(rel):
    """Resolve a path recorded in an evaluation spec.

    Specs store dataset-relative paths (e.g. "gold/patches/x.patch"), but the
    test-patch entry was written relative to the TIFS workspace instead. Both
    forms appear in already-frozen specs, so handle them explicitly rather than
    silently producing a doubled prefix like TIFS/gold/patches/... .
    """
    if not rel:
        return None
    if os.path.isabs(rel):
        return rel if os.path.exists(rel) else None
    tifs = r"C:\\Users\\Administrator\\Desktop\\TIFS"
    for base in (tifs, DS):
        cand = os.path.join(base, rel.replace("/", os.sep))
        if os.path.exists(cand):
            return cand
    # last resort: strip a leading dataset dir name and retry
    parts = rel.replace("\\\\", "/").split("/")
    if parts and parts[0] in ("dataset", "gold", "benchmark_tests"):
        cand = os.path.join(DS, *parts[1:])
        if os.path.exists(cand):
            return cand
    return os.path.join(tifs, rel.replace("/", os.sep))


def load_spec(task_id):'''
assert old2 in s
s = s.replace(old2, new2, 1)

# route the test-patch resolution through the same helper
old3 = """    a = apply_patch(workdir, spec["test_patch_file"] if
                    os.path.isabs(spec.get("test_patch_file") or "")
                    else os.path.join(r"C:\\Users\\Administrator\\Desktop\\TIFS",
                                      spec.get("test_patch_file") or ""),
                    "test_patch")"""
new3 = """    a = apply_patch(workdir, resolve_dataset_path(spec.get("test_patch_file")),
                    "test_patch")"""
assert old3 in s, "run_stage test patch path not found"
s = s.replace(old3, new3)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("evaluate.py patched")

# --- fix build_inventory.py so future specs are consistent
p2 = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools\build_inventory.py"
s2 = open(p2, encoding="utf-8").read()
old4 = """            "test_patch_file": os.path.relpath(test_patch,
                                               r"C:\\Users\\Administrator\\Desktop\\TIFS")
                               .replace("\\\\", "/"),"""
new4 = """            "test_patch_file": os.path.relpath(test_patch, DS)
                               .replace("\\\\", "/"),"""
if old4 in s2:
    s2 = s2.replace(old4, new4)
    open(p2, "w", encoding="utf-8", newline="\n").write(s2)
    print("build_inventory.py patched (test_patch_file now dataset-relative)")
else:
    print("build_inventory.py: pattern not found, skipped")
