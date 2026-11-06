"""Load the OMOP vocabulary (Athena download) into DuckDB.

Athena CSVs are tab-delimited, have a header, use NO quote character, and store
dates as YYYYMMDD. Each table is loaded in its own connection so memory is
released between tables -- important on an 8 GB machine.

Usage:
    python -m src.db.load_vocab                 # load everything
    python -m src.db.load_vocab --limit 5000    # quick test on a subset
    python -m src.db.load_vocab --only CONCEPT CONCEPT_ANCESTOR
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from src import paths

# Tables we need. CONCEPT_SYNONYM helps search; DRUG_STRENGTH is not needed.
TABLES = [
    "VOCABULARY",
    "DOMAIN",
    "CONCEPT_CLASS",
    "RELATIONSHIP",
    "CONCEPT",
    "CONCEPT_SYNONYM",
    "CONCEPT_RELATIONSHIP",
    "CONCEPT_ANCESTOR",
]

INT_COLUMNS = {
    "concept_id", "ancestor_concept_id", "descendant_concept_id",
    "concept_id_1", "concept_id_2",
    "min_levels_of_separation", "max_levels_of_separation",
}


def find_csv(name: str) -> Path | None:
    """Athena files are usually NAME.csv, but be tolerant of case."""
    for candidate in (f"{name}.csv", f"{name.lower()}.csv", f"{name}.CSV"):
        p = paths.ATHENA_RAW / candidate
        if p.exists():
            return p
    return None


def column_names(con: duckdb.DuckDBPyConnection, csv: Path) -> list[str]:
    """Read the header only, as text, to discover column names."""
    rel = con.execute(
        "SELECT * FROM read_csv(?, delim='\t', quote='', header=true, "
        "all_varchar=true) LIMIT 0",
        [csv.as_posix()],
    )
    return [d[0] for d in rel.description]


def cast_expression(col: str) -> str:
    """Build a SQL expression casting a raw text column to its proper type."""
    lower = col.lower()
    src = f'nullif(trim("{col}"), \'\')'
    if lower.endswith("_date"):
        # Athena stores dates as YYYYMMDD text
        return f"try_strptime({src}, '%Y%m%d')::DATE AS {lower}"
    if lower in INT_COLUMNS:
        return f"try_cast({src} AS BIGINT) AS {lower}"
    return f"{src} AS {lower}"


def load_table(name: str, limit: int | None) -> int:
    csv = find_csv(name)
    if csv is None:
        print(f"  [skip] {name}.csv not found in {paths.ATHENA_RAW}")
        return 0

    con = duckdb.connect(paths.VOCAB_DB.as_posix())
    paths.configure(con)
    try:
        cols = column_names(con, csv)
        select_list = ",\n       ".join(cast_expression(c) for c in cols)
        limit_sql = f" LIMIT {limit}" if limit else ""
        table = name.lower()

        start = time.time()
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(
            f"""
            CREATE TABLE {table} AS
            SELECT {select_list}
            FROM read_csv('{csv.as_posix()}', delim='\t', quote='',
                          header=true, all_varchar=true){limit_sql}
            """
        )
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        size_mb = csv.stat().st_size / 1e6
        print(f"  [ok]   {table:<22} {rows:>12,} rows  "
              f"({size_mb:,.0f} MB source, {time.time() - start:,.0f}s)")
        return rows
    finally:
        con.close()


def build_helpers() -> None:
    """Precompute tables that make later queries fast and cheap."""
    con = duckdb.connect(paths.VOCAB_DB.as_posix())
    paths.configure(con)
    try:
        existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}

        if "concept_ancestor" in existing:
            print("  building descendant_count ...")
            con.execute("DROP TABLE IF EXISTS descendant_count")
            con.execute(
                """
                CREATE TABLE descendant_count AS
                SELECT ancestor_concept_id AS concept_id,
                       count(*) - 1 AS n_descendants
                FROM concept_ancestor
                GROUP BY 1
                """
            )

        if "concept" in existing:
            print("  building concept_search ...")
            # One row per searchable name (primary name + synonyms), lowercased.
            has_syn = "concept_synonym" in existing
            syn_sql = (
                """
                UNION ALL
                SELECT s.concept_id, lower(s.concept_synonym_name) AS term
                FROM concept_synonym s
                JOIN concept c ON c.concept_id = s.concept_id
                WHERE c.standard_concept = 'S' AND c.invalid_reason IS NULL
                """
                if has_syn else ""
            )
            con.execute("DROP TABLE IF EXISTS concept_search")
            con.execute(
                f"""
                CREATE TABLE concept_search AS
                SELECT concept_id, lower(concept_name) AS term
                FROM concept
                WHERE standard_concept = 'S' AND invalid_reason IS NULL
                {syn_sql}
                """
            )

        print("  creating indexes ...")
        index_specs = [
            ("idx_concept_id", "concept", "concept_id"),
            ("idx_ca_ancestor", "concept_ancestor", "ancestor_concept_id"),
            ("idx_ca_descendant", "concept_ancestor", "descendant_concept_id"),
            ("idx_cs_term", "concept_search", "term"),
            ("idx_cs_concept", "concept_search", "concept_id"),
            ("idx_cr_1", "concept_relationship", "concept_id_1"),
        ]
        tables_now = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for idx, table, col in index_specs:
            if table in tables_now:
                con.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {table}({col})")
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Load Athena vocabulary into DuckDB")
    ap.add_argument("--limit", type=int, default=None,
                    help="rows per table (for a quick test run)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="load only these tables")
    args = ap.parse_args()

    paths.ensure_dirs()
    if not paths.ATHENA_RAW.exists():
        print(f"ERROR: {paths.ATHENA_RAW} does not exist. "
              "Unzip the Athena download there first.")
        return 1

    tables = args.only if args.only else TABLES
    print(f"Source : {paths.ATHENA_RAW}")
    print(f"Target : {paths.VOCAB_DB}")
    if args.limit:
        print(f"TEST MODE: {args.limit} rows per table")
    print()

    start = time.time()
    for name in tables:
        load_table(name, args.limit)

    if not args.limit:
        build_helpers()

    print(f"\nDone in {(time.time() - start) / 60:,.1f} min. "
          f"Database: {paths.VOCAB_DB}")
    if args.limit:
        print("This was a TEST load. Re-run without --limit for the full load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
