"""Cohort scoring requires explicitly comparable patient ID sets."""

from types import SimpleNamespace

from src.metrics.evaluation import RunRecord
from src.metrics.evaluation import patient_set_jaccard
from src.runner import experiment
from src.runner.experiment import C3, _comparable_patient_sets


def test_comparable_patient_sets_present():
    result = SimpleNamespace(
        execution=SimpleNamespace(persons=[10, 20]),
    )

    predicted, reference, reason = _comparable_patient_sets(
        result,
        {"comparable_patient_ids": [20, 30]},
    )

    assert predicted == {10, 20}
    assert reference == {20, 30}
    assert reason == []
    assert patient_set_jaccard(predicted, reference).jaccard == 1 / 3


def test_comparable_patient_sets_absent_preserves_null_inputs():
    result = SimpleNamespace(execution=None)

    predicted, reference, reason = _comparable_patient_sets(
        result,
        {"all_concept_ids": [1, 2], "cohort_size": 2},
    )

    assert predicted is None
    assert reference is None
    assert reason == [
        "predicted_patient_set_unavailable",
        "comparable_reference_patient_set_unavailable",
    ]


def test_empty_comparable_patient_sets_keep_counts_but_jaccard_is_null():
    result = SimpleNamespace(execution=SimpleNamespace(persons=[]))
    predicted, reference, reason = _comparable_patient_sets(
        result,
        {"comparable_patient_ids": []},
    )

    metrics = patient_set_jaccard(predicted, reference)
    assert reason == []
    assert metrics.jaccard is None
    assert metrics.predicted_size == 0
    assert metrics.reference_size == 0


def test_runner_records_reason_and_leaves_uncomparable_counts_null(monkeypatch):
    result = SimpleNamespace(
        status="success",
        reason=None,
        resolved={},
        spec=None,
        execution=SimpleNamespace(persons=[10, 20], size=2),
        tracker=SimpleNamespace(to_dict=lambda: {}),
        critic_rounds=0,
        validator_retries=0,
        unresolved=[],
    )
    monkeypatch.setattr(experiment, "run_multi_agent", lambda **_kwargs: result)
    task = SimpleNamespace(task_id="T01", question="A test cohort")

    record = experiment._run_real_pipeline(
        task=task,
        configuration=C3,
        client=object(),
        vocab_con=object(),
        reference={"all_concept_ids": [], "entry_concept_ids": []},
    )

    assert record.cohort_jaccard is None
    assert record.predicted_patient_count is None
    assert record.reference_patient_count is None
    assert record.metadata["cohort_metric_unavailable_reasons"] == [
        "comparable_reference_patient_set_unavailable"
    ]


def test_runner_scores_only_explicitly_comparable_patient_ids(monkeypatch):
    result = SimpleNamespace(
        status="success",
        reason=None,
        resolved={},
        spec=None,
        execution=SimpleNamespace(persons=[10, 20], size=2),
        tracker=SimpleNamespace(to_dict=lambda: {}),
        critic_rounds=0,
        validator_retries=0,
        unresolved=[],
    )
    monkeypatch.setattr(experiment, "run_multi_agent", lambda **_kwargs: result)
    task = SimpleNamespace(task_id="T01", question="A test cohort")

    record = experiment._run_real_pipeline(
        task=task,
        configuration=C3,
        client=object(),
        vocab_con=object(),
        reference={"comparable_patient_ids": [20, 30]},
    )

    assert record.cohort_jaccard == 1 / 3
    assert record.predicted_patient_count == 2
    assert record.reference_patient_count == 2
    assert "cohort_metric_unavailable_reasons" not in record.metadata


def test_runner_preserves_zero_counts_for_empty_comparable_cohorts(monkeypatch):
    result = SimpleNamespace(
        status="success",
        reason=None,
        resolved={},
        spec=None,
        execution=SimpleNamespace(persons=[], size=0),
        tracker=SimpleNamespace(to_dict=lambda: {}),
        critic_rounds=0,
        validator_retries=0,
        unresolved=[],
    )
    monkeypatch.setattr(experiment, "run_multi_agent", lambda **_kwargs: result)
    task = SimpleNamespace(task_id="T01", question="A test cohort")

    record = experiment._run_real_pipeline(
        task=task,
        configuration=C3,
        client=object(),
        vocab_con=object(),
        reference={"comparable_patient_ids": []},
    )

    assert record.cohort_jaccard is None
    assert record.predicted_patient_count == 0
    assert record.reference_patient_count == 0
    assert record.metadata["cohort_metric_unavailable_reasons"] == [
        "both_comparable_patient_sets_empty"
    ]
