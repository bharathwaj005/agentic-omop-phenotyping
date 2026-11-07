"""Component 3 tests: compiler, validator, executor.

Builds a tiny OMOP CDM where every expected cohort is worked out by hand, so a
wrong SQL join or an off-by-one window is caught immediately.

PATIENTS
  1  born 1970, male,   observation 2010-01-01 .. 2020-12-31
       peptic ulcer   2015-06-01  and  2016-06-01   (two events)
       ibuprofen      2015-05-15  (17 days before first ulcer)
  2  born 2010, female, observation 2015-01-01 .. 2020-12-31
       gastric ulcer  2018-03-01                      (child: fails age>=18)
  3  born 1980, female, observation 2017-01-01 .. 2020-12-31
       duodenal ulcer 2017-02-01   (only 32 days of prior observation)
  4  born 1960, male,   observation 2000-01-01 .. 2020-12-31
       peptic ulcer   2019-01-01
       no ibuprofen
  5  born 1990, male,   observation 2010-01-01 .. 2020-12-31
       motion sickness only -- never in any ulcer cohort

Run:  python -m tests.test_component3
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import duckdb

from src.schema.spec import CohortSpec, ConceptItem, ConceptSet, Criterion
from src.tools.compiler import CompileError, compile_spec, temp_table_name
from src.tools.executor import execute, try_execute
from src.tools.validator import validate, validate_execution

passed = failed = 0


def check(name: str, fn):
    global passed, failed
    try:
        fn()
        print(f"  [pass] {name}")
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        failed += 1
    except Exception as e:                               # noqa: BLE001
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        failed += 1


# 100 peptic ulcer > {110 gastric, 120 duodenal}; 300 ibuprofen; 200 motion sickness
CONCEPTS = [
    (100, "Peptic ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (110, "Gastric ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (120, "Duodenal ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (200, "Motion sickness", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (300, "Ibuprofen", "Drug", "RxNorm", "Ingredient", "S", None),
    (400, "ASA source code", "Drug", "NDC", "Source Code", None, None),
    (500, "Deprecated ulcer", "Condition", "SNOMED", "Clinical Finding", "S", "D"),
]
PERSONS = [
    (1, 8507, 1970), (2, 8532, 2010), (3, 8532, 1980),
    (4, 8507, 1960), (5, 8507, 1990),
]
OBS = [
    (1, "2010-01-01", "2020-12-31"), (2, "2015-01-01", "2020-12-31"),
    (3, "2017-01-01", "2020-12-31"), (4, "2000-01-01", "2020-12-31"),
    (5, "2010-01-01", "2020-12-31"),
]
CONDITIONS = [
    (1, 100, "2015-06-01"), (1, 100, "2016-06-01"),
    (2, 110, "2018-03-01"), (3, 120, "2017-02-02"),
    (4, 100, "2019-01-01"), (5, 200, "2012-01-01"),
]
DRUGS = [(1, 300, "2015-05-15")]


def build_cdm(path: Path) -> None:
    con = duckdb.connect(path.as_posix())
    con.execute("""CREATE TABLE concept(concept_id BIGINT, concept_name VARCHAR,
        domain_id VARCHAR, vocabulary_id VARCHAR, concept_class_id VARCHAR,
        standard_concept VARCHAR, invalid_reason VARCHAR)""")
    con.executemany("INSERT INTO concept VALUES (?,?,?,?,?,?,?)", CONCEPTS)

    con.execute("""CREATE TABLE person(person_id BIGINT,
        gender_concept_id BIGINT, year_of_birth INT)""")
    con.executemany("INSERT INTO person VALUES (?,?,?)", PERSONS)

    con.execute("""CREATE TABLE observation_period(person_id BIGINT,
        observation_period_start_date DATE, observation_period_end_date DATE)""")
    con.executemany("INSERT INTO observation_period VALUES (?,?::DATE,?::DATE)",
                    OBS)

    con.execute("""CREATE TABLE condition_occurrence(person_id BIGINT,
        condition_concept_id BIGINT, condition_start_date DATE)""")
    con.executemany("INSERT INTO condition_occurrence VALUES (?,?,?::DATE)",
                    CONDITIONS)

    con.execute("""CREATE TABLE drug_exposure(person_id BIGINT,
        drug_concept_id BIGINT, drug_exposure_start_date DATE)""")
    con.executemany("INSERT INTO drug_exposure VALUES (?,?,?::DATE)", DRUGS)
    con.close()


def ulcer_spec(**kw) -> CohortSpec:
    base = dict(
        entry_concept_set="ulcer",
        concept_sets={
            "ulcer": ConceptSet(name="ulcer", domain="Condition",
                                description="peptic ulcer disease",
                                items=[ConceptItem(concept_id=100,
                                                   rationale="entry event")]),
        },
    )
    base.update(kw)
    return CohortSpec(**base)


ULCER_IDS = {"ulcer": {100, 110, 120}}          # peptic ulcer with descendants


# --- compiler ---------------------------------------------------------------

def t_compile_basic():
    sql = compile_spec(ulcer_spec())
    assert "condition_occurrence" in sql
    assert "cs_ulcer" in sql
    assert "min(event_date)" in sql


def t_compile_all_events():
    sql = compile_spec(ulcer_spec(first_occurrence_only=False))
    assert "min(event_date)" not in sql and "DISTINCT" in sql


def t_compile_drug_entry():
    spec = CohortSpec(
        entry_concept_set="ibu",
        concept_sets={"ibu": ConceptSet(name="ibu", domain="Drug",
                                        description="ibuprofen",
                                        items=[ConceptItem(concept_id=300,
                                                           rationale="ibuprofen ingredient")])})
    sql = compile_spec(spec)
    assert "drug_exposure" in sql and "drug_exposure_start_date" in sql


def t_temp_name_sanitised():
    assert temp_table_name("NSAIDs; DROP TABLE person") == \
        "cs_nsaids__drop_table_person"


def t_compile_rejects_bad_domain():
    spec = ulcer_spec()
    spec.entry_arms[0].event_domain = "Demographic"       # unsupported event table
    try:
        compile_spec(spec)
    except CompileError:
        return
    raise AssertionError("should refuse an unsupported domain")


# --- executor ---------------------------------------------------------------

def t_exec_basic(con):
    r = execute(con, ulcer_spec(), ULCER_IDS)
    assert r.persons == [1, 2, 3, 4], r.persons
    assert str(r.index_dates[0]) == "2015-06-01", r.index_dates[0]


def t_exec_first_occurrence(con):
    r = execute(con, ulcer_spec(), ULCER_IDS)
    assert len(r.persons) == len(set(r.persons)), "first occurrence -> 1 row pp"
    r2 = execute(con, ulcer_spec(first_occurrence_only=False), ULCER_IDS)
    assert r2.persons.count(1) == 2, "all events -> patient 1 appears twice"


def t_exec_age_filter(con):
    r = execute(con, ulcer_spec(age_min=18), ULCER_IDS)
    assert 2 not in r.persons, "patient 2 was 8 at index"
    assert set(r.persons) == {1, 3, 4}, r.persons


def t_exec_prior_observation(con):
    r = execute(con, ulcer_spec(prior_observation_days=365), ULCER_IDS)
    assert 3 not in r.persons, "patient 3 had only 32 days of prior data"
    assert set(r.persons) == {1, 2, 4}, r.persons


def t_exec_combined(con):
    r = execute(con, ulcer_spec(age_min=18, prior_observation_days=365),
                ULCER_IDS)
    assert set(r.persons) == {1, 4}, r.persons


def t_exec_inclusion_criterion(con):
    """Ulcer patients with ibuprofen in the 90 days before index -> only 1."""
    spec = ulcer_spec(
        concept_sets={
            "ulcer": ConceptSet(name="ulcer", domain="Condition",
                                description="ulcer",
                                items=[ConceptItem(concept_id=100,
                                                   rationale="entry")]),
            "nsaid": ConceptSet(name="nsaid", domain="Drug",
                                description="ibuprofen",
                                items=[ConceptItem(concept_id=300,
                                                   rationale="nsaid")]),
        },
        criteria=[Criterion(concept_set="nsaid", window_start_days=-90,
                            window_end_days=0, rule="at_least_one")],
    )
    r = execute(con, spec, {**ULCER_IDS, "nsaid": {300}})
    assert r.persons == [1], r.persons


def t_exec_exclusion_criterion(con):
    spec = ulcer_spec(
        concept_sets={
            "ulcer": ConceptSet(name="ulcer", domain="Condition",
                                description="ulcer",
                                items=[ConceptItem(concept_id=100,
                                                   rationale="entry")]),
            "nsaid": ConceptSet(name="nsaid", domain="Drug",
                                description="ibuprofen",
                                items=[ConceptItem(concept_id=300,
                                                   rationale="nsaid")]),
        },
        criteria=[Criterion(concept_set="nsaid", window_start_days=-90,
                            window_end_days=0, rule="none")],
    )
    r = execute(con, spec, {**ULCER_IDS, "nsaid": {300}})
    assert r.persons == [2, 3, 4], r.persons


def t_exec_window_boundary(con):
    """Ibuprofen is 17 days before index: a -17..0 window includes it,
    a -16..0 window does not. Catches off-by-one errors."""
    def with_window(start):
        spec = ulcer_spec(
            concept_sets={
                "ulcer": ConceptSet(name="ulcer", domain="Condition",
                                    description="peptic ulcer",
                                    items=[ConceptItem(concept_id=100,
                                                       rationale="entry event")]),
                "nsaid": ConceptSet(name="nsaid", domain="Drug",
                                    description="nsaid drugs",
                                    items=[ConceptItem(concept_id=300,
                                                       rationale="nsaid exposure")]),
            },
            criteria=[Criterion(concept_set="nsaid", window_start_days=start,
                                window_end_days=0)],
        )
        return execute(con, spec, {**ULCER_IDS, "nsaid": {300}}).persons

    assert with_window(-17) == [1], with_window(-17)
    assert with_window(-16) == [], with_window(-16)


def t_exec_empty_set(con):
    r = execute(con, ulcer_spec(), {"ulcer": set()})
    assert r.persons == [] and r.summary["cohort_size"] == 0


def t_exec_summary_fields(con):
    r = execute(con, ulcer_spec(), ULCER_IDS)
    s = r.summary
    assert s["cohort_size"] == 4
    assert s["age_mean"] is not None
    assert set(s["sex"]) <= {"male", "female"}
    text = r.to_text()
    assert "cohort_size: 4" in text


def t_exec_small_cell_suppression(con):
    """Patient 3 is the only person with a duodenal-ulcer-only cohort;
    counts under 5 must be masked."""
    spec = ulcer_spec()
    r = execute(con, spec, {"ulcer": {120}})
    assert r.summary["cohort_size"] == 1
    assert all(v == "<5" for v in r.summary["sex"].values()), r.summary["sex"]


def t_try_execute_bad_sql(con):
    spec = ulcer_spec()
    spec.entry_arms[0].event_domain = "Demographic"
    result, err = try_execute(con, spec, ULCER_IDS)
    assert result is None and err is not None, (result, err)


# --- validator --------------------------------------------------------------

def t_validate_clean(con):
    res = validate(ulcer_spec(), vocab_con=con, resolved=ULCER_IDS)
    assert res.passed, res.to_text()


def t_validate_missing_concept(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=999999, rationale="made up")]
    res = validate(spec, vocab_con=con)
    assert not res.passed
    assert any(i.code == "concept_not_found" for i in res.errors)


def t_validate_non_standard(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=400, rationale="source code")]
    res = validate(spec, vocab_con=con)
    assert any(i.code == "concept_not_standard" for i in res.errors), res.to_text()


def t_validate_invalid_concept(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=500, rationale="deprecated")]
    res = validate(spec, vocab_con=con)
    assert any(i.code == "concept_invalid" for i in res.errors)


def t_validate_domain_mismatch(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=300, rationale="a drug in a condition set")]
    res = validate(spec, vocab_con=con)
    assert any(i.code == "domain_mismatch" for i in res.errors)


def t_validate_empty_entry_set(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = []
    res = validate(spec, vocab_con=con)
    assert any(i.code == "empty_concept_set" and i.level == "error"
               for i in res.issues)


def t_validate_only_exclusions(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=100, is_excluded=True, rationale="excluded")]
    res = validate(spec, vocab_con=con)
    assert any(i.code == "only_exclusions" for i in res.errors)


def t_validate_duplicate_warning(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items = [
        ConceptItem(concept_id=100, rationale="first listing"),
        ConceptItem(concept_id=100, rationale="second listing"),
    ]
    res = validate(spec, vocab_con=con)
    assert any(i.code == "duplicate_concept" for i in res.warnings)
    assert res.passed, "duplicates are a warning, not an error"


def t_validate_broad_warning(con):
    res = validate(ulcer_spec(), vocab_con=con,
                   resolved={"ulcer": set(range(1, 3000))})
    assert any(i.code == "very_broad_set" for i in res.warnings)


def t_validate_entry_resolves_empty(con):
    res = validate(ulcer_spec(), vocab_con=con, resolved={"ulcer": set()})
    assert any(i.code == "entry_set_resolves_empty" for i in res.errors)


def t_validate_single_entry_without_descendants_warns(con):
    spec = ulcer_spec()
    spec.concept_sets["ulcer"].items[0].include_descendants = False
    res = validate(spec, vocab_con=con, resolved={"ulcer": {100}})
    assert any(
        i.code == "possibly_too_narrow"
        and i.level == "warning"
        and "descendants were not requested" in i.message
        for i in res.warnings
    ), res.to_text()
    assert res.passed, "narrowness should warn, not block"


def t_validate_execution_empty():
    res = validate_execution(0)
    assert any(i.code == "empty_cohort" for i in res.warnings)
    assert validate_execution(42).issues == []


def main() -> int:
    print("COMPILER")
    for name, fn in [
        ("basic condition cohort", t_compile_basic),
        ("all events mode", t_compile_all_events),
        ("drug entry event", t_compile_drug_entry),
        ("temp table name sanitised", t_temp_name_sanitised),
        ("rejects unsupported domain", t_compile_rejects_bad_domain),
    ]:
        check(name, fn)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cdm.duckdb"
        build_cdm(db)
        con = duckdb.connect(db.as_posix())
        try:
            print("\nEXECUTOR")
            for name, fn in [
                ("basic cohort membership", t_exec_basic),
                ("first occurrence vs all events", t_exec_first_occurrence),
                ("age filter", t_exec_age_filter),
                ("prior observation filter", t_exec_prior_observation),
                ("age + observation combined", t_exec_combined),
                ("inclusion criterion", t_exec_inclusion_criterion),
                ("exclusion criterion", t_exec_exclusion_criterion),
                ("window boundary off-by-one", t_exec_window_boundary),
                ("empty concept set", t_exec_empty_set),
                ("summary fields", t_exec_summary_fields),
                ("small cell suppression", t_exec_small_cell_suppression),
                ("bad sql handled", t_try_execute_bad_sql),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nVALIDATOR")
            for name, fn in [
                ("clean spec passes", t_validate_clean),
                ("missing concept", t_validate_missing_concept),
                ("non-standard concept", t_validate_non_standard),
                ("invalid concept", t_validate_invalid_concept),
                ("domain mismatch", t_validate_domain_mismatch),
                ("empty entry set", t_validate_empty_entry_set),
                ("only exclusions", t_validate_only_exclusions),
                ("duplicate is a warning", t_validate_duplicate_warning),
                ("very broad set warning", t_validate_broad_warning),
                ("entry resolves empty", t_validate_entry_resolves_empty),
                ("single entry without descendants warns",
                 t_validate_single_entry_without_descendants_warns),
            ]:
                check(name, lambda f=fn: f(con))
            check("empty cohort warning", t_validate_execution_empty)
        finally:
            con.close()

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
