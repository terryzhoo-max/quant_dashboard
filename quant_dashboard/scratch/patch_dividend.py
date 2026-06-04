# -*- coding: utf-8 -*-
"""Patch dividend_optimization_results.json: add generated_at from mtime"""
import json
from datetime import datetime
from os.path import getmtime

fp = "dividend_optimization_results.json"
d = json.load(open(fp, "r", encoding="utf-8"))

mtime = datetime.fromtimestamp(getmtime(fp))

if isinstance(d, list):
    new = {
        "generated_at": mtime.isoformat(),
        "combined_score": d[0]["final_score"] if d else 0,
        "best_params": d[0]["params"] if d else {},
        "results": d,
    }
    json.dump(new, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Patched: generated_at={new['generated_at']}, combined_score={new['combined_score']}")
else:
    print(f"Already dict format, generated_at={d.get('generated_at','missing')}")
