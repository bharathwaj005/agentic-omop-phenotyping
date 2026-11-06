"""Sanity-check the loaded databases. Run this after every load.

Usage:
    python -m src.db.verify
"""

from __future__ import annotations

import sys

import duckdb

from src import paths

# A well-known SNOMED concept used as a smoke test.
TEST_CONCEPT = 313217          # Atrial fibrillation
TEST_NAME_FRAGMENT = "atrial fibrillation"


def check_vocab() -> bool:
    if not paths.VOCAB_DB.exists():
        print(f"[--] vocabulary database not found at {paths.VOCAB_DB}")
        return False

    con = duckdb.connect(paths.VOCAB_DB.as_posix(), read_only=True)
    ok = True
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        print(f"Vocabulary DB: {paths.VOCAB_DB}")
        print(f"  tables: {', '.join(sorted(tables))}\n")

        for t in ("concept", "concept_ancestor", "concept_search",
                  "descendant_count"):
            if t in tables:
                n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                print(f"  {t:<20} {n:>12,} rows")
            else:
                print(f"  {t:<20} MISSING")
                ok = False

        # Dates must have parsed, not be NULL everywhere
        if "concept" in tables:
            bad = con.execute(
                "SELECT count(*) FROM concept WHERE valid_start_date IS NULL"
            ).fetchone()[0]
            total = con.execute("SELECT count(*) FROM concept").fetchone()[0]
            print(f"\n  concepts with unparsed valid_start_date: {bad:,} / {total:,}")
            if total and bad / total > 0.01:
                print("  WARNING: many dates failed to parse -- check the format")
                ok = False

            row = con.execute(
                "SELECT concept_name, domain_id, vocabulary_id, standard_concept "
                "FROM concept WHERE concept_id = ?", [TEST_CONCEPT]
            ).fetchone()
            print(f"\n  smoke test, concept {TEST_CONCEPT}: {row}")
            if row is None:
                print("  NOTE: test concept absent -- fine if SNOMED was not loaded")

        if {"concept_ancestor", "concept"} <= tables:
            n_desc = con.execute(
                "SELECT count(*) FROM concept_ancestor WHERE ancestor_concept_id = ?",
                [TEST_CONCEPT],
            ).fetchone()[0]
            print(f"  descendants of {TEST_CONCEPT}: {n_desc:,}")

        if "concept_search" in tables:
            hits = con.execute(
                "SELECT count(DISTINCT concept_id) FROM concept_search "
                "WHERE term LIKE ?", [f"%{TEST_NAME_FRAGMENT}%"]
            ).fetchone()[0]
            print(f"  search hits for '{TEST_NAME_FRAGMENT}': {hits:,}")
    finally:
        con.close()
    return ok


def check_eunomia() -> bool:
    if not paths.EUNOMIA_DB.exists():
        print(f"\n[--] Eunomia database not found at {paths.EUNOMIA_DB}")
        return False

    con = duckdb.connect(paths.EUNOMIA_DB.as_posix(), read_only=True)
    ok = True
    try:
        print(f"\nEunomia DB: {paths.EUNOMIA_DB}")
        for t in ("person", "observation_period", "condition_occurrence",
                  "drug_exposure"):
            try:
                n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                print(f"  {t:<24} {n:>10,} rows")
            except duckdb.Error:
                print(f"  {t:<24} MISSING")
                ok = False

        try:
            row = con.execute(
                "SELECT min(condition_start_date), max(condition_start_date) "
                "FROM condition_occurrence"
            ).fetchone()
            print(f"  condition date range: {row[0]} .. {row[1]}")
            if row[0] is None:
                print("  WARNING: dates are NULL -- date coercion failed")
                ok = False
        except duckdb.Error as exc:
            print(f"  date check failed: {exc}")
            ok = False
    finally:
        con.close()
    return ok


def main() -> int:
    vocab_ok = check_vocab()
    eunomia_ok = check_eunomia()
    print("\n" + "=" * 52)
    print(f"vocabulary: {'OK' if vocab_ok else 'NOT READY'}")
    print(f"eunomia   : {'OK' if eunomia_ok else 'NOT READY'}")
    return 0 if (vocab_ok and eunomia_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
