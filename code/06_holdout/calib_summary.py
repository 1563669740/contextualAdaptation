import glob
import json
import os

for f in sorted(glob.glob(r"C:\Users\Administrator\Desktop\TIFS\dataset\holdout_tests\_calibration\python-babel__*.json")):
    d = json.load(open(f, encoding="utf-8"))
    v = (d.get("verdict") or {}).get("oracle_reproduced")
    bw = d.get("base_without_gold") or {}
    bg = d.get("base_with_gold") or {}
    print(f"{os.path.basename(f)[:-5]:32s} oracle={v}  base_rc={bw.get('rc')} "
          f"({bw.get('summary')})  gold_rc={bg.get('rc')} ({bg.get('summary')})  "
          f"gold_files={len(d.get('gold_files') or [])}")
