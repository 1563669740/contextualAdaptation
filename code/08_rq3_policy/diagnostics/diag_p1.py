import json
import os

d = r"C:\Users\Administrator\Desktop\TIFS\experiment_root\analysis\synthetic\sessions"
sids = sorted(os.listdir(d))[:6]
for s in sids:
    p = os.path.join(d, s, "events.jsonl")
    ev = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    opens = [e["payload"]["path"] for e in ev if e["event_type"] == "open"]
    last = ev[-1]["monotonic_ms"]
    print(f"{s}: events={len(ev):3d} opens={len(opens):2d} distinct={len(set(opens))} "
          f"last_ms={last:9d} windows={last // 360000}")
