"""Build a candidate list for task selection.

Joins Phenotype Library metadata (Cohorts.csv) with the parsed expressions from
extract_reference.py, assigns a complexity tier, flags which definitions our
compiler can execute, and counts how many Eunomia persons each entry concept
set would capture (using Eunomia's own ancestor table).

Runs WITHOUT the Athena vocabulary, so P3/P4 can select tasks immediately.

Output: HDD/tasks/candidates.csv

Usage:
    python -m src.eval.candidates
    python -m src.eval.candidates --min-eunomia 50    # only executable ones
"""

from __future__ import annotations

import argparse
import json
import sys

import duckdb
import pandas as pd

from src import paths


def load_parsed() -> pd.DataFrame:
    raw_dir = paths.TASKS_DIR / "reference_raw"
    if not raw_dir.exists():
        raise FileNotFoundError(
            f"{raw_dir} not found. Run: python -m src.eval.extract_reference"
        )
    rows = []
    for f in sorted(raw_dir.glob("*.json")):
        d = json.loads(f.read_text())
        entry = d["concept_sets"].get(d["entry_codeset_id"], {})
        items = entry.get("items", [])
        rows.append({
            "cohort_id": int(d["cohort_id"]),
            "entry_set_name": entry.get("name", ""),
            "entry_domain": d.get("entry_domain"),
            "n_entry_items": len(items),
            "n_entry_excluded": sum(1 for i in items if i["is_excluded"]),
            "any_descendants": any(i["include_descendants"] for i in items),
            "any_mapped": any(i["include_mapped"] for i in items),
            "n_concept_sets": d["n_concept_sets"],
            "n_inclusion_rules": d["n_inclusion_rules"],
            "n_primary_criteria": d["n_primary_criteria"],
            "multi_domain_entry": len(d.get("entry_domains", [])) > 1,
            "entry_concept_ids": [i["concept_id"] for i in items
                                  if not i["is_excluded"]],
        })
    return pd.DataFrame(rows)


def load_metadata() -> pd.DataFrame:
    csv = paths.PHENOTYPE_LIBRARY / "PhenotypeLibrary" / "inst" / "Cohorts.csv"
    meta = pd.read_csv(csv, low_memory=False)
    keep = ["cohortId", "cohortName", "status", "logicDescription", "hashTag"]
    keep = [c for c in keep if c in meta.columns]
    meta = meta[keep].rename(columns={"cohortId": "cohort_id",
                                      "cohortName": "cohort_name"})
    return meta


def complexity(row) -> str:
    """Three tiers, based on how much structure the definition carries."""
    if row["multi_domain_entry"] or row["n_inclusion_rules"] >= 2 \
            or row["n_concept_sets"] >= 3:
        return "complex"
    if row["n_inclusion_rules"] == 1 or row["n_concept_sets"] == 2 \
            or row["n_entry_excluded"] > 0:
        return "medium"
    return "simple"


def compiler_supported(row) -> bool:
    """Does our simplified cohort spec cover this definition's structure?"""
    return (not row["multi_domain_entry"]
            and row["n_inclusion_rules"] <= 2
            and row["n_concept_sets"] <= 3
            and row["entry_domain"] in ("Condition", "Drug"))


def eunomia_counts(df: pd.DataFrame) -> pd.Series:
    """Persons in Eunomia captured by each entry concept set (approximate).

    Uses Eunomia's OWN small vocabulary, so this is a lower bound -- it only
    tells us which phenotypes are worth executing there.
    """
    if not paths.EUNOMIA_DB.exists():
        return pd.Series([0] * len(df), index=df.index)

    con = duckdb.connect(paths.EUNOMIA_DB.as_posix(), read_only=True)
    counts = []
    try:
        for _, row in df.iterrows():
            ids = row["entry_concept_ids"]
            if not ids:
                counts.append(0)
                continue
            ph = ",".join("?" * len(ids))
            table, col = (("condition_occurrence", "condition_concept_id")
                          if row["entry_domain"] == "Condition"
                          else ("drug_exposure", "drug_concept_id"))
            try:
                n = con.execute(
                    f"""
                    WITH expanded AS (
                        SELECT DISTINCT descendant_concept_id AS cid
                        FROM concept_ancestor
                        WHERE ancestor_concept_id IN ({ph})
                        UNION
                        SELECT unnest(?::BIGINT[]) AS cid
                    )
                    SELECT count(DISTINCT t.person_id)
                    FROM {table} t JOIN expanded e ON e.cid = t.{col}
                    """,
                    list(ids) + [list(ids)],
                ).fetchone()[0]
            except duckdb.Error:
                n = 0
            counts.append(int(n))
    finally:
        con.close()
    return pd.Series(counts, index=df.index)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-eunomia", type=int, default=0,
                    help="keep only rows with at least this many Eunomia persons")
    args = ap.parse_args()

    parsed = load_parsed()
    meta = load_metadata()
    df = parsed.merge(meta, on="cohort_id", how="left")

    df["complexity"] = df.apply(complexity, axis=1)
    df["compiler_supported"] = df.apply(compiler_supported, axis=1)
    print("counting Eunomia coverage ...")
    df["eunomia_persons"] = eunomia_counts(df)
    df["eunomia_evaluable"] = df["eunomia_persons"] >= 20

    if args.min_eunomia:
        df = df[df["eunomia_persons"] >= args.min_eunomia]

    df = df.drop(columns=["entry_concept_ids"])
    df = df.sort_values(["complexity", "eunomia_persons"],
                        ascending=[True, False])

    out = paths.TASKS_DIR / "candidates.csv"
    df.to_csv(out, index=False)

    print(f"\ncandidates: {len(df):,}  ->  {out}\n")
    print("BY COMPLEXITY")
    print(df["complexity"].value_counts().to_string())
    print("\nCOMPILER-SUPPORTED BY COMPLEXITY")
    print(pd.crosstab(df["complexity"], df["compiler_supported"]).to_string())
    print(f"\nEUNOMIA-EVALUABLE (>=20 persons): {int(df['eunomia_evaluable'].sum())}")
    cols = ["cohort_id", "cohort_name", "complexity", "n_entry_items",
            "eunomia_persons"]
    top = df[df["eunomia_evaluable"]][cols].head(20)
    if len(top):
        print("\nTOP EUNOMIA-EVALUABLE CANDIDATES")
        print(top.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
