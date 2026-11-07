from scripts.analyze_results import analyze


def _report(config, task, value):
    return {"configuration": config, "task_id": task, "status": "success",
            "metrics": {"v2": {"full": {"f1": value}, "entry": {"f1": value}}}}


def test_repeated_synthetic_runs_are_averaged_within_task_before_pairing():
    result = analyze([_report("C1", "T01", .2), _report("C1", "T01", .8),
                      _report("C2", "T01", .4)])
    assert result["paired_wilcoxon_v2"]["C1__C2__full.f1"]["n"] == 1
    assert "repeated runs are averaged" in result["paired_metric_definition"]
