#!/usr/bin/env python3
"""
Safe, staged OMOP/Athena vocabulary candidate builder for JBI.

This script NEVER writes to the active vocab.duckdb, reference JSONs, or
frozen benchmark queue. It builds a timestamped candidate database separately.

Usage:
  python scripts/repair_vocab_pipeline.py --stage inspect --athena-dir /path/to/unpacked_athena
  python scripts/repair_vocab_pipeline.py --stage build   --athena-dir /path/to/unpacked_athena
  python scripts/repair_vocab_pipeline.py --stage audit   --candidate-db /path/to/candidate.duckdb
  python scripts/repair_vocab_pipeline.py --stage all     --athena-dir /path/to/unpacked_athena

The full Athena archive must be obtained and unpacked by the user first.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = Path("/media/bharathwaj/HDD_Storage/project_jbi/results/benchmark_design")
DEFAULT_REFERENCE_DIR = Path("/media/bharathwaj/HDD_Storage/project_jbi/tasks/reference_raw_v2")
ACTIVE_DB = Path("/media/bharathwaj/HDD_Storage/project_jbi/data/vocab.duckdb")

TABLES = [
    "VOCABULARY", "DOMAIN", "CONCEPT_CLASS", "RELATIONSHIP", "CONCEPT",
    "CONCEPT_SYNONYM", "CONCEPT_RELATIONSHIP", "CONCEPT_ANCESTOR",
]
INT_COLUMNS = {
    "concept_id", "ancestor_concept_id", "descendant_concept_id",
    "concept_id_1", "concept_id_2", "min_levels_of_separation",
    "max_levels_of_separation",
}
# These are a diagnostic checklist, not a guarantee that every vocabulary
# is available to every Athena account or permitted for every use.
RECOMMENDED_VOCABS = {
    "SNOMED", "RxNorm", "ICD10CM", "CPT4", "HCPCS", "LOINC",
    "ICD9CM", "ICD9Proc", "ICD10PCS", "NDC", "RxNorm Extension",
    "OMOP Extension",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def find_file(root: Path, name: str) -> Path | None:
    for candidate in (f"{name}.csv", f"{name.lower()}.csv", f"{name}.CSV"):
        p = root / candidate
        if p.is_file():
            return p
    return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_source(athena_dir: Path, out_dir: Path) -> dict:
    if not athena_dir.is_dir():
        raise FileNotFoundError(f"Athena directory does not exist: {athena_dir}")

    files = {}
    missing_tables = []
    for table in TABLES:
        path = find_file(athena_dir, table)
        if path is None:
            missing_tables.append(table)
        else:
            files[table] = {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }

    vocabulary_path = find_file(athena_dir, "VOCABULARY")
    vocab_ids = []
    if vocabulary_path:
        # Athena vocabulary files are tab-separated.
        with vocabulary_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                value = row.get("vocabulary_id")
                if value:
                    vocab_ids.append(value.strip())

    present = set(vocab_ids)
    absent_recommended = sorted(RECOMMENDED_VOCABS - present)
    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "athena_dir": str(athena_dir),
        "required_table_files": files,
        "missing_required_table_files": missing_tables,
        "vocabulary_ids_found": sorted(present),
        "recommended_vocabularies_not_found": absent_recommended,
        "ready_to_build": not missing_tables and bool(vocabulary_path),
        "note": (
            "Vocabulary names are a diagnostic checklist. Absence is not "
            "automatically a failure because availability/licensing varies. "
            "The post-build compatibility audit is the actual coverage check."
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source_inventory.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    with (out_dir / "source_inventory.txt").open("w", encoding="utf-8") as f:
        f.write(f"Athena source: {athena_dir}\n")
        f.write(f"Ready to build: {report['ready_to_build']}\n\n")
        f.write("Required table files:\n")
        for table in TABLES:
            if table in files:
                f.write(f"  [OK]   {table}: {files[table]['bytes']:,} bytes\n")
            else:
                f.write(f"  [MISS] {table}.csv\n")
        f.write("\nRecommended vocabulary IDs not found:\n")
        for name in absent_recommended:
            f.write(f"  - {name}\n")
        f.write("\nThis is inventory only; no source files or databases changed.\n")
    return report


def column_names(con: duckdb.DuckDBPyConnection, csv_path: Path) -> list[str]:
    rel = con.execute(
        "SELECT * FROM read_csv(?, delim='\\t', quote='', header=true, "
        "all_varchar=true) LIMIT 0",
        [str(csv_path)],
    )
    return [d[0] for d in rel.description]


def cast_expression(col: str) -> str:
    lower = col.lower()
    quoted = '"' + col.replace('"', '""') + '"'
    src = f"nullif(trim({quoted}), '')"
    if lower.endswith("_date"):
        return f"try_strptime({src}, '%Y%m%d')::DATE AS \"{lower}\""
    if lower in INT_COLUMNS:
        return f"try_cast({src} AS BIGINT) AS \"{lower}\""
    return f"{src} AS \"{lower}\""


def build_candidate(athena_dir: Path, candidate_db: Path, out_dir: Path) -> dict:
    if candidate_db.resolve() == ACTIVE_DB.resolve():
        raise RuntimeError("Refusing to write to the active vocabulary database.")
    if not athena_dir.is_dir():
        raise FileNotFoundError(f"Athena directory does not exist: {athena_dir}")

    missing = [t for t in TABLES if find_file(athena_dir, t) is None]
    if missing:
        raise RuntimeError(
            "Cannot build candidate; required CSV files are missing: "
            + ", ".join(missing)
            + ". Inspect the full Athena extraction first."
        )

    candidate_db.parent.mkdir(parents=True, exist_ok=True)
    if candidate_db.exists():
        raise FileExistsError(
            f"Candidate database already exists; refusing to overwrite: {candidate_db}"
        )

    started = time.time()
    con = duckdb.connect(str(candidate_db))
    rows = {}
    try:
        # Process sequentially to reduce memory pressure on the 8 GB laptop.
        for table_name in TABLES:
            csv_path = find_file(athena_dir, table_name)
            assert csv_path is not None
            cols = column_names(con, csv_path)
            select_list = ",\n".join(cast_expression(c) for c in cols)
            table = table_name.lower()
            print(f"[BUILD] {table_name}: {csv_path.stat().st_size / 1e6:,.1f} MB")
            con.execute(
                f'CREATE TABLE "{table}" AS SELECT {select_list} '
                "FROM read_csv(?, delim='\\t', quote='', header=true, "
                "all_varchar=true)",
                [str(csv_path)],
            )
            n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            rows[table] = n
            print(f"        {n:,} rows")

        existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "concept_ancestor" in existing:
            print("[BUILD] descendant_count helper")
            con.execute("""
                CREATE TABLE descendant_count AS
                SELECT ancestor_concept_id AS concept_id, count(*) - 1 AS n_descendants
                FROM concept_ancestor GROUP BY 1
            """)
        if "concept" in existing:
            print("[BUILD] concept_search helper")
            if "concept_synonym" in existing:
                syn_sql = """
                    UNION ALL
                    SELECT s.concept_id, lower(s.concept_synonym_name) AS term
                    FROM concept_synonym s
                    JOIN concept c ON c.concept_id = s.concept_id
                    WHERE c.standard_concept = 'S' AND c.invalid_reason IS NULL
                """
            else:
                syn_sql = ""
            con.execute(f"""
                CREATE TABLE concept_search AS
                SELECT concept_id, lower(concept_name) AS term
                FROM concept
                WHERE standard_concept = 'S' AND invalid_reason IS NULL
                {syn_sql}
            """)
        # Indexes are optional performance aids; skip if a source table lacks a column.
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
                cols = {r[0] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()}
                if col in cols:
                    try:
                        con.execute(f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{table}"("{col}")')
                    except Exception as e:
                        print(f"[WARN] Index {idx} skipped: {e}")
        # Basic structural validation.
        required = {"vocabulary", "concept", "concept_relationship", "concept_ancestor"}
        missing_built = sorted(required - tables_now)
        if missing_built:
            raise RuntimeError(f"Candidate is missing required tables: {missing_built}")
        vocab_rows = con.execute(
            "SELECT vocabulary_id, vocabulary_name, vocabulary_version FROM vocabulary ORDER BY vocabulary_id"
        ).fetchall()
        concept_n = con.execute("SELECT count(*) FROM concept").fetchone()[0]
        report = {
            "created_at": datetime.now().astimezone().isoformat(),
            "source_dir": str(athena_dir),
            "candidate_db": str(candidate_db),
            "active_db_untouched": str(ACTIVE_DB),
            "table_rows": rows,
            "concept_rows": concept_n,
            "vocabulary_rows": [
                {"vocabulary_id": r[0], "vocabulary_name": r[1], "vocabulary_version": r[2]}
                for r in vocab_rows
            ],
            "elapsed_seconds": round(time.time() - started, 2),
            "status": "BUILD_OK",
        }
    finally:
        con.close()

    (out_dir / "candidate_build_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def run_audit(candidate_db: Path, out_dir: Path, reference_dir: Path) -> int:
    if candidate_db.resolve() == ACTIVE_DB.resolve():
        raise RuntimeError("Refusing to audit active DB as a candidate.")
    audit_script = PROJECT_ROOT / "scripts" / "jbi_vocab_compatibility_audit.py"
    if not audit_script.is_file():
        raise FileNotFoundError(f"Audit script not found: {audit_script}")
    if not reference_dir.is_dir():
        raise FileNotFoundError(f"Reference directory not found: {reference_dir}")
    audit_root = out_dir / "compatibility_audit"
    cmd = [
        sys.executable, str(audit_script),
        "--db", str(candidate_db),
        "--reference-dir", str(reference_dir),
        "--out-root", str(audit_root),
    ]
    print("[AUDIT] Running compatibility audit against candidate database:")
    print("        " + " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    (out_dir / "audit_exit_code.txt").write_text(
        f"{completed.returncode}\n", encoding="utf-8"
    )
    if completed.returncode != 0:
        print(f"[FAIL] Audit exited with code {completed.returncode}")
    else:
        print("[OK] Audit completed. Review its summary before approving the candidate.")
    return completed.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Safely build and audit a separate Athena vocabulary DB.")
    ap.add_argument("--stage", choices=["inspect", "build", "audit", "all"], required=True)
    ap.add_argument(
        "--athena-dir", type=Path,
        help="Directory containing the newly downloaded/unpacked Athena TSV CSV files.",
    )
    ap.add_argument("--candidate-db", type=Path, help="Candidate DuckDB path for build/audit.")
    ap.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = ap.parse_args()

    run_dir = args.out_root / f"VOCAB_REPAIR_PIPELINE_{stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "RUN_INFO.txt").write_text(
        f"stage={args.stage}\nstarted={datetime.now().astimezone().isoformat()}\n"
        f"active_db_protected={ACTIVE_DB}\n",
        encoding="utf-8",
    )
    print(f"[INFO] Run reports: {run_dir}")
    print(f"[INFO] Active DB protected: {ACTIVE_DB}")

    try:
        if args.stage in {"inspect", "build", "all"}:
            if not args.athena_dir:
                raise ValueError("--athena-dir is required for inspect/build/all.")
            source_report = inspect_source(args.athena_dir.resolve(), run_dir)
            print(f"[INSPECT] Required files complete: {source_report['ready_to_build']}")
            print(f"[INSPECT] Inventory: {run_dir / 'source_inventory.txt'}")
            if args.stage == "inspect":
                return 0 if source_report["ready_to_build"] else 2
            if not source_report["ready_to_build"]:
                raise RuntimeError(
                    "Source inventory failed. No candidate database was built. "
                    "Check source_inventory.txt."
                )
            candidate = args.candidate_db
            if candidate is None:
                candidate = (
                    args.out_root / "candidate_databases" /
                    f"vocab_candidate_{stamp()}.duckdb"
                )
            candidate = candidate.resolve()
            build_report = build_candidate(args.athena_dir.resolve(), candidate, run_dir)
            print(f"[BUILD] Candidate: {candidate}")
            print(f"[BUILD] Concepts: {build_report['concept_rows']:,}")
            print(f"[BUILD] Report: {run_dir / 'candidate_build_report.json'}")
        else:
            if not args.candidate_db:
                raise ValueError("--candidate-db is required for audit.")
            candidate = args.candidate_db.resolve()
            if not candidate.is_file():
                raise FileNotFoundError(f"Candidate DB does not exist: {candidate}")

        if args.stage in {"audit", "all"}:
            rc = run_audit(candidate, run_dir, args.reference_dir.resolve())
            if rc != 0:
                return rc
            print("\n[REVIEW REQUIRED] No database activation or reference regeneration was performed.")
        return 0
    except Exception as exc:
        (run_dir / "ERROR.txt").write_text(
            f"{type(exc).__name__}: {exc}\n", encoding="utf-8"
        )
        print(f"[STOP SAFE] {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[INFO] See: {run_dir / 'ERROR.txt'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
