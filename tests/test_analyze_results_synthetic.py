from scripts.analyze_results import analyze


def _run(config, task, status, f1, track="V5.3 core", complexity="low"):
    return {"configuration": config, "task_id": task, "status": status,
            "track": track, "complexity": complexity, "wall_seconds": 2.0,
            "llm_calls": 3, "tool_calls": 1, "input_tokens": 10,
            "output_tokens": 5,
            "metrics": {"v2": {"full": {"f1": f1, "precision": f1,
                                           "recall": f1, "jaccard": f1},
                                 "entry": {"f1": f1, "precision": f1,
                                            "recall": f1, "jaccard": f1}}}}


def test_synthetic_analysis_keeps_failure_missingness_breakdowns_and_paired_n():
    reports = [_run("C1", "T01", "success", 0.5),
               _run("C2", "T01", "success", 0.4),
               _run("C1", "T02", "failed", None, track="Neuro", complexity="high")]
    result = analyze(reports)
    assert result["configurations"]["C1"]["runs"] == 2
    assert result["configurations"]["C1"]["failed_runs"] == 1
    assert result["configurations"]["C1"]["metrics_v2"]["full"]["f1"]["missing"] == 1
    assert result["breakdowns"]["track"]["Neuro"]["C1"]["runs"] == 1
    assert result["paired_wilcoxon_v2"]["C1__C2__full.f1"]["n"] == 1
