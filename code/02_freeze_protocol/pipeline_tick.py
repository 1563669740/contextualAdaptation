#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Consume newly fetched snapshots: build Chigh context packages and per-task
environment manifests for every task whose inventory + snapshot are complete,
then report how many tasks remain.

Safe to run repeatedly and safe to run while repo_cache/fetch_repos.py is still
working: it only reads snapshots that already exist, and both builders are
idempotent per task.

Usage
  python _pipeline_tick.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
INV = os.path.join(ROOT, "repo_cache", "_inventory")
SNAP = os.path.join(ROOT, "repo_cache", "_snapshots")


def ready_tasks():
    ready = []
    if not os.path.isdir(INV):
        return ready
    for f in sorted(os.listdir(INV)):
        if f.startswith("_") or not f.endswith(".json"):
            continue
        tid = f[:-5]
        sp = os.path.join(SNAP, f)
        if not os.path.exists(sp):
            continue
        try:
            inv = json.load(open(os.path.join(INV, f), encoding="utf-8"))
            snap = json.load(open(sp, encoding="utf-8"))
        except Exception:
            continue
        if inv.get("ok") and inv.get("n_files") and "error" not in snap:
            ready.append(tid)
    return ready


def main():
    ready = ready_tasks()
    print(f"tasks with usable base-commit snapshot: {len(ready)}/216")
    if not ready:
        return

    rc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools",
                                      "build_context_packages.py"),
         "--workers", "8", "--only"] + ready,
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    tail = [l for l in (rc.stdout or "").splitlines() if l.strip()][-1:]
    print("context packages :", tail[0] if tail else f"rc={rc.returncode}")
    if rc.returncode not in (0,) and rc.stderr:
        print("  stderr tail:", rc.stderr.strip().splitlines()[-1:])

    rc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools",
                                      "build_env_manifests.py")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    for line in (rc.stdout or "").splitlines():
        if line.startswith("environment manifests") or \
                line.startswith("skipped"):
            print(line)

    n_cp = len([f for f in os.listdir(os.path.join(ROOT, "context_packages"))
                if f.endswith(".md")])
    n_env = len([f for f in os.listdir(os.path.join(ROOT, "manifests", "env"))
                 if f.endswith(".yaml")]) if os.path.isdir(
        os.path.join(ROOT, "manifests", "env")) else 0
    print(f"built so far     : context_packages {n_cp}/216   "
          f"env manifests {n_env}/216")


if __name__ == "__main__":
    main()
