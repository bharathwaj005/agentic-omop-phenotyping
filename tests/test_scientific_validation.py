"""Synthetic tests for independent scientific diagnostics."""
import duckdb
from types import SimpleNamespace

from src.metrics.evaluation import RunRecord, set_metrics, summarize_runs
from src.schema.spec import CohortSpec, ConceptItem, ConceptSet, Criterion
from src.scientific_validation import (
    analyze_records, assess_artifact, interpret_cohort_size, reconciliation_rows,
    write_release,
)
from src.tools.compiler import compile_spec, temp_table_name
from src.tools.resolver import resolve_items, restrict_to_standard
from src.runner import experiment
from src.runner.experiment import C1, run_experiment


def make_spec(*, first=True):
    return CohortSpec(
        question="synthetic question", entry_concept_set="entry",
        first_occurrence_only=first,
        prior_observation_days=3,
        concept_sets={
            "entry": ConceptSet(name="entry", domain="Condition", description="entry condition",
                                items=[ConceptItem(concept_id=10, rationale="synthetic entry")]),
            "include": ConceptSet(name="include", domain="Drug", description="drug evidence",
                                  items=[ConceptItem(concept_id=20, rationale="synthetic inclusion")]),
            "exclude": ConceptSet(name="exclude", domain="Condition", description="exclude condition",
                                  items=[ConceptItem(concept_id=30, rationale="synthetic exclusion")]),
        },
        criteria=[Criterion(concept_set="include", window_start_days=-2, window_end_days=0),
                  Criterion(concept_set="exclude", window_start_days=0, window_end_days=0, rule="none")],
    )


def test_hand_calculated_metrics_and_duplicates():
    m = set_metrics([1, 2, 2, 9], [1, 2, 3])
    assert (m.precision, m.recall, m.f1, m.jaccard) == (2/3, 2/3, 2/3, 0.5)
    assert set_metrics([], []).jaccard is None
    assert set_metrics([], [1]).precision is None
    assert set_metrics([], [1]).recall == 0
    assert set_metrics([1], []).precision == 0
    assert set_metrics([1], []).recall is None
    disjoint = set_metrics([1], [2])
    assert disjoint.precision == 0 and disjoint.recall == 0 and disjoint.jaccard == 0
    # Historical implementation leaves the 0/0 harmonic mean missing; many
    # reporting conventions define this case as F1=0. Preserve and disclose it.
    assert disjoint.f1 == 0.0  # zero overlap scores F1 = 0 (docs/ERRATA.md E2)


def test_vocabulary_validity_standard_domain_and_relationship_missing():
    con = duckdb.connect(":memory:")
    con.execute("create table concept(concept_id bigint, domain_id varchar, standard_concept varchar, invalid_reason varchar)")
    con.execute("create table concept_ancestor(ancestor_concept_id bigint, descendant_concept_id bigint)")
    con.executemany("insert into concept values (?, ?, ?, ?)", [
        (10, "Condition", "S", None), (20, "Condition", None, None),
        (30, "Condition", "S", "D"),
    ])
    spec = make_spec()
    # Drug set deliberately mismatches the vocabulary row. Modify item ID to a nonstandard row.
    spec.concept_sets["include"].items[0].concept_id = 20
    spec.concept_sets["exclude"].items[0].concept_id = 30
    report = assess_artifact(spec, vocab_con=con)
    assert report.structural_validity is True
    assert any("nonstandard" in e for e in report.vocabulary_issues)
    assert any("invalid" in e for e in report.vocabulary_issues)
    assert any("Condition!=Drug" in e for e in report.domain_issues)
    assert "CLINICALLY_ADJUDICATED" not in report.grades
    con.close()


def test_resolver_descendants_exclusions_and_standard_filtering():
    con = duckdb.connect(":memory:")
    con.execute("create table concept_ancestor(ancestor_concept_id bigint, descendant_concept_id bigint)")
    con.execute("create table concept(concept_id bigint, standard_concept varchar, invalid_reason varchar)")
    con.execute("insert into concept_ancestor values (1,1),(1,2),(1,3),(4,4),(4,2)")
    con.execute("insert into concept values (1,'S',NULL),(2,'S',NULL),(3,NULL,NULL),(4,'S','D')")
    result = resolve_items(con, [
        {"concept_id": 1, "include_descendants": True},
        {"concept_id": 3, "include_descendants": False},
        {"concept_id": 2, "include_descendants": False, "is_excluded": True},
    ])
    # Exclusions subtract after all inclusions, and duplicates collapse in the set.
    assert result == {1, 3}
    assert restrict_to_standard(con, {1, 2, 3, 4}) == {1, 2}
    con.close()


def test_missing_concept_and_missing_hierarchy_are_not_conflated():
    con = duckdb.connect(":memory:")
    con.execute("create table concept(concept_id bigint, domain_id varchar, standard_concept varchar, invalid_reason varchar)")
    con.execute("create table concept_ancestor(ancestor_concept_id bigint, descendant_concept_id bigint)")
    con.execute("insert into concept values (10, 'Condition', 'S', NULL)")
    report = assess_artifact(make_spec(), vocab_con=con)
    assert any(":missing" in issue for issue in report.vocabulary_issues)
    # Absence of descendants for a valid concept is not falsely called invalid.
    assert not any("hierarchy" in issue for issue in report.vocabulary_issues)
    con.execute("drop table concept_ancestor")
    no_hierarchy = assess_artifact(make_spec(), vocab_con=con)
    assert any("descendant expansion cannot be checked" in limitation
               for limitation in no_hierarchy.provenance_limitations)
    assert "VOCABULARY_VALIDATED" not in no_hierarchy.grades


def test_temporal_description_inclusive_and_zero_cohort_is_not_failure():
    report = assess_artifact(make_spec())
    assert report.temporal_rules["criteria"][0]["boundaries_inclusive_in_current_compiler"]
    assert "NOT" not in str(report.temporal_rules["criteria"][1])
    assert interpret_cohort_size(0) == "ZERO_PATIENTS_REQUIRES_DATA_AND_LOGIC_REVIEW"


def test_reference_denominators_version_and_missing_patients():
    spec = make_spec()
    report = assess_artifact(spec, {"predicted_concepts": [1, 2]},
                             reference={"concept_ids": [1, 2]}, reference_version="v1")
    assert report.reference_metrics is None
    assert "COMPARISON_INCOMPARABLE" in report.grades
    matched = assess_artifact(spec, {"predicted_concepts": [1, 2]},
                              reference={"concept_ids": [1, 3], "reference_version": "v1"},
                              reference_version="v1")
    assert matched.reference_metrics["jaccard"] == 1/3
    assert matched.metric_denominators == {"predicted_unique_concepts": 2, "reference_unique_concepts": 2}


def test_reference_v2_union_scoring_scope_must_match():
    reference = {"reference_version": "v2", "all_concept_ids": [1, 2, 3],
                 "entry_concept_ids": [1, 2]}
    full = assess_artifact(make_spec(), {"predicted_concepts": [1, 2, 3],
                                         "scoring_scope": "full"},
                           reference=reference, reference_version="v2")
    assert full.reference_metrics["jaccard"] == 1
    mismatch = assess_artifact(make_spec(), {"predicted_concepts": [1, 2, 3],
                                             "scoring_scope": "entry"},
                               reference=reference, reference_version="v2")
    assert mismatch.reference_metrics["jaccard"] == 2/3
    assert mismatch.metric_denominators["reference_unique_concepts"] == 2


def test_reference_is_evaluator_side_and_not_mutated():
    spec = make_spec()
    reference = {"concept_ids": [10], "reference_version": "v1", "comparable_patient_ids": [5]}
    before = dict(reference)
    report = assess_artifact(spec, {"status": "success"}, reference=reference,
                             reference_version="v1")
    assert reference == before
    assert "COMPARISON_INCOMPARABLE" in report.grades
    assert report.execution_status == "success"


def test_reference_never_enters_generation_pipeline(monkeypatch):
    class Task:
        task_id = "SYN"
        question = "blinded synthetic question"

    gold = {"private_concept_ids": [111, 222]}
    received = {}

    def fake_pipeline(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(status="success", reason=None, resolved={}, spec=None,
                               tracker=None, execution=None, critic_rounds=0,
                               validator_retries=0, unresolved=[])

    monkeypatch.setattr(experiment, "run_multi_agent", fake_pipeline)
    result = run_experiment([Task()], [C1], client=object(), vocab_con=object(),
                            reference_loader=lambda _task_id: gold)
    assert "reference" not in received
    assert gold not in received.values()
    assert result.records[0].metadata["reference_supplied"] is True


def test_patient_overlap_requires_ids_and_matching_namespace():
    spec = make_spec()
    reference = {"concept_ids": [10], "reference_version": "v1",
                 "comparable_patient_ids": [7, 8], "patient_id_namespace": "eunomia:abc"}
    record = {"predicted_concepts": [10], "predicted_patient_ids": [8, 9],
              "patient_id_namespace": "eunomia:abc", "predicted_patient_count": 2}
    report = assess_artifact(spec, record, reference=reference, reference_version="v1")
    assert report.patient_set_jaccard == 1 / 3
    assert report.metric_denominators["predicted_unique_patients"] == 2
    assert report.cohort_size_interpretation == "NONZERO_COHORT_REQUIRES_SANITY_REVIEW"
    no_namespace = assess_artifact(
        spec, {"predicted_patient_ids": [8]}, reference=reference, reference_version="v1")
    assert no_namespace.patient_set_jaccard is None
    assert any("namespace evidence unavailable" in s for s in no_namespace.provenance_limitations)
    empty = assess_artifact(spec, {"predicted_patient_count": 0})
    assert empty.cohort_size_interpretation == "ZERO_PATIENTS_REQUIRES_DATA_AND_LOGIC_REVIEW"


def test_macro_aggregation_keeps_metric_specific_denominators_and_failed_rows():
    rows = [
        RunRecord("a", "cfg", "success", concept_precision=1.0, concept_recall=1.0),
        RunRecord("b", "cfg", "failed", concept_precision=None, concept_recall=0.0),
    ]
    summary = summarize_runs(rows)
    assert summary["n_runs"] == 2 and summary["n_failed"] == 1
    assert summary["concept_precision"]["n"] == 1
    assert summary["concept_recall"]["n"] == 2
    assert summary["concept_precision"]["mean"] == 1.0
    assert summary["concept_recall"]["mean"] == 0.5


def test_macro_values_differ_from_micro_and_remain_explicit():
    rows = [
        RunRecord("a", "cfg", "success", concept_precision=1, concept_recall=1,
                  concept_f1=1, concept_jaccard=1),
        RunRecord("b", "cfg", "success", concept_precision=1/3, concept_recall=1,
                  concept_f1=0.5, concept_jaccard=1/3),
    ]
    summary = summarize_runs(rows)
    assert summary["concept_precision"]["mean"] == 2/3  # macro
    assert summary["concept_f1"]["mean"] == 0.75  # macro; pooled micro F1 would be 2/3


def test_self_comparison_is_only_a_metric_sanity_check():
    same = [1, 2, 3]
    metrics = set_metrics(same, same)
    assert (metrics.precision, metrics.recall, metrics.f1, metrics.jaccard) == (1, 1, 1, 1)
    report = assess_artifact(make_spec(), {"predicted_concepts": same},
                             reference={"concept_ids": same, "reference_version": "v1",
                                        "reference_sha256": "abc"},
                             reference_version="v1")
    assert report.reference_metrics["jaccard"] == 1
    assert "CLINICAL_VALIDITY_UNVERIFIED" == report.acceptance["clinical_review"]


def test_invalid_metric_inputs_and_empty_set_denominators_remain_missing():
    invalid = assess_artifact(make_spec(), {"predicted_concepts": ["one"]},
                              reference={"concept_ids": [1], "reference_version": "v1"},
                              reference_version="v1")
    assert invalid.reference_metrics is None
    assert any(f["code"] == "METRIC_INPUT_INVALID_OR_MISSING" for f in invalid.findings)
    empty = assess_artifact(make_spec(), {"predicted_concepts": []},
                            reference={"concept_ids": [], "reference_version": "v1"},
                            reference_version="v1")
    assert empty.metric_denominators == {"predicted_unique_concepts": 0,
                                         "reference_unique_concepts": 0}
    assert empty.reference_metrics == {"precision": None, "recall": None,
                                       "f1": None, "jaccard": None}
    assert empty.acceptance["metrics"] == "EVALUATION_INCOMPLETE"


def test_acceptance_gate_keeps_dimensions_separate_and_conservative():
    report = assess_artifact(make_spec(), {"status": "success", "execution_status": "success",
                                          "compiler_status": "success"})
    assert report.acceptance["structure"] == "STRUCTURALLY_VALID"
    assert report.acceptance["vocabulary"] == "VOCABULARY_UNVERIFIED"
    assert report.acceptance["execution"] == "EXECUTION_VERIFIED"
    assert report.acceptance["reference_comparison"] == "COMPARISON_INCOMPARABLE"
    assert report.acceptance["clinical_review"] == "CLINICAL_VALIDITY_UNVERIFIED"
    assert report.acceptance["eligibility"]["ELIGIBLE_FOR_DESCRIPTIVE_REPORTING"] is True
    assert report.acceptance["eligibility"]["ELIGIBLE_FOR_PAIRED_COMPARISON"] is False
    assert not any("CLINICALLY_ADJUDICATED" in str(x) for x in report.to_dict().values())


def test_retries_are_not_independent_tasks_or_paired_rows():
    ref = {"concept_ids": [1], "reference_version": "v1", "reference_sha256": "rhash"}
    rows = [{"task_id": "T1", "run_id": f"T1_C1_try{i}", "configuration": "C1",
             "spec": make_spec().model_dump(), "record": {
                 "task_id": "T1", "run_id": f"T1_C1_try{i}", "configuration": "C1",
                 "model": "local", "scorer_version": "s1", "status": "success",
                 "scoring_scope": "full", "predicted_concepts": [1]},
             "reference": ref} for i in (1, 2)]
    result = analyze_records(rows, input_path="synthetic.json", input_sha256="hash",
                             vocabulary_version="vocab-syn", vocabulary_sha256="vhash")
    assert result["counts"]["original_tasks"] == 1
    assert result["counts"]["unreconciled_task_configuration_groups"] == 1
    assert result["counts"]["paired_eligible_original_tasks"] == 0
    assert all(not r["acceptance"]["eligibility"]["ELIGIBLE_FOR_PAIRED_COMPARISON"]
               for r in result["records"])


def test_reconciliation_adapter_preserves_original_status_and_attempt_evidence():
    ledger = {"schema_version": "synthetic", "logical_runs": [{
        "run_id": "T1_C1", "task_id": "T1", "configuration": "C1",
        "original_queue_status": "FAILED", "individual_result_status": "failed",
        "best_supported_classification": "EXECUTED, OUTPUT UNVERIFIED",
        "attempt_count_records": 2, "attempt_statuses": ["success", "failed"],
        "recorded_full_recall": 0.5, "recorded_scoring_scope": "full",
        "metric_provenance": "recorded; versions not bound",
    }]}
    row = reconciliation_rows(ledger)[0]
    assert row["record"]["status"] == "failed"
    assert row["record"]["concept_recall_full"] == 0.5
    result = analyze_records([row], input_sha256="ledgerhash")
    out = result["records"][0]
    assert out["acceptance"]["structure"] == "STRUCTURALLY_UNVERIFIED"
    assert out["recorded_metrics_unverified"]["concept_recall_full"] == 0.5
    assert out["reconciliation_evidence"]["attempt_statuses"] == ["success", "failed"]


def test_paired_gate_requires_same_task_config_reference_scope_and_scorer():
    ref = {"concept_ids": [1], "reference_version": "v1", "reference_sha256": "rhash"}
    rows = []
    for config in ("C1", "C2"):
        rows.append({"task_id": "T1", "run_id": f"T1_{config}", "configuration": config,
                     "spec": make_spec().model_dump(), "reference": ref,
                     "record": {"task_id": "T1", "run_id": f"T1_{config}",
                                "configuration": config, "model": "local", "scorer_version": "s1",
                                "status": "success", "execution_status": "success",
                                "compiler_status": "success",
                                "scoring_scope": "full", "predicted_concepts": [1]}})
    result = analyze_records(rows, input_path="synthetic.json", input_sha256="hash",
                             vocabulary_version="vocab-syn", vocabulary_sha256="vhash")
    assert result["counts"]["paired_eligible_original_tasks"] == 1
    assert all(r["acceptance"]["eligibility"]["ELIGIBLE_FOR_PAIRED_COMPARISON"]
               for r in result["records"])


def test_missing_configuration_output_is_not_imputed_or_paired():
    ref = {"concept_ids": [1], "reference_version": "v1", "reference_sha256": "rhash"}
    row = {"task_id": "T1", "run_id": "T1_C1", "configuration": "C1",
           "spec": make_spec().model_dump(), "reference": ref,
           "record": {"task_id": "T1", "run_id": "T1_C1", "configuration": "C1",
                      "model": "local", "scorer_version": "s1", "status": "success",
                      "execution_status": "success", "scoring_scope": "full",
                      "predicted_concepts": [1]}}
    result = analyze_records([row], input_sha256="hash")
    assert result["counts"]["original_tasks"] == 1
    assert result["counts"]["paired_eligible_original_tasks"] == 0
    assert result["records"][0]["reference_metrics"]["jaccard"] == 1


def test_missing_spec_is_unverified_not_invalid_and_blocks_eligibility():
    report = assess_artifact(None, {"status": "success", "executable": True})
    assert report.structural_validity is None
    assert report.acceptance["structure"] == "STRUCTURALLY_UNVERIFIED"
    assert report.acceptance["vocabulary"] == "VOCABULARY_UNVERIFIED"
    assert report.acceptance["eligibility"]["ELIGIBLE_FOR_DESCRIPTIVE_REPORTING"] is False
    assert report.recorded_metrics_unverified == {}
    missing_metric = assess_artifact(None, {"status": "failed", "concept_recall_full": None})
    assert missing_metric.recorded_metrics_unverified == {"concept_recall_full": None}
    assert any(f["code"] == "RECORDED_METRIC_MISSING" for f in missing_metric.findings)


def test_compile_failure_is_separate_from_clinical_validity():
    report = assess_artifact(make_spec(), {"status": "failed", "compiler_status": "failed"})
    assert report.acceptance["compilation"] == "COMPILE_FAILED"
    assert any(f["code"] == "SQL_COMPILATION_FAILED" for f in report.findings)
    assert report.acceptance["clinical_review"] == "CLINICAL_VALIDITY_UNVERIFIED"


def test_compiler_temp_names_are_sanitized_and_malformed_sql_is_rejected():
    hostile = "entry; DROP TABLE person; --"
    assert temp_table_name(hostile) == "cs_entry__drop_table_person____"
    spec = CohortSpec(entry_concept_set=hostile, concept_sets={
        hostile: ConceptSet(name=hostile, domain="Condition", description="safe synthetic name",
                            items=[ConceptItem(concept_id=10, rationale="safe test item")])})
    sql = compile_spec(spec)
    assert "DROP TABLE" not in sql
    assert temp_table_name(hostile) in sql
    con = duckdb.connect(":memory:")
    try:
        con.execute("SELECT FROM")
        assert False, "malformed SQL unexpectedly executed"
    except duckdb.Error:
        pass
    con.close()


def test_release_writer_is_deterministic_and_emits_three_formats(tmp_path):
    row = {"task_id": "T1", "run_id": "T1_C1", "configuration": "C1",
           "spec": make_spec().model_dump(), "record": {"status": "success"}}
    report = analyze_records([row], input_path="synthetic.json", input_sha256="same")
    output = tmp_path / "release"
    write_release(report, output)
    first = {p.name: p.read_bytes() for p in output.iterdir()}
    write_release(report, output)
    second = {p.name: p.read_bytes() for p in output.iterdir()}
    assert first == second
    assert set(first) == {"scientific_findings.json", "diagnostic_ledger.csv",
                          "scientific_validation_report.md"}


def test_compiler_index_event_windows_and_inclusion_exclusion():
    sql = compile_spec(make_spec())
    assert "min(event_date) AS index_date" in sql
    assert "BETWEEN -2" in sql and "AND 0" in sql
    assert "EXISTS (" in sql and "NOT EXISTS (" in sql
    assert "t.condition_start_date IS NOT NULL" in sql
    all_events = compile_spec(make_spec(first=False))
    assert "SELECT DISTINCT person_id, event_date AS index_date" in all_events


def test_compiled_sql_synthetic_inclusive_window_exclusion_and_index_date():
    con = duckdb.connect(":memory:")
    con.execute("create table condition_occurrence(person_id bigint, condition_concept_id bigint, condition_start_date date)")
    con.execute("create table drug_exposure(person_id bigint, drug_concept_id bigint, drug_exposure_start_date date)")
    con.execute("create table person(person_id bigint, year_of_birth bigint)")
    con.execute("create table observation_period(person_id bigint, observation_period_start_date date, observation_period_end_date date)")
    con.execute("insert into person values (1,1980),(2,1980),(3,1980),(4,1980),(5,1980)")
    con.execute("insert into observation_period values "
                "(1,'2019-01-01','2021-01-01'),(2,'2019-01-01','2021-01-01'),"
                "(3,'2019-01-01','2021-01-01'),(4,'2019-01-01','2021-01-01'),"
                "(5,'2019-01-01','2021-01-01')")
    con.execute("insert into condition_occurrence values "
                "(1,10,'2020-01-10'),(2,10,'2020-01-10'),(3,10,'2020-01-10'),"
                "(3,30,'2020-01-10'),"
                "(4,10,'2020-01-10'),(4,10,'2020-01-20'),(5,10,NULL)")
    con.execute("insert into drug_exposure values "
                "(1,20,'2020-01-08'),(2,20,'2020-01-07'),(3,20,'2020-01-09'),"
                "(4,20,'2020-01-18'),(2,20,NULL)")
    for table, ids in [("cs_entry", [10]), ("cs_include", [20]), ("cs_exclude", [30])]:
        con.execute(f"create temp table {table}(concept_id bigint)")
        con.executemany(f"insert into {table} values (?)", [(i,) for i in ids])
    rows = con.execute(compile_spec(make_spec())).fetchall()
    assert rows == [(1, duckdb.sql("select date '2020-01-10'").fetchone()[0])]
    later_events = con.execute(compile_spec(make_spec(first=False))).fetchall()
    assert later_events == [
        (1, duckdb.sql("select date '2020-01-10'").fetchone()[0]),
        (4, duckdb.sql("select date '2020-01-20'").fetchone()[0]),
    ]
    con.close()


def test_prior_observation_exact_day_boundary_is_inclusive():
    con = duckdb.connect(":memory:")
    con.execute("create table condition_occurrence(person_id bigint, condition_concept_id bigint, condition_start_date date)")
    con.execute("create table person(person_id bigint, year_of_birth bigint)")
    con.execute("create table observation_period(person_id bigint, observation_period_start_date date, observation_period_end_date date)")
    con.execute("insert into condition_occurrence values (1,10,'2020-01-10'),(2,10,'2020-01-10')")
    con.execute("insert into person values (1,1980),(2,1980)")
    con.execute("insert into observation_period values "
                "(1,'2020-01-07','2020-01-10'),(2,'2020-01-08','2020-01-10')")
    con.execute("create temp table cs_entry(concept_id bigint)")
    con.execute("insert into cs_entry values (10)")
    spec = CohortSpec(entry_concept_set="entry", prior_observation_days=3,
                      concept_sets={"entry": make_spec().concept_sets["entry"]})
    assert con.execute(compile_spec(spec)).fetchall() == [
        (1, duckdb.sql("select date '2020-01-10'").fetchone()[0])
    ]
    con.close()


def test_overlapping_observation_periods_can_duplicate_person_index_row():
    con = duckdb.connect(":memory:")
    con.execute("create table condition_occurrence(person_id bigint, condition_concept_id bigint, condition_start_date date)")
    con.execute("create table person(person_id bigint, year_of_birth bigint)")
    con.execute("create table observation_period(person_id bigint, observation_period_start_date date, observation_period_end_date date)")
    con.execute("insert into condition_occurrence values (1,10,'2020-01-10')")
    con.execute("insert into person values (1,1980)")
    con.execute("insert into observation_period values "
                "(1,'2019-01-01','2020-01-10'),(1,'2019-06-01','2020-01-10')")
    con.execute("create temp table cs_entry(concept_id bigint)")
    con.execute("insert into cs_entry values (10)")
    spec = CohortSpec(entry_concept_set="entry", concept_sets={
        "entry": make_spec().concept_sets["entry"]})
    rows = con.execute(compile_spec(spec)).fetchall()
    # Documents current compiler behavior; a person-level cohort may require DISTINCT.
    assert len(rows) == 2 and rows[0] == rows[1]
    con.close()


def test_structural_failure_and_evidence_grades_are_conservative():
    report = assess_artifact({"entry_concept_sets": ["missing"], "concept_sets": {}})
    assert report.structural_validity is False
    assert report.evidence_grade == "EVIDENCE_INSUFFICIENT"
    valid = assess_artifact(make_spec(), {"concept_f1": 1.0})
    assert "EVALUATION_INCOMPLETE" in valid.grades
    assert valid.metric_denominators == {}
    assert valid.evidence_grade == "SEMANTICALLY_UNVERIFIED"
