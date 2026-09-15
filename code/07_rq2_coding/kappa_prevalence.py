"""A prevalence-consistency check on the paper's reported reliability.

The simulator reproduces the paper's raw agreement cheaply, but not its kappa.
That gap is not a bug in the simulator -- it is information about the data the
paper must have had, and it is worth extracting.

For two raters and a binary item, kappa depends on raw agreement AND on the
marginal prevalence.  Fixing agreement at the paper's 0.889, this solves for the
prevalence that would produce the paper's kappa of 0.82, and compares it with
the prevalence in the synthetic sample.
"""
import json
import os

ROOT = r"C:\Users\Administrator\Desktop\TIFS\experiment_root"


def kappa_from(po, p_a, p_b):
    """Closed form for binary kappa given agreement and the two marginals."""
    pe = p_a * p_b + (1 - p_a) * (1 - p_b)
    return (po - pe) / (1 - pe)


def solve_prevalence(target_kappa, po, lo=0.01, hi=0.99, iters=200):
    """Bisection on a common prevalence p (both raters marginal p)."""
    f = lambda p: kappa_from(po, p, p) - target_kappa
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


PO = 0.889
TARGET = 0.82

# Scan prevalence to find the attainable kappa range.  Bisection cannot be used
# here because the target may be unattainable at ANY prevalence, which is
# exactly what turns out to happen.
scan = [(round(p / 1000, 3), kappa_from(PO, p / 1000, p / 1000))
        for p in range(1, 1000)]
best_p, best_k = max(scan, key=lambda t: t[1])
print(f"paper reports raw agreement {PO} and kappa {TARGET}")
print(f"maximum attainable kappa at that agreement: {best_k:.4f} "
      f"(at prevalence {best_p:.3f})")
print(f"is the reported kappa attainable at all?  "
      f"{'YES' if best_k >= TARGET else 'NO'}")

near = [t for t in scan if abs(t[1] - 0.82) < 0.02]
print(f"prevalences giving kappa within 0.02 of 0.82: "
      f"{[t[0] for t in near][:8] or 'none'}")
p = best_p

# what the synthetic sample actually has
d = json.load(open(os.path.join(ROOT, "analysis", "synthetic",
                                "semantic_review.json"), encoding="utf-8"))
k = d["would_accept_reliability"]
conf = k["confusion"]
n = sum(sum(r) for r in conf)
a_yes = conf[0][0] + conf[0][1]
b_yes = conf[0][0] + conf[1][0]
print(f"\nsynthetic sample: n={n}, rater A accept rate "
      f"{a_yes/n:.3f}, rater B {b_yes/n:.3f}")
print(f"synthetic kappa at that prevalence: {k['cohen_kappa']}")

print("\ninterpretation:")
print("  For a binary item, raw agreement and kappa are bound together: at 88.9%")
print("  agreement the LARGEST kappa any prevalence can produce is the number")
print("  printed above. If the paper's 0.82 exceeds it, the two statistics")
print("  cannot come from one 2x2 table of binary decisions.")
print("  The likely explanation is that kappa was computed over the multi-level")
print("  rubric items (yes / partly / no, where chance agreement is lower) while")
print("  the 88.9% agreement was reported for the binary would-accept item --")
print("  a common and easily-overlooked mismatch when a rubric has both kinds of")
print("  item. This replication must therefore record, for EACH rubric item")
print("  separately, its own agreement and kappa, so the two can never be")
print("  quoted as if they described the same judgement.")

out = {
    "checked_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "paper_reported": {"raw_agreement": PO, "kappa": TARGET},
    "max_attainable_kappa_at_reported_agreement": round(best_k, 4),
    "prevalence_at_maximum": best_p,
    "reported_kappa_attainable": bool(best_k >= TARGET),
    "synthetic": {"n": n, "kappa": k["cohen_kappa"],
                  "rater_A_accept_rate": round(a_yes / n, 4),
                  "rater_B_accept_rate": round(b_yes / n, 4)},
    "conclusion": ("at 88.9% agreement a binary item cannot yield kappa above "
                   f"{best_k:.3f} at any prevalence, so the paper's 0.82 must "
                   "come from a different item's marginals (most plausibly the "
                   "three-level rubric items)"),
    "action_for_the_real_review": ("report agreement AND kappa per rubric item, "
                                   "with the item's category distribution; do "
                                   "not quote one item's agreement beside "
                                   "another item's kappa"),
}
json.dump(out, open(os.path.join(ROOT, "analysis", "synthetic",
                                 "kappa_prevalence_check.json"), "w",
                    encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote analysis/synthetic/kappa_prevalence_check.json")
