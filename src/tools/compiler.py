"""The compiler: cohort specification -> SQL.

Deterministic, with no LLM involvement. This is the pivot of the architecture:
agents argue about *what* the cohort means, and this module decides *how* it is
computed. Because it is deterministic, two identical specifications always give
identical SQL and identical patients, which is what makes the reproducibility
metric meaningful.

Concept sets are referenced as temporary tables named cs_<set name>, created by
the executor before the query runs. Keeping the ID lists out of the SQL text
means the query stays short even when a set holds thousands of concepts.
"""

from __future__ import annotations

import re

from src.schema.spec import CohortSpec

# domain -> (table, concept column, date column)
DOMAIN_TABLES = {
    "Condition": ("condition_occurrence", "condition_concept_id",
                  "condition_start_date"),
    "Drug": ("drug_exposure", "drug_concept_id", "drug_exposure_start_date"),
    "Procedure": ("procedure_occurrence", "procedure_concept_id",
                  "procedure_date"),
    "Measurement": ("measurement", "measurement_concept_id", "measurement_date"),
    "Observation": ("observation", "observation_concept_id", "observation_date"),
    "Visit": ("visit_occurrence", "visit_concept_id", "visit_start_date"),
    "Device": ("device_exposure", "device_concept_id", "device_exposure_start_date"),
}

_SAFE = re.compile(r"[^a-z0-9_]")


def temp_table_name(concept_set_name: str) -> str:
    """Map a concept set name to a safe temp table name.

    Agents choose these names, so they are sanitised rather than trusted.
    """
    safe = _SAFE.sub("_", concept_set_name.strip().lower())
    return f"cs_{safe or 'unnamed'}"


class CompileError(ValueError):
    """The specification cannot be turned into SQL."""


def compile_spec(spec: CohortSpec) -> str:
    """Return the SQL for a cohort specification."""
    # 1. Entry events: every entry arm is an alternative (OR), including
    # alternatives that use different OMOP domains/tables.
    event_selects = []
    for arm in spec.entry_arms:
        entry_name = arm.concept_set
        if arm.event_domain not in DOMAIN_TABLES:
            raise CompileError(f"unsupported entry domain {arm.event_domain!r}")
        table, concept_col, date_col = DOMAIN_TABLES[arm.event_domain]
        entry_tbl = temp_table_name(entry_name)
        event_selects.append(
            f"SELECT t.person_id, t.{date_col} AS event_date "
            f"FROM {table} t "
            f"JOIN {entry_tbl} s ON s.concept_id = t.{concept_col} "
            f"WHERE t.{date_col} IS NOT NULL"
        )
    if not event_selects:
        raise CompileError("at least one entry concept set is required")
    events = "\n    events AS (\n        " + "\n        UNION ALL\n        ".join(event_selects) + "\n    )"

    if spec.first_occurrence_only:
        entry_cte = """
    entry AS (
        SELECT person_id, min(event_date) AS index_date
        FROM events GROUP BY person_id
    )"""
    else:
        entry_cte = """
    entry AS (
        SELECT DISTINCT person_id, event_date AS index_date FROM events
    )"""

    # 2. demographic and observation qualification
    quals = [
        "op.observation_period_start_date <= e.index_date",
        "op.observation_period_end_date >= e.index_date",
    ]
    if spec.prior_observation_days > 0:
        quals.append(
            "datediff('day', op.observation_period_start_date, e.index_date) "
            f">= {int(spec.prior_observation_days)}"
        )
    if spec.age_min is not None:
        quals.append(
            f"(year(e.index_date) - p.year_of_birth) >= {int(spec.age_min)}")
    if spec.age_max is not None:
        quals.append(
            f"(year(e.index_date) - p.year_of_birth) <= {int(spec.age_max)}")

    qualified = f"""
    qualified AS (
        SELECT e.person_id, e.index_date
        FROM entry e
        JOIN person p ON p.person_id = e.person_id
        JOIN observation_period op ON op.person_id = e.person_id
        WHERE {' AND '.join(quals)}
    )"""

    # 3. inclusion / exclusion criteria
    conditions = []
    for i, crit in enumerate(spec.criteria):
        cs = spec.concept_sets.get(crit.concept_set)
        if cs is None:
            raise CompileError(
                f"criterion {i} references unknown concept set "
                f"{crit.concept_set!r}")
        if cs.domain not in DOMAIN_TABLES:
            raise CompileError(
                f"criterion {i} uses unsupported domain {cs.domain!r}")
        c_table, c_concept, c_date = DOMAIN_TABLES[cs.domain]
        c_tbl = temp_table_name(crit.concept_set)
        exists = f"""(
            SELECT 1 FROM {c_table} x
            JOIN {c_tbl} cs ON cs.concept_id = x.{c_concept}
            WHERE x.person_id = q.person_id
              AND datediff('day', q.index_date, x.{c_date})
                  BETWEEN {int(crit.window_start_days)}
                      AND {int(crit.window_end_days)}
        )"""
        keyword = "EXISTS" if crit.rule == "at_least_one" else "NOT EXISTS"
        conditions.append(f"{keyword} {exists}")

    where = ("WHERE " + "\n          AND ".join(conditions)) if conditions else ""

    return f"""
WITH{events},{entry_cte},{qualified}
SELECT q.person_id, q.index_date
FROM qualified q
{where}
ORDER BY q.person_id
""".strip()


def required_temp_tables(spec: CohortSpec) -> dict[str, str]:
    """Concept set name -> temp table name, for every set the SQL needs."""
    needed = set(spec.entry_concept_sets)
    needed |= {c.concept_set for c in spec.criteria}
    return {n: temp_table_name(n) for n in sorted(needed)}


if __name__ == "__main__":
    from src.schema.spec import ConceptItem, ConceptSet, Criterion

    demo = CohortSpec(
        entry_concept_set="peptic_ulcer",
        age_min=18,
        prior_observation_days=365,
        concept_sets={
            "peptic_ulcer": ConceptSet(
                name="peptic_ulcer", domain="Condition",
                description="peptic ulcer disease",
                items=[ConceptItem(concept_id=4027663, rationale="entry")]),
            "nsaid": ConceptSet(
                name="nsaid", domain="Drug", description="NSAIDs",
                items=[ConceptItem(concept_id=1177480, rationale="ibuprofen")]),
        },
        criteria=[Criterion(concept_set="nsaid", window_start_days=-90,
                            window_end_days=0, rule="at_least_one")],
    )
    print(compile_spec(demo))
    print("\ntemp tables:", required_temp_tables(demo))
