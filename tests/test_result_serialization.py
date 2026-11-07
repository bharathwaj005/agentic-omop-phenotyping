import json
import csv

import pytest
from types import SimpleNamespace

from src.result_serialization import validate_result_report, write_result_report
from src.runner import experiment
from src.metrics.evaluation import RunRecord, write_csv


def _report(status="success"):
    return {
        "schema_version": 1,
        "logical_run_id": "v53_T01_C2",
        "attempt_id": "v53_T01_C2_attempt1",
        "task_id": "T01",
        "configuration": "C2",
        "status": status,
        "final_spec": {"concept_sets": {}} if status == "success" else None,
        "metrics": {"v1": None},
    }


def test_versioned_result_round_trips_and_refuses_overwrite(tmp_path):
    path = tmp_path / "report.json"
    report = _report()
    write_result_report(path, report)
    assert json.loads(path.read_text()) == report
    with pytest.raises(FileExistsError):
        write_result_report(path, report)


@pytest.mark.parametrize("report", [
    {**_report(), "schema_version": None},
    {**_report(), "attempt_id": ""},
    {**_report(), "status": "running"},
    {**_report(), "final_spec": None},
])
def test_result_schema_fails_closed(report):
    with pytest.raises((TypeError, ValueError)):
        validate_result_report(report)


def test_experiment_result_keeps_phenotype_for_recovery_trace(monkeypatch):
    phenotype = {"spec_version": "1", "entry_concept_sets": [], "concept_sets": {}}
    spec = SimpleNamespace(
        entry_concept_sets=[], model_dump=lambda: phenotype,
    )
    pipeline_result = SimpleNamespace(
        status="success", reason=None, spec=spec, resolved={},
        tracker=None, execution=None,
    )
    monkeypatch.setattr(experiment, "run_single_agent", lambda **kwargs: pipeline_result)
    record = experiment._run_real_pipeline(
        task=SimpleNamespace(task_id="T01", question="synthetic"),
        configuration=experiment.C2, client=object(), vocab_con=object(),
        models={"single_agent": "local-model"}, reference={
            "all_concept_ids": [], "entry_concept_ids": [],
        },
    )
    assert record.status == "success"
    assert record.final_spec == phenotype


def test_evaluation_csv_has_versioned_fixed_width_rows_and_keeps_metadata(tmp_path):
    path = tmp_path / "results.csv"
    write_csv([
        RunRecord(task_id="T01", configuration="C1", status="failed",
                  reason="timeout", metadata={"attempt_id": "attempt-1"}),
        RunRecord(task_id="T02", configuration="C1", status="success",
                  final_spec={"concept_sets": {}}, concept_recall_full=0.5),
    ], path)
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert len({len(row) for row in rows}) == 1
    parsed = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert [row["schema_version"] for row in parsed] == ["1", "1"]
    assert parsed[0]["attempt_id"] == "attempt-1"
    assert parsed[0]["concept_recall_full"] == ""
    assert json.loads(parsed[0]["metadata"]) == {"attempt_id": "attempt-1"}
