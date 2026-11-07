#!/usr/bin/env python3
"""Build a clinician review sheet for the generated concept sets.

For every scored run of the chosen configurations, list
  * MATCHED concepts (in prediction and reference, up to --max-matched),
  * PREDICTED_ONLY concepts (in prediction, not in reference)  -> "was this a wrong concept?"
  * MISSED concepts (in reference, not predicted, up to --max-missed) -> "is this omission important?"
with concept names, so two raters can mark each row independently.

Output: docs/review/review_sheet.csv  (rater columns are left blank)
Score agreement afterwards with scripts/review_agreement.py.

    .venv/bin/python scripts/make_review_sheet.py --configs C1,C2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.tools.resolver import open_vocab, resolve_items

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "analysis_tier1_20261028"


def names(con, ids):
    if not ids:
        return {}
    con.register("ids", pd.DataFrame({"id": sorted(ids)}))
    out = dict(con.execute("SELECT c.concept_id, c.concept_name || ' [' || c.domain_id || ']' "
                           "FROM concept c JOIN ids ON ids.id = c.concept_id").fetchall())
    con.unregister("ids")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="C1,C2")
    ap.add_argument("--max-matched", type=int, default=10)
    ap.add_argument("--max-missed", type=int, default=25)
    a = ap.parse_args()
    configs = a.configs.split(",")
    metrics = pd.read_csv(RES / "concept_metrics.csv")
    runs = pd.read_csv(RES / "final_runs.csv")
    scored = metrics[metrics.exact_f1.notna() & metrics.configuration.isin(configs)].merge(
        runs[["track", "task_id", "configuration", "chosen_report"]], on=["track", "task_id", "configuration"])
    rows = []
    with open_vocab(read_only=True) as con:
        for _, r in scored.sort_values(["track", "task_id", "configuration"]).iterrows():
            rep = json.loads((ROOT / r.chosen_report).read_text())
            pred = set()
            for s in (rep.get("per_set") or {}).values():
                pred |= resolve_items(con, s.get("items", []))
            cohort = "1025" if (r.track == "v53" and r.task_id == "T10") else str(rep.get("cohort_id"))
            ref = set(json.loads((ROOT / "tasks" / "reference_v2" / f"{cohort}.json").read_text())["all_concept_ids"])
            groups = [("MATCHED", sorted(pred & ref)[: a.max_matched]),
                      ("PREDICTED_ONLY", sorted(pred - ref)),
                      ("MISSED", sorted(ref - pred)[: a.max_missed])]
            nm = names(con, {c for _, g in groups for c in g})
            for side, ids in groups:
                for cid in ids:
                    rows.append({"track": r.track, "task_id": r.task_id, "configuration": r.configuration,
                                 "side": side, "concept_id": cid, "concept_name": nm.get(cid, "?"),
                                 "rater_1": "", "rater_2": "", "notes": ""})
    out = ROOT / "docs" / "review"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "review_sheet.csv", index=False)
    (out / "README.md").write_text(
        "# Clinician review sheet\n\n"
        "Each row is one concept from a scored run. Two raters fill `rater_1` and `rater_2` independently:\n\n"
        "- `MATCHED` / `PREDICTED_ONLY`: **A** = clinically appropriate for the phenotype, **I** = inappropriate, **U** = unsure\n"
        "- `MISSED`: **E** = essential omission, **M** = minor omission, **U** = unsure\n\n"
        "Then run `python scripts/review_agreement.py docs/review/review_sheet.csv` for Cohen's kappa.\n"
        "Use only the generated concept sets; do not share patient data in this sheet.\n")
    print(f"wrote {len(rows)} rows to {out / 'review_sheet.csv'}")


if __name__ == "__main__":
    main()
