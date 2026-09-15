#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase I -- Per-task environment manifests + reference fingerprint (plan 2.3, 13.2)

Plan 2.3 requires every task to carry an `environment manifest` with: task_id,
repo_url/repo_id, base_commit, os_image, runtime_versions, dependency_install,
test_commands, network_policy, resource_limits and env_hash.

Plan 13.2 additionally requires an environment fingerprint (kernel, CPU, RAM,
locale, timezone, toolchain versions, lockfile hashes).

This tool produces:
  manifests/env/<task_id>.yaml     the frozen per-task manifest
  manifests/reference_environment.json   the fingerprint of the machine the
                                   manifests were generated on

Honesty note recorded inside every manifest: the reference fingerprint is
captured on the generation host.  The plan targets a fixed Linux VM, so when
the real experiment host is provisioned the fingerprint block must be
re-recorded and `env_hash` recomputed **before the first formal session** --
which is exactly what plan 2.3's `env_hash` is for.  The dependency pins,
commands and resource limits are host-independent and are frozen here.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"
SNAP = os.path.join(ROOT, "repo_cache", "_snapshots")
INV = os.path.join(ROOT, "repo_cache", "_inventory")
OUT = os.path.join(ROOT, "manifests", "env")
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

RUNNER_VERSION = "0.1.0"
LOCKFILE_CANDIDATES = [
    "poetry.lock", "uv.lock", "pdm.lock", "requirements.txt",
    "requirements-dev.txt", "requirements-test.txt", "setup.py",
    "pyproject.toml", "setup.cfg", "Pipfile.lock", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock",
]


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def try_cmd(args, timeout=60):
    exe = shutil.which(args[0])
    if not exe:
        return None
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (p.stdout or p.stderr or "").strip().splitlines()[0]
    except Exception:
        return None


def fingerprint():
    fps = {
        "captured_utc": NOW,
        "host_provisional": True,
        "captured_on": "manifest generation host (not the experiment host)",
        "os_build": f"{platform.system()} {platform.release()} "
                    f"{platform.version()}",
        "kernel": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "git_version": try_cmd(["git", "--version"]),
        "node_version": try_cmd(["node", "--version"]),
        "npm_version": try_cmd(["npm", "--version"]),
        "java_version": try_cmd(["java", "-version"]),
        "gcc_version": try_cmd(["gcc", "--version"]),
        "clang_version": try_cmd(["clang", "--version"]),
        "rustc_version": try_cmd(["rustc", "--version"]),
        "go_version": try_cmd(["go", "version"]),
        "locale": os.environ.get("LANG") or os.environ.get("LC_ALL"),
        "timezone": os.environ.get("TZ"),
        "path_sanitised": os.environ.get("PATH", "")[:400],
    }
    try:
        import locale as _l
        fps["preferred_encoding"] = _l.getpreferredencoding(False)
    except Exception:
        pass
    return fps


def yaml_dump(obj, indent=0):
    sp = "  " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{sp}{k}:")
                out.append(yaml_dump(v, indent + 1))
            elif isinstance(v, (dict, list)):
                out.append(f"{sp}{k}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                out.append(f"{sp}{k}: {scalar(v)}")
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, (dict, list)) and it:
                body = yaml_dump(it, indent + 1).split("\n")
                out.append(f"{sp}- {body[0].strip()}")
                out.extend(body[1:])
            else:
                out.append(f"{sp}- {scalar(it)}")
    return "\n".join(out)


def scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s.strip() != s or any(c in s for c in ":#{}[]&*!|>'\"%@`,") \
            or s.lower() in ("yes", "no", "true", "false", "null", "~") \
            or s[0] in "-? " or "\n" in s:
        return json.dumps(s, ensure_ascii=False)
    return s


def lockfiles_from_snapshot(snap):
    files = set(snap.get("files", {}))
    inv = set()
    return [f for f in LOCKFILE_CANDIDATES if f in files]


def install_commands(lockfiles, repo_id):
    cmds = ["python -m venv .venv"]
    if "poetry.lock" in lockfiles:
        cmds += ["pip install poetry", "poetry install --no-root"]
    elif "uv.lock" in lockfiles:
        cmds += ["pip install uv", "uv sync"]
    elif "pdm.lock" in lockfiles:
        cmds += ["pip install pdm", "pdm install"]
    elif "requirements.txt" in lockfiles:
        cmds += [".venv/bin/pip install -r requirements.txt"]
    elif "pyproject.toml" in lockfiles:
        cmds += [".venv/bin/pip install -e ."]
    else:
        cmds += [".venv/bin/pip install -e ."]
    return cmds


def main():
    os.makedirs(OUT, exist_ok=True)
    index = json.load(open(os.path.join(ROOT, "manifests", "task_index.json"),
                           encoding="utf-8"))["tasks"]
    fp = fingerprint()
    json.dump(fp, open(os.path.join(ROOT, "manifests",
                                    "reference_environment.json"), "w",
                       encoding="utf-8"), indent=1, ensure_ascii=False)

    built, skipped = 0, []
    env_index = []
    for t in index:
        tid = t["task_id"]
        sp = os.path.join(SNAP, tid + ".json")
        ip = os.path.join(INV, tid + ".json")
        if not os.path.exists(sp) or not os.path.exists(ip):
            skipped.append({"task_id": tid, "reason": "no snapshot/inventory"})
            continue
        snap = json.load(open(sp, encoding="utf-8"))
        inv = json.load(open(ip, encoding="utf-8"))
        if "error" in snap or not inv.get("ok"):
            skipped.append({"task_id": tid, "reason": "snapshot/inventory error"})
            continue

        lock = lockfiles_from_snapshot(snap)
        lock_hashes = {}
        for lf in lock:
            v = snap["files"][lf]
            lock_hashes[lf] = v.get("sha256") or v.get("blob")

        man = {
            "schema_version": "1.0",
            "task_id": tid,
            "repo_id": t["repo_id"],
            "repo_url": f"https://github.com/{t['repo_id']}.git",
            "base_commit": t["base_commit"],
            "split": t["split"],
            "language": t["language"],
            "os_image": "TO_BE_PINNED_BEFORE_SESSIONS",
            "os_image_note": ("plan 2.1 recommends a fixed Ubuntu LTS base image "
                              "with per-task snapshot/clone; record the exact "
                              "image id here when the experiment host is "
                              "provisioned"),
            "isolation": {
                "type": "non_containerized",
                "mechanism": "per-task workspace + language-level virtualenv",
                "docker_used": False,
                "reset_procedure": [
                    "terminate session processes",
                    "snapshot the worktree for the record",
                    "git reset --hard && git clean -fdx",
                    "delete the task virtualenv / node_modules",
                ],
            },
            "runtime_versions": {
                "python": "3.11",
                "python_note": ("upstream SWE-bench-Live images for this "
                                "family use Python 3.11; pin exactly at host "
                                "provisioning"),
                "node": None, "java": None, "rust": None, "go": None,
            },
            "dependency_install": install_commands(lock, t["repo_id"]),
            "lockfiles": lock,
            "lockfile_hashes_sha256": lock_hashes,
            "visible_tests": {
                "smoke": "pytest -q <visible target>",
                "benchmark": "see evaluation_spec (evaluation-only)",
                "note": ("participants and agents may run any test present in "
                         "the base repository; the grading command is held in "
                         "evaluation_spec/ and is not participant-visible"),
            },
            "network_policy": {"setup": "allow-package-mirrors",
                               "task": "deny-external-by-default"},
            "resource_limits": {"cpu": 4, "memory_gb": 8, "disk_gb": 30},
            "artifacts": {
                "base_commit_file_count": inv["n_files"],
                "base_commit_bytes": inv["n_bytes"],
                "inventory_sha256": inv["inventory_sha256"],
                "runner_version": RUNNER_VERSION,
                "repository_prefetched": True,
            },
        }
        body = yaml_dump(man)
        env_hash = sha256_text(body)
        man["env_hash"] = env_hash
        with open(os.path.join(OUT, tid + ".yaml"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(f"# environment manifest -- {tid}\n")
            f.write(f"# generated {NOW}; env_hash is the SHA256 of this "
                    f"document with the env_hash field omitted\n")
            f.write(yaml_dump(man) + "\n")
        env_index.append({
            "task_id": tid, "repo_id": t["repo_id"], "split": t["split"],
            "base_commit": t["base_commit"], "env_hash": env_hash,
            "lockfiles": lock, "manifest": f"manifests/env/{tid}.yaml",
        })
        built += 1

    json.dump({
        "generated_utc": NOW,
        "runner_version": RUNNER_VERSION,
        "reference_fingerprint_file": "manifests/reference_environment.json",
        "n_manifests": built,
        "skipped": skipped,
        "note": ("env_hash values are frozen; re-record the reference "
                 "fingerprint and recompute on the real experiment host BEFORE "
                 "the first formal session (plan 2.3)"),
        "tasks": env_index,
    }, open(os.path.join(ROOT, "manifests", "env_index.json"), "w",
            encoding="utf-8"), indent=1, ensure_ascii=False)

    print(f"environment manifests written: {built}")
    print(f"skipped                     : {len(skipped)}")
    for s in skipped[:10]:
        print("  ", s)
    if env_index:
        print(f"sample env_hash             : "
              f"{env_index[0]['env_hash'][:24]}…")


if __name__ == "__main__":
    main()
