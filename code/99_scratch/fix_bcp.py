import io, os

p = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools\build_context_packages.py"
s = open(p, encoding="utf-8").read()

pairs = [
    ("""A(f"**Repository:** {man['repo_url']}  ")""",
     """A(f"**Repository:** {repo_url}  ")"""),
    ("""A(f"**Language:** {man['language']}  ")""",
     """A(f"**Language:** {language}  ")"""),
    ("""A(f"| 2 | `{man['repo_url']}` @ `{commit}` | file inventory, tree, module \"""",
     """A(f"| 2 | `{repo_url}` @ `{commit}` | file inventory, tree, module \""""),
]
for old, new in pairs:
    if old not in s:
        print("NOT FOUND:", old[:70])
    s = s.replace(old, new)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("remaining man['repo_url']:", s.count("man['repo_url']"))
print("remaining man['language']:", s.count("man['language']"))
print("remaining man['repo_slug']:", s.count("man['repo_slug']"))
