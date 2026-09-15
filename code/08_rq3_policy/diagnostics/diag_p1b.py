import json
import os
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\TIFS\experiment_root\tools")
import online_policy as op

d = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\analysis\synthetic\sessions"
ex = op.OnlineExtractor()
print(f"window_ms={ex.window_ms}  (6 min = {ex.window_ms} ms)")
for s in sorted(os.listdir(d))[:4]:
    ev = [json.loads(l) for l in open(os.path.join(d, s, "events.jsonl"),
                                      encoding="utf-8") if l.strip()]
    span = ev[-1]["monotonic_ms"]
    w = ex._windows(ev)
    p1 = ex.p1(ev)
    opens = [(e["monotonic_ms"], e["payload"]["path"])
             for e in ev if e["event_type"] == "open"]
    print(f"\n{s}: span_ms={span} windows={sorted(w)} "
          f"distinct_windows_with_events={len(w)}")
    print(f"  opens: {opens[:6]}")
    print(f"  candidate_set_size: {p1['candidate_set_size']}")
    print(f"  fired per window  : {p1['fired']}")
