"""The executor: runs compiled SQL against the CDM and returns AGGREGATES ONLY.

Privacy by construction. The LLM never sees a patient row -- only counts and
distributions, with small cells suppressed. The data here is synthetic, so the
suppression is not strictly needed, but it demonstrates a design that transfers
unchanged to a real hospital database. That is the governance claim in the
paper, implemented rather than asserted.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

import duckdb

from src import paths
from src.schema.spec import CohortSpec
from src.tools.compiler import compile_spec, required_temp_tables

SMALL_CELL = 5          # counts below this are reported as "<5"
TOP_N = 10

GENDER = {8507: "male", 8532: "female"}


@contextmanager
def open_cdm(read_only: bool = True):
    """Open the CDM database (Eunomia)."""
    if not paths.EUNOMIA_DB.exists():
        raise FileNotFoundError(
            f"{paths.EUNOMIA_DB} not found. Run: python -m src.db.load_eunomia")
    con = duckdb.connect(paths.EUNOMIA_DB.as_posix(), read_only=read_only)
    try:
        con.execute(f"SET threads={paths.DUCKDB_THREADS}")
        yield con
    finally:
        con.close()


def suppress(n: int) -> str:
    return f"<{SMALL_CELL}" if 0 < n < SMALL_CELL else str(n)


def create_concept_tables(con, spec: CohortSpec,
                          resolved: dict[str, set[int]]) -> None:
    """Materialise each concept set as a temp table of concept ids."""
    for set_name, table in required_temp_tables(spec).items():
        ids = resolved.get(set_name, set())
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TEMP TABLE {table}(concept_id BIGINT)")
        if ids:
            con.executemany(f"INSERT INTO {table} VALUES (?)",
                            [(int(i),) for i in sorted(ids)])


class ExecutionResult:
    def __init__(self, persons: list[int], index_dates: list,
                 summary: dict, sql: str):
        self.persons = persons
        self.index_dates = index_dates
        self.summary = summary
        self.sql = sql

    @property
    def size(self) -> int:
        return len(self.persons)

    def to_text(self) -> str:
        """Compact summary for the Critic prompt -- aggregates only."""
        s = self.summary
        lines = [f"cohort_size: {s['cohort_size']}"]
        if s["cohort_size"] == 0:
            lines.append("no patients matched")
            return "\n".join(lines)
        lines.append(f"age_at_index: mean {s['age_mean']} sd {s['age_sd']} "
                     f"range {s['age_min']}-{s['age_max']}")
        lines.append("sex: " + ", ".join(f"{k} {v}" for k, v in s["sex"].items()))
        lines.append(f"index_date_range: {s['index_min']} .. {s['index_max']}")
        if s["top_conditions"]:
            lines.append("top conditions in 30d before index:")
            for name, n in s["top_conditions"]:
                lines.append(f"  {name}: {n}")
        if s["top_drugs"]:
            lines.append("top drugs in 30d before index:")
            for name, n in s["top_drugs"]:
                lines.append(f"  {name}: {n}")
        return "\n".join(lines)


def _top_context(con, table: str, concept_col: str, date_col: str
                 ) -> list[tuple[str, str]]:
    """Most common co-occurring concepts shortly before index."""
    try:
        rows = con.execute(
            f"""
            SELECT COALESCE(c.concept_name, 'concept ' || t.{concept_col})
                     AS name,
                   count(DISTINCT t.person_id) AS n
            FROM cohort_result r
            JOIN {table} t ON t.person_id = r.person_id
            LEFT JOIN concept c ON c.concept_id = t.{concept_col}
            WHERE datediff('day', r.index_date, t.{date_col}) BETWEEN -30 AND 0
            GROUP BY 1 ORDER BY n DESC LIMIT {TOP_N}
            """
        ).fetchall()
    except duckdb.Error:
        return []
    return [(r[0], suppress(int(r[1]))) for r in rows]


def execute(con, spec: CohortSpec, resolved: dict[str, set[int]],
            with_context: bool = True) -> ExecutionResult:
    """Compile, run, and summarise. Raises duckdb.Error on a bad query."""
    sql = compile_spec(spec)
    create_concept_tables(con, spec, resolved)

    con.execute("DROP TABLE IF EXISTS cohort_result")
    con.execute(f"CREATE TEMP TABLE cohort_result AS {sql}")

    rows = con.execute(
        "SELECT person_id, index_date FROM cohort_result ORDER BY person_id"
    ).fetchall()
    persons = [int(r[0]) for r in rows]
    dates = [r[1] for r in rows]

    summary: dict = {"cohort_size": len(persons)}
    if not persons:
        summary.update({"age_mean": None, "age_sd": None, "age_min": None,
                        "age_max": None, "sex": {}, "index_min": None,
                        "index_max": None, "top_conditions": [],
                        "top_drugs": []})
        return ExecutionResult(persons, dates, summary, sql)

    stats = con.execute(
        """
        SELECT round(avg(year(r.index_date) - p.year_of_birth), 1),
               round(stddev_samp(year(r.index_date) - p.year_of_birth), 1),
               min(year(r.index_date) - p.year_of_birth),
               max(year(r.index_date) - p.year_of_birth),
               min(r.index_date), max(r.index_date)
        FROM cohort_result r JOIN person p ON p.person_id = r.person_id
        """
    ).fetchone()
    summary.update({
        "age_mean": stats[0], "age_sd": stats[1],
        "age_min": stats[2], "age_max": stats[3],
        "index_min": str(stats[4]), "index_max": str(stats[5]),
    })

    sex_rows = con.execute(
        """
        SELECT p.gender_concept_id, count(*)
        FROM cohort_result r JOIN person p ON p.person_id = r.person_id
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    summary["sex"] = {GENDER.get(int(g), f"concept {g}"): suppress(int(n))
                      for g, n in sex_rows}

    if with_context:
        summary["top_conditions"] = _top_context(
            con, "condition_occurrence", "condition_concept_id",
            "condition_start_date")
        summary["top_drugs"] = _top_context(
            con, "drug_exposure", "drug_concept_id", "drug_exposure_start_date")
    else:
        summary["top_conditions"] = []
        summary["top_drugs"] = []

    return ExecutionResult(persons, dates, summary, sql)


def try_execute(con, spec: CohortSpec, resolved: dict[str, set[int]]
                ) -> tuple[Optional[ExecutionResult], Optional[str]]:
    """Execute, returning (result, error_message). Never raises.

    A failed query should cost the agent one turn, not the whole run.
    """
    try:
        return execute(con, spec, resolved), None
    except duckdb.Error as e:
        return None, f"SQL error: {e}"
    except Exception as e:                               # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
