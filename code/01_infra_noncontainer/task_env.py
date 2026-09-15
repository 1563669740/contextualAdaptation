#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Execution environment builder -- the prerequisite for every human-role artefact.

Roles A1 (holdout author), A2 (quiz author) and B (semantic reviewer) all need
to actually RUN a repository's tests.  A holdout test that nobody executed is
just prose.  This module creates a per-task virtualenv from the task's own
dependency declaration and runs pytest inside a clean worktree at a given
commit, so the author can observe real behaviour.

Design notes
  * one venv per repository (not per task): six tasks of a repo share their
    dependency set, and venv creation dominates the cost.
  * the venv lives outside the repository clone so `git status` in the worktree
    stays clean -- the leak audit depends on that.
  * installation is best-effort and its outcome is recorded, because a missing
    dependency is an infrastructure fault (plan 13.1), not a task property.
  * no global installs: plan 2.2 forbids them, and they would break the
    "same tool for every condition" guarantee.

CLI
  python tools/task_env.py build  --task-id <id>          create/refresh venv
  python tools/task_env.py run    --task-id <id> [--commit C] [--apply P]...
                                  [-- pytest args...]
  python tools/task_env.py probe  --task-id <id>          report what is usable
  python tools/task_env.py status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset"
CACHE = os.path.join(ROOT, "repo_cache")
SNAP = os.path.join(CACHE, "_snapshots")
INV = os.path.join(CACHE, "_inventory")
ENVS = os.path.join(ROOT, "_envs")
WORK = os.path.join(ROOT, "_run_workspaces")
LOGDIR = os.path.join(ROOT, "audit", "task_env")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# heuristics: which file declares dependencies, and how to install
INSTALL_STRATEGIES = [
    ("requirements-dev.txt", ["-r", "requirements-dev.txt"]),
    ("dev-requirements.txt", ["-r", "dev-requirements.txt"]),
    ("requirements.txt", ["-r", "requirements.txt"]),
    ("requirements-test.txt", ["-r", "requirements-test.txt"]),
    ("test-requirements.txt", ["-r", "test-requirements.txt"]),
]


def run(cmd, cwd=None, timeout=3600, env=None, shell=False):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=env, shell=shell)
    return (p.returncode, p.stdout or "", p.stderr or "",
            round(time.time() - t0, 1))


def load(task_id):
    inv = json.load(open(os.path.join(INV, task_id + ".json"), encoding="utf-8"))
    snap = json.load(open(os.path.join(SNAP, task_id + ".json"),
                          encoding="utf-8"))
    idx = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                         encoding="utf-8"))["tasks"]
    meta = next((t for t in idx if t["task_id"] == task_id), None)
    if meta is None:
        raise SystemExit(f"unknown task {task_id}")
    return meta, inv, snap


def venv_path(repo_id):
    return os.path.join(ENVS, repo_id.replace("/", "__"))


def venv_python(repo_id):
    p = venv_path(repo_id)
    for cand in ("Scripts/python.exe", "bin/python"):
        f = os.path.join(p, cand.replace("/", os.sep))
        if os.path.exists(f):
            return f
    return None


def load_recipe(repo_id):
    """Repository-specific build steps, discovered by running the tests and
    recorded with the evidence (see manifests/build_recipes.json)."""
    p = os.path.join(ROOT, "manifests", "build_recipes.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8")).get("recipes", {}).get(repo_id, {})
    except Exception:
        return {}


def build_env(task_id, force=False):
    meta, inv, snap = load(task_id)
    repo_id = meta["repo_id"]
    vp = venv_path(repo_id)
    py = venv_python(repo_id)
    files = set(snap.get("files", {}))
    rec = {"repo_id": repo_id, "built_utc": NOW, "task_id": task_id,
           "steps": []}

    if py and not force:
        rec["reused"] = True
        rec["python"] = py
        return rec

    shutil.rmtree(vp, ignore_errors=True)
    os.makedirs(ENVS, exist_ok=True)
    rc, out, err, dt = run([sys.executable, "-m", "venv", vp], timeout=900)
    rec["steps"].append({"step": "venv", "rc": rc, "seconds": dt,
                         "stderr_tail": err[-300:]})
    if rc != 0:
        rec["ok"] = False
        return rec
    py = venv_python(repo_id)

    rc, out, err, dt = run([py, "-m", "pip", "install", "--upgrade",
                            "pip", "wheel", "setuptools"], timeout=1800)
    rec["steps"].append({"step": "pip_upgrade", "rc": rc, "seconds": dt})

    # test tooling first: without pytest nothing else matters
    rc, out, err, dt = run([py, "-m", "pip", "install", "pytest",
                            "pytest-xdist"], timeout=1800)
    rec["steps"].append({"step": "pytest", "rc": rc, "seconds": dt,
                         "stderr_tail": err[-300:]})

    installed = []
    for name, args in INSTALL_STRATEGIES:
        if name in files:
            rc, out, err, dt = run([py, "-m", "pip", "install"] + args,
                                   cwd=_worktree_for_install(task_id),
                                   timeout=3600)
            rec["steps"].append({"step": f"install:{name}", "rc": rc,
                                 "seconds": dt, "stderr_tail": err[-400:]})
            installed.append({"file": name, "rc": rc})
            if rc == 0:
                break
    if not installed:
        rec["steps"].append({"step": "install:none_declared", "rc": 0})

    # editable install of the project itself, when it has a build config
    if "pyproject.toml" in files or "setup.py" in files:
        wt = _worktree_for_install(task_id)
        rc, out, err, dt = run([py, "-m", "pip", "install", "-e", "."],
                               cwd=wt, timeout=3600)
        rec["steps"].append({"step": "install_editable", "rc": rc,
                             "seconds": dt, "stderr_tail": err[-400:]})

    # repository-specific steps (e.g. babel must build its CLDR data)
    recipe = load_recipe(repo_id)
    if recipe:
        rec["recipe"] = recipe
        wt = _worktree_for_install(task_id)
        for stage in ("pre_install", "post_install"):
            for cmd in recipe.get(stage, []):
                cmd = [py if c == "python" else c for c in cmd]
                rc, out, err, dt = run(cmd, cwd=wt, timeout=3600)
                rec["steps"].append({"step": f"{stage}:{' '.join(cmd[1:])}",
                                     "rc": rc, "seconds": dt,
                                     "stdout_tail": out[-300:],
                                     "stderr_tail": err[-400:]})
        for pkg in recipe.get("extra_requirements", []):
            rc, out, err, dt = run([py, "-m", "pip", "install", pkg],
                                   timeout=1800)
            rec["steps"].append({"step": f"extra:{pkg}", "rc": rc,
                                 "seconds": dt})
        # a rebuilt editable install so the generated data is picked up
        rc, out, err, dt = run([py, "-m", "pip", "install", "-e", "."],
                               cwd=wt, timeout=3600)
        rec["steps"].append({"step": "reinstall_after_recipe", "rc": rc,
                             "seconds": dt, "stderr_tail": err[-300:]})

    rec["ok"] = True
    rec["python"] = py
    rec["installed"] = installed
    os.makedirs(LOGDIR, exist_ok=True)
    json.dump(rec, open(os.path.join(LOGDIR, f"env_{repo_id.replace('/','__')}.json"),
                        "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return rec


_INSTALL_WT = {}


def _worktree_for_install(task_id):
    """A checkout used only so `pip install -e .` sees the project metadata.

    Goes through `workspace()` so it works for the repositories that were
    fetched as codeload tarballs (no local git clone available).
    """
    if task_id in _INSTALL_WT:
        return _INSTALL_WT[task_id]
    wt, _how = workspace(task_id)
    _INSTALL_WT[task_id] = wt
    return wt


def worktree(task_id, commit, tag=None, keep=False):
    meta, inv, snap = load(task_id)
    slug = meta["repo_id"].replace("/", "__")
    src = os.path.join(CACHE, slug)
    if not os.path.isdir(os.path.join(src, ".git")):
        raise SystemExit(
            f"no git clone for {slug}. This task was fetched via codeload "
            f"tarball, so there is no local git to make a worktree from. "
            f"Run repo_cache/fetch_repos.py {meta['repo_id']} first, or use "
            f"`tarball_worktree`.")
    dst = os.path.join(WORK, tag or f"{task_id}__{commit[:8]}")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rc, out, err, _ = run(["git", "worktree", "add", "--detach", "--force",
                           dst, commit], cwd=src, timeout=1800)
    if rc != 0:
        raise SystemExit(f"worktree add failed: {err[-300:]}")
    return dst


def tarball_worktree(task_id, commit):
    """Materialise the base commit from the cached codeload tarball.

    Needed for the 117 tasks whose repository has no local git clone, because
    `git clone` could not complete on this network.  The tarball is the same
    content that produced the frozen inventory, so it is the right source.
    """
    import io
    import tarfile
    meta, inv, snap = load(task_id)
    repo = meta["repo_id"]
    tb = os.path.join(CACHE, "_tarballs",
                      f"{repo.replace('/', '__')}__{commit}.tar.gz")
    if not os.path.exists(tb):
        raise SystemExit(f"no cached tarball for {repo}@{commit[:10]}")
    dst = os.path.join(WORK, f"{task_id}__{commit[:8]}")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    with tarfile.open(tb, "r:gz") as tf:
        for m in tf.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2:
                continue
            m.name = parts[1]
            tf.extract(m, dst, filter="data")
    # make it a git repo so diffs and patches behave normally
    run(["git", "init", "-q"], cwd=dst)
    run(["git", "config", "user.email", "exp@local"], cwd=dst)
    run(["git", "config", "user.name", "exp"], cwd=dst)
    run(["git", "add", "-A"], cwd=dst, timeout=1800)
    run(["git", "commit", "-qm", f"base {commit[:10]}"], cwd=dst, timeout=1800)
    return dst


def artifact_cache(repo_id):
    return os.path.join(ENVS, "_artifacts", repo_id.replace("/", "__"))


def ensure_recipe_artifacts(task_id, wd):
    """Copy a repository's cached build products into a fresh worktree.

    Some projects generate data during setup (babel builds its CLDR
    locale-data).  A fresh checkout has none of it, and rebuilding per scenario
    is wasteful, so the products are built once under _envs/_artifacts and
    copied into each workspace.  This is what makes repeated runs of the same
    task comparable -- the M1 'environment_repeatable' gate depends on it.
    """
    meta, _, _ = load(task_id)
    recipe = load_recipe(meta["repo_id"])
    arts = recipe.get("recipe_artifacts") or []
    if not arts:
        return []
    src_root = artifact_cache(meta["repo_id"])
    copied = []
    for rel in arts:
        src = os.path.join(src_root, rel.replace("/", os.sep))
        dst = os.path.join(wd, rel.replace("/", os.sep))
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        copied.append(rel)
    return copied


def build_recipe_artifacts(task_id):
    """Run the recipe's generator once and cache its declared products."""
    meta, _, _ = load(task_id)
    repo_id = meta["repo_id"]
    recipe = load_recipe(repo_id)
    arts = recipe.get("recipe_artifacts") or []
    if not arts:
        return {"built": [], "reason": "no recipe_artifacts declared"}
    cache = artifact_cache(repo_id)
    if all(os.path.isdir(os.path.join(cache, a.replace("/", os.sep)))
           for a in arts):
        return {"built": arts, "cached": True}
    wd, how = workspace(task_id, skip_artifacts=True)
    py = venv_python(repo_id) or sys.executable
    steps = []
    for stage in ("pre_install", "post_install"):
        for cmd in recipe.get(stage, []):
            cmd = [py if c == "python" else c for c in cmd]
            rc, out, err, dt = run(cmd, cwd=wd, timeout=5400)
            steps.append({"step": f"{stage}:{' '.join(cmd[1:])}", "rc": rc,
                          "seconds": dt, "stderr_tail": err[-300:]})
    os.makedirs(cache, exist_ok=True)
    for rel in arts:
        src = os.path.join(wd, rel.replace("/", os.sep))
        if os.path.isdir(src):
            dst = os.path.join(cache, rel.replace("/", os.sep))
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
    return {"built": arts, "steps": steps, "cache": cache}


def workspace(task_id, commit=None, skip_artifacts=False):
    """Best available clean checkout at `commit` (default base_commit)."""
    meta, inv, snap = load(task_id)
    commit = commit or meta["base_commit"]
    slug = meta["repo_id"].replace("/", "__")
    if os.path.isdir(os.path.join(CACHE, slug, ".git")):
        try:
            wd, how = worktree(task_id, commit), "git_worktree"
        except SystemExit:
            wd, how = tarball_worktree(task_id, commit), "codeload_tarball"
    else:
        wd, how = tarball_worktree(task_id, commit), "codeload_tarball"
    if not skip_artifacts:
        ensure_recipe_artifacts(task_id, wd)
    return wd, how


def apply_patch(wd, path):
    if not path or not os.path.exists(path):
        return {"applied": False, "reason": "missing", "path": path}
    rc, out, err, _ = run(["git", "apply", "-v", "--whitespace=nowarn", path],
                          cwd=wd)
    if rc == 0:
        return {"applied": True}
    rc, out, err, _ = run(["git", "apply", "-v", "--3way",
                           "--whitespace=nowarn", path], cwd=wd)
    return {"applied": rc == 0, "reason": (err or out)[-400:]}


def run_pytest(task_id, wd, args=None, timeout=3600, py=None):
    meta, _, _ = load(task_id)
    py = py or venv_python(meta["repo_id"]) or sys.executable
    args = args or ["-q", "-x", "--no-header", "-p", "no:cacheprovider"]
    cmd = [py, "-m", "pytest"] + args
    rc, out, err, dt = run(cmd, cwd=wd, timeout=timeout)
    return {"cmd": " ".join(cmd), "rc": rc, "seconds": dt,
            "stdout": out, "stderr": err}


def probe(task_id):
    meta, inv, snap = load(task_id)
    repo_id = meta["repo_id"]
    out = {"task_id": task_id, "repo_id": repo_id,
           "has_git_clone": os.path.isdir(os.path.join(
               CACHE, repo_id.replace("/", "__"), ".git")),
           "has_tarball": os.path.exists(os.path.join(
               CACHE, "_tarballs",
               f"{repo_id.replace('/','__')}__{meta['base_commit']}.tar.gz")),
           "venv": venv_python(repo_id),
           "declared_dep_files": [n for n, _ in INSTALL_STRATEGIES
                                  if n in set(snap.get("files", {}))],
           "has_pyproject": "pyproject.toml" in set(snap.get("files", {})),
           "test_header_count": snap.get("n_headers", 0)}
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build"); p.add_argument("--task-id", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=lambda a: print(json.dumps(build_env(a.task_id, a.force),
                                                 indent=1, ensure_ascii=False)))

    p = sub.add_parser("probe"); p.add_argument("--task-id", required=True)
    p.set_defaults(fn=lambda a: print(json.dumps(probe(a.task_id), indent=1)))

    p = sub.add_parser("run")
    p.add_argument("--task-id", required=True)
    p.add_argument("--apply", action="append", default=[])
    p.add_argument("--pytest", nargs=argparse.REMAINDER, default=None)
    def _run(a):
        wd, how = workspace(a.task_id)
        res = {"task_id": a.task_id, "workspace": wd, "source": how,
               "applied": [apply_patch(wd, p) for p in a.apply]}
        r = run_pytest(a.task_id, wd, a.pytest or None)
        res["pytest"] = {k: v for k, v in r.items() if k not in ("stdout",)}
        print(json.dumps(res, indent=1, ensure_ascii=False)[:4000])
        print("---- stdout tail ----")
        print(r["stdout"][-3000:])
        print("---- stderr tail ----")
        print(r["stderr"][-1500:])
    p.set_defaults(fn=_run)

    p = sub.add_parser("status")
    def _status(a):
        os.makedirs(ENVS, exist_ok=True)
        envs = sorted(d for d in os.listdir(ENVS)
                      if os.path.isdir(os.path.join(ENVS, d)))
        print(f"{len(envs)} repository venvs:")
        for e in envs:
            py = venv_python(e.replace("__", "/"))
            print(f"  {e:52s} {'python OK' if py else 'BROKEN'}")
    p.set_defaults(fn=_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
