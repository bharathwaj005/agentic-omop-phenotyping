#!/usr/bin/env python3
"""Hierarchy-aware concept metrics (secondary analysis).

Exact concept-ID matching treats a clinically adjacent choice (a parent or child
of a reference concept) as a complete miss. This script re-scores every scored
run with a tolerance of k levels in the OMOP concept_ancestor hierarchy:

  near-precision(k) = |{p in P : p is within k levels (up or down) of some r in R}| / |P|
  near-recall(k)    = |{r in R : r is within k levels (up or down) of some p in P}| / |R|

k = 0 reproduces exact matching. Results are written next to the official tables
and are NOT used in the primary analysis.

Run from the repository root:
    .venv/bin/python scripts/hierarchy_aware_metrics.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.tools.resolver import open_vocab, resolve_items

import inspect as _inspect
from src.tools.resolver import restrict_to_standard as _rts
def _std(con, ids, s):
    """Same standard-concept restriction the official scorer and reference builder apply."""
    params = list(_inspect.signature(_rts).parameters)
    kw = {p: s.get("domain") for p in params[2:] if "domain" in p}
    return set(_rts(con, ids, **kw))

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "analysis_tier1_20261028"
LEVELS = (0, 1, 2)
T10_CORRECTED_COHORT = "1025"   # see docs/ERRATA.md


def near(con, a: set[int], b: set[int], k: int) -> set[int]:
    """Members of `a` that lie within k ancestor/descendant levels of any member of `b`."""
    if not a or not b:
        return set()
    con.register("set_a", pd.DataFrame({"id": sorted(a)}))
    con.register("set_b", pd.DataFrame({"id": sorted(b)}))
    rows = con.execute(f"""
        SELECT DISTINCT a.id FROM set_a a
          JOIN concept_ancestor ca ON ca.ancestor_concept_id = a.id
          JOIN set_b b ON b.id = ca.descendant_concept_id
         WHERE ca.min_levels_of_separation <= {int(k)}
        UNION
        SELECT DISTINCT a.id FROM set_a a
          JOIN concept_ancestor ca ON ca.descendant_concept_id = a.id
          JOIN set_b b ON b.id = ca.ancestor_concept_id
         WHERE ca.min_levels_of_separation <= {int(k)}
    """).fetchall()
    con.unregister("set_a"); con.unregister("set_b")
    return {r[0] for r in rows} | (a & b)


def prf(p_hit: int, p_n: int, r_hit: int, r_n: int):
    p = p_hit / p_n if p_n else None
    r = r_hit / r_n if r_n else None
    if p is None or r is None:
        return p, r, None
    return p, r, (0.0 if p + r == 0 else 2 * p * r / (p + r))


def main() -> int:
    metrics = pd.read_csv(RES / "concept_metrics.csv")
    runs = pd.read_csv(RES / "final_runs.csv")
    scored = metrics[metrics.exact_f1.notna()].merge(
        runs[["track", "task_id", "configuration", "chosen_report"]],
        on=["track", "task_id", "configuration"])
    rows = []
    with open_vocab(read_only=True) as con:
        for _, row in scored.iterrows():
            rep = json.loads((ROOT / row.chosen_report).read_text())
            sets = rep.get("per_set") or {}
            pred: set[int] = set()
            for s in sets.values():
                pred |= _std(con, resolve_items(con, s.get("items", [])), s)
            cohort = str(rep.get("cohort_id"))
            if row.track == "v53" and row.task_id == "T10":
                cohort = T10_CORRECTED_COHORT
            ref = set(json.loads((ROOT / "tasks" / "reference_v2" / f"{cohort}.json").read_text())["all_concept_ids"])
            out = {"track": row.track, "task_id": row.task_id, "configuration": row.configuration,
                   "n_pred": len(pred), "n_ref": len(ref), "official_exact_f1": row.exact_f1}
            for k in LEVELS:
                p, r, f = prf(len(near(con, pred, ref, k)), len(pred), len(near(con, ref, pred, k)), len(ref))
                out.update({f"k{k}_precision": p, f"k{k}_recall": r, f"k{k}_f1": f})
            rows.append(out)
    df = pd.DataFrame(rows)
    df.to_csv(RES / "hierarchy_aware_metrics.csv", index=False)
    drift = (df.k0_f1 - df.official_exact_f1).abs().max()
    summary = (df.groupby(["track", "configuration"])
                 .agg(scored=("k0_f1", "count"), exact_f1=("k0_f1", "mean"),
                      k1_f1=("k1_f1", "mean"), k2_f1=("k2_f1", "mean"),
                      k1_recall=("k1_recall", "mean"), k2_recall=("k2_recall", "mean"))
                 .round(4).reset_index())
    lines = ["# Hierarchy-aware concept metrics (secondary analysis)", "",
             "k = maximum ancestor/descendant distance in `concept_ancestor` counted as a match; "
             "k = 0 is exact matching (primary analysis). Means over scored runs.", "",
             "| Track | Config | Scored | F1 (exact, k=0) | F1 (k=1) | F1 (k=2) | Recall (k=1) | Recall (k=2) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for _, s in summary.iterrows():
        lines.append(f"| {s.track.upper()} | {s.configuration} | {s.scored} | {s.exact_f1:.4f} | {s.k1_f1:.4f} | "
                     f"{s.k2_f1:.4f} | {s.k1_recall:.4f} | {s.k2_recall:.4f} |")
    lines += ["", f"Check: max |k=0 F1 − official exact F1| = {drift:.2e} (should be ~0)."]
    (RES / "hierarchy_aware_metrics.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if drift < 1e-6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
