"""Load the Eunomia synthetic OMOP dataset (GiBleed) into DuckDB.

Eunomia ships as plain CSVs. Column types are auto-detected, then any column
whose name ends in _date is coerced to DATE so the compiler can do date maths.

Usage:
    python -m src.db.load_eunomia
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

from src import paths

# Clinical tables the compiler and executor need. Others are loaded too if
# present, but these are the ones we check for.
REQUIRED = [
    "person",
    "observation_period",
    "condition_occurrence",
    "drug_exposure",
]


def find_csv_dir() -> Path | None:
    """The zip may unpack into a subfolder; find the folder holding PERSON.csv."""
    root = paths.EUNOMIA_RAW
    if not root.exists():
        return None
    for candidate in [root, *[d for d in root.rglob("*") if d.is_dir()]]:
        names = {p.name.lower() for p in candidate.glob("*.csv")}
        if "person.csv" in names:
            return candidate
    return None


def load_csv(con: duckdb.DuckDBPyConnection, csv: Path) -> int:
    table = csv.stem.lower()
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(
        f"""
        CREATE TABLE {table} AS
        SELECT * FROM read_csv('{csv.as_posix()}', header=true,
                               auto_detect=true, sample_size=-1)
        """
    )
    # Coerce *_date columns to DATE (some arrive as VARCHAR or TIMESTAMP)
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ?", [table]
    ).fetchall()
    for col, dtype in cols:
        if col.lower().endswith("_date") and dtype.upper() != "DATE":
            con.execute(
                f'ALTER TABLE {table} ALTER COLUMN "{col}" '
                f'SET DATA TYPE DATE USING try_cast("{col}" AS DATE)'
            )
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def main() -> int:
    paths.ensure_dirs()
    csv_dir = find_csv_dir()
    if csv_dir is None:
        print(f"ERROR: no person.csv found under {paths.EUNOMIA_RAW}")
        print("Unzip the Eunomia download there first.")
        return 1

    print(f"Source : {csv_dir}")
    print(f"Target : {paths.EUNOMIA_DB}\n")

    con = duckdb.connect(paths.EUNOMIA_DB.as_posix())
    paths.configure(con)
    start = time.time()
    loaded = {}
    try:
        for csv in sorted(csv_dir.glob("*.csv")):
            try:
                rows = load_csv(con, csv)
                loaded[csv.stem.lower()] = rows
                print(f"  [ok]   {csv.stem.lower():<28} {rows:>10,} rows")
            except Exception as exc:                      # noqa: BLE001
                print(f"  [fail] {csv.stem.lower():<28} {exc}")

        missing = [t for t in REQUIRED if t not in loaded]
        print()
        if missing:
            print(f"WARNING: required tables missing: {', '.join(missing)}")
        else:
            print("All required clinical tables present.")
        print(f"Done in {time.time() - start:,.0f}s.")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
