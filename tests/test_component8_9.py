"""Component 8/9 contract tests."""

from __future__ import annotations

from src.metrics.evaluation import (
    RunRecord,
    aggregate,
    adjudication_record,
    exact_match,
    patient_set_jaccard,
    set_metrics,
    summarize_runs,
)
from src.runner.experiment import (
    C1,
    C2,
    C3,
    C4,
    ExperimentConfig,
    run_experiment,
)


def test_concept_metrics():
    m = set_metrics([1, 2, 3], [2, 3, 4])

    assert round(m.precision, 6) == round(2 / 3, 6)
    assert round(m.recall, 6) == round(2 / 3, 6)
    assert round(m.f1, 6) == round(2 / 3, 6)
    assert round(m.jaccard, 6) == round(2 / 4, 6)


def test_patient_jaccard():
    m = patient_set_jaccard([1, 2, 3], [2, 3, 4])

    assert m.jaccard == 0.5
    assert m.predicted_size == 3
    assert m.reference_size == 3


def test_exact_match():
    assert exact_match([1, 2], [2, 1])
    assert not exact_match([1], [1, 2])


def test_aggregate():
    x = aggregate([0.5, 0.75, 1.0])

    assert x["n"] == 3
    assert x["mean"] == 0.75
    assert x["median"] == 0.75


def test_adjudication_record():
    r = adjudication_record(
        "T01",
        "C1",
        predicted_concepts=[1, 2],
        reference_concepts=[2, 3],
        predicted_patients=[10, 20],
        reference_patients=[20, 30],
        executable=True,
    )

    assert r.task_id == "T01"
    assert r.configuration == "C1"
    assert r.concept_jaccard == 1 / 3
    assert r.cohort_jaccard == 1 / 3
    assert r.executable is True


def test_summary_by_configuration():
    records = [
        RunRecord(
            task_id="T01",
            configuration="C1",
            status="success",
            concept_f1=0.8,
            cohort_jaccard=0.5,
        ),
        RunRecord(
            task_id="T02",
            configuration="C1",
            status="success",
            concept_f1=0.6,
            cohort_jaccard=1.0,
        ),
        RunRecord(
            task_id="T01",
            configuration="C3",
            status="failed",
        ),
    ]

    s = summarize_runs(records)

    assert s["n_runs"] == 3
    assert s["n_success"] == 2
    assert s["by_configuration"]["C1"]["n_runs"] == 2
    assert s["by_configuration"]["C3"]["n_failed"] == 1


def test_experiment_runner_uses_injected_task_function():
    class Task:
        def __init__(self, task_id):
            self.task_id = task_id

    tasks = [Task("T01"), Task("T02")]

    configs = [
        ExperimentConfig("A", use_critic=False),
        ExperimentConfig("B", use_critic=True),
    ]

    seen = []

    def run_task(*, task, configuration, reference):
        seen.append(
            (
                task.task_id,
                configuration.name,
                reference,
            )
        )

        return RunRecord(
            task_id=task.task_id,
            configuration=configuration.name,
            status="success",
        )

    result = run_experiment(
        tasks,
        configs,
        run_task,
        reference_loader=lambda task_id: {"gold": task_id},
    )

    assert result.n_runs == 4
    assert result.n_success == 4
    assert len(seen) == 4
    assert seen[0] == ("T01", "A", {"gold": "T01"})


def test_runner_does_not_require_reference_metadata_from_agent_task():
    class Task:
        task_id = "T01"
        question = "Find patients with asthma."

    captured = {}

    def run_task(*, task, configuration, reference):
        captured["task"] = task
        captured["reference"] = reference

        return RunRecord(
            task_id=task.task_id,
            configuration=configuration.name,
            status="success",
        )

    result = run_experiment(
        [Task()],
        [C1],
        run_task,
    )

    assert result.n_runs == 1
    assert captured["reference"] is None


def test_named_configuration_flags():
    assert C1.use_critic is True
    assert C3.use_critic is False
    assert C2.use_validator is True
    assert C4.use_validator is False


if __name__ == "__main__":
    tests = [
        value
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]

    for test in tests:
        test()

    print(f"COMPONENT 8/9: {len(tests)} tests passed")
