#!/usr/bin/env python3
"""Summarise an ADN-track run directory with the same dual-denominator rules as the paper.

    python scripts/analyze_adn_track.py results/adn_runs/qwen7b_YYYYMMDD
"""
import json
import sys
from pathlib import Path

import pandas as pd

run_dir = Path(sys.argv[1])
rows = []
for rep_path in sorted(run_dir.glob("A*_C*/report.json")):
    if rep_path.parent.name.endswith("_retry1"):
        continue
    rep = json.loads(rep_path.read_text())
    full = ((rep.get("metrics") or {}).get("v2") or {}).get("full") or {}
    p, r, f1 = full.get("precision"), full.get("recall"), full.get("f1")
    if f1 is None and p == 0 and r == 0 and rep.get("status") == "success":
        f1 = 0.0                      # zero-overlap runs count as F1 = 0 (paper's scoring rule)
    rows.append({"task_id": rep["task_id"], "configuration": rep["configuration"], "status": rep.get("status"),
                 "f1": f1, "precision": p if f1 is not None else None, "recall": r if f1 is not None else None,
                 "wall_seconds": rep.get("wall_seconds")})
df = pd.DataFrame(rows)
if df.empty:
    raise SystemExit(f"no reports found in {run_dir}")
n_tasks = df.task_id.nunique()
summary = []
for cfg, g in df.groupby("configuration"):
    sc = g[g.f1.notna()]
    summary.append({"Config": cfg, "Scored": f"{len(sc)} / {n_tasks}",
                    "Mean F1 (Scored)": f"{sc.f1.mean():.4f} ± {sc.f1.std():.3f}" if len(sc) else "n/a",
                    "Mean F1 (All=0)": f"{g.f1.fillna(0).sum() / n_tasks:.4f}",
                    "Mean Recall": f"{sc.recall.mean():.4f}" if len(sc) else "n/a",
                    "Mean Precision": f"{sc.precision.mean():.4f}" if len(sc) else "n/a",
                    "Median seconds": f"{g.wall_seconds.median():.0f}"})
s = pd.DataFrame(summary)
df.to_csv(run_dir / "adn_runs.csv", index=False)
s.to_csv(run_dir / "adn_summary.csv", index=False)
md = "| " + " | ".join(s.columns) + " |\n| " + " | ".join("---" for _ in s.columns) + " |\n"
md += "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in s.values) + "\n"
(run_dir / "adn_summary.md").write_text(md)
print(md)
