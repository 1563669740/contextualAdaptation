import os, io, re

p = (r"C:\Users\Administrator\Desktop\TIFS\experiment_root\repo_cache"
     r"\fetch_repos.py")
s = open(p, encoding="utf-8").read()

# 1) fewer concurrent connections -- GitHub throttles aggressively above ~2-3
s = s.replace("with cf.ThreadPoolExecutor(max_workers=4) as ex:",
              "with cf.ThreadPoolExecutor(max_workers=2) as ex:")

# 2) batch the commit fetch so partial progress survives a dropped connection
old = """        net_fail = False
        for attempt in range(1, 5):
            rc, _, err, dt = run(
                ["git", "fetch", "--no-tags", "origin"] + missing,
                cwd=dest, timeout=5400)
            log.append({"repo": repo, "op": "fetch_commits", "rc": rc,
                        "n": len(missing), "attempt": attempt,
                        "seconds": round(dt, 1), "stderr_tail": err[-400:]})
            flush_log(log)
            if rc == 0:
                net_fail = False
                break
            net_fail = True
            time.sleep(min(60, 5 * 2 ** attempt))
        if net_fail:
            still = [bc for bc in missing
                     if run(["git", "cat-file", "-e", bc + "^{commit}"],
                            cwd=dest)[0] != 0]
            return log, {"__error__": f"fetch failed for {len(still)} commits"}"""

new = """        # Fetch in small batches: a dropped connection then costs one batch
        # rather than the whole repository, and GitHub is far less likely to
        # stall a short request.  Each batch is retried with backoff and with a
        # bounded timeout, so a hung socket cannot hold the pass open forever.
        BATCH = 2
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            batch = [bc for bc in batch
                     if run(["git", "cat-file", "-e", bc + "^{commit}"],
                            cwd=dest)[0] != 0]
            if not batch:
                continue
            ok = False
            for attempt in range(1, 6):
                rc, _, err, dt = run(
                    ["git", "fetch", "--no-tags", "--depth=1", "origin"] + batch,
                    cwd=dest, timeout=900)
                log.append({"repo": repo, "op": "fetch_commits", "rc": rc,
                            "n": len(batch), "attempt": attempt,
                            "seconds": round(dt, 1),
                            "stderr_tail": err[-400:]})
                flush_log(log)
                if rc == 0:
                    ok = True
                    break
                time.sleep(min(120, 15 * 2 ** attempt))
            if not ok:
                still = [bc for bc in batch
                         if run(["git", "cat-file", "-e", bc + "^{commit}"],
                                cwd=dest)[0] != 0]
                if still:
                    return log, {"__error__": (
                        f"fetch failed for {len(still)} commit(s) of "
                        f"{repo}; rerun later: python fetch_repos.py {repo}")}"""

assert old in s, "fetch block not found"
s = s.replace(old, new)

# 3) pause between repositories so we do not hammer the connection pool
old2 = """            if rc == 0:
                break
            shutil.rmtree(dest, ignore_errors=True)
            time.sleep(min(90, 10 * 2 ** attempt))"""
new2 = """            if rc == 0:
                break
            shutil.rmtree(dest, ignore_errors=True)
            time.sleep(min(180, 20 * 2 ** attempt))"""
assert old2 in s, "clone retry block not found"
s = s.replace(old2, new2)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched fetch_repos.py")
print("workers=2:", "max_workers=2" in s)
print("batched fetch:", "BATCH = 2" in s)
print("depth=1:", "--depth=1" in s)
