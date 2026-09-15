import os, csv, subprocess, json

csv.field_size_limit(10**9)
DS = r"C:\Users\Administrator\Desktop\TIFS\dataset\repositories"
rows = list(csv.DictReader(open(
    r"C:\Users\Administrator\Desktop\TIFS\dataset\gold\commits.csv",
    newline="", encoding="utf-8")))

need = {}
for r in rows:
    need.setdefault(r["repo"], set()).add(r["base_commit"])


def g(repo_dir, *args):
    p = subprocess.run(["git", "-C", repo_dir] + list(args),
                       capture_output=True, text=True, errors="replace",
                       timeout=120)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


print(f"{'repo':52s} {'local?':6s} {'base commits present':22s} ls-tree?")
print("-" * 100)
report = {}
for repo, bcs in sorted(need.items()):
    slug = repo.replace("/", "__")
    d = os.path.join(DS, slug)
    if not os.path.isdir(os.path.join(d, ".git")):
        print(f"{repo:52s} {'no':6s} {'-':22s} -")
        continue
    have = sum(1 for bc in bcs if g(d, "cat-file", "-e", bc + "^{commit}")[0] == 0)
    sample = sorted(bcs)[0]
    rc, out, err = g(d, "ls-tree", "-r", "--name-only", sample)
    lstree = (rc == 0 and len(out.splitlines()) > 0)
    filt = g(d, "config", "--get", "remote.origin.partialclonefilter")[1]
    report[repo] = {"slug": slug, "have": have, "need": len(bcs),
                    "ls_tree_ok": lstree, "files": len(out.splitlines()),
                    "partial_filter": filt}
    print(f"{repo:52s} {'yes':6s} {str(have)+'/'+str(len(bcs)):22s} "
          f"{'OK ('+str(len(out.splitlines()))+' files)' if lstree else 'FAIL'}  {filt}")

json.dump(report, open(r"C:\Users\Administrator\Desktop\TIFS\_local_clone_probe.json",
                       "w", encoding="utf-8"), indent=1)
print()
full = [r for r, v in report.items() if v["have"] == v["need"] and v["ls_tree_ok"]]
print(f"usable local clones with all base commits: {len(full)}")
for r in full:
    print("   ", r)
