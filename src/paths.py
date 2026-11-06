"""Central path configuration.

Every script imports paths from here. Nothing is hardcoded, so the same code
runs on the Linux laptop, on a borrowed Windows machine, or anywhere else.
Paths come from the .env file in the project root.

Layout rule:
  - Local SSD  -> code, venv, DuckDB files (needs speed, locking, permissions)
  - HDD (exFAT)-> raw downloads, tasks, runs, results, backups
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)


def _require(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Create {_ENV_FILE} (copy .env.example) and set it."
        )
    return Path(value).expanduser().resolve()


# --- roots -----------------------------------------------------------------
PROJECT_ROOT = _require("PROJECT_ROOT")   # local SSD working copy
HDD_ROOT = _require("HDD_ROOT")           # external drive

# --- local (SSD): fast, writable, never on exFAT ---------------------------
DATA_DIR = PROJECT_ROOT / "data"
TMP_DIR = DATA_DIR / "tmp"
VOCAB_DB = DATA_DIR / "vocab.duckdb"
EUNOMIA_DB = DATA_DIR / "eunomia.duckdb"

# --- HDD: bulk storage and transport ---------------------------------------
ATHENA_RAW = HDD_ROOT / "athena_raw"              # unzipped Athena CSVs
EUNOMIA_RAW = HDD_ROOT / "eunomia_raw"            # unzipped Eunomia CSVs
PHENOTYPE_LIBRARY = HDD_ROOT / "phenotype_library"
TASKS_DIR = HDD_ROOT / "tasks"
REFERENCE_DIR = TASKS_DIR / "reference"
TASKS_FILE = TASKS_DIR / "tasks.jsonl"
RUNS_DIR = HDD_ROOT / "runs"
RESULTS_DIR = HDD_ROOT / "results"
BACKUP_DIR = HDD_ROOT / "backups"

# --- DuckDB settings tuned for 8 GB RAM ------------------------------------
DUCKDB_MEMORY_LIMIT = os.environ.get("DUCKDB_MEMORY_LIMIT", "3GB")
DUCKDB_THREADS = int(os.environ.get("DUCKDB_THREADS", "4"))


def ensure_dirs() -> None:
    """Create the directories that must exist before anything runs."""
    for d in (DATA_DIR, TMP_DIR, TASKS_DIR, REFERENCE_DIR, RUNS_DIR,
              RESULTS_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def configure(con) -> None:
    """Apply memory-safe settings to a DuckDB connection."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    con.execute(f"SET threads={DUCKDB_THREADS}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{TMP_DIR.as_posix()}'")


if __name__ == "__main__":
    ensure_dirs()
    print(f"PROJECT_ROOT : {PROJECT_ROOT}")
    print(f"HDD_ROOT     : {HDD_ROOT}")
    print(f"vocab.duckdb : {VOCAB_DB}")
    print(f"athena_raw   : {ATHENA_RAW}  exists={ATHENA_RAW.exists()}")
    print(f"eunomia_raw  : {EUNOMIA_RAW}  exists={EUNOMIA_RAW.exists()}")
    print("Directories ready.")
