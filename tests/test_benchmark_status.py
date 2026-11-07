import json

from scripts.benchmark_status import summarize


def test_status_summary_counts_remaining_and_failure_reasons(tmp_path):
    checkpoint = {
        "track": "v53", "model": "fake",
        "runs": [
            {"task_id": "T01", "configuration": "C1", "status": "success", "wall_seconds": 10},
            {"task_id": "T02", "configuration": "C1", "status": "failed", "reason": "synthetic failure", "wall_seconds": 20},
            {"task_id": "T01", "configuration": "C2", "status": "pending", "wall_seconds": ""},
        ],
    }
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))
    result = summarize(tmp_path)
    assert result["remaining"] == 1
    assert result["by_configuration"]["C1"]["mean_wall_seconds"] == 15
    assert result["by_configuration"]["C2"]["estimated_remaining_seconds"] is None
    assert result["last_5_failures"][0]["reason"] == "synthetic failure"
