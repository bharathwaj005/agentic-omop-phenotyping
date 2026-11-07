import json

from scripts import run_benchmark
from src.llm.fake_client import FakeClient


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_FAKE_LLM", "1")
    monkeypatch.setattr(run_benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(run_benchmark, "RUNS_ROOT", tmp_path / "runs")
    questions = tmp_path / "questions.jsonl"
    questions.write_text("".join(json.dumps({"task_id": tid, "question": "synthetic"}) + "\n"
                              for tid in ("T01", "T02")))
    refs = tmp_path / "tasks/reference"
    refs_v2 = tmp_path / "tasks/reference_v2"
    refs.mkdir(parents=True); refs_v2.mkdir(parents=True)
    for cid in ("134", "219"):
        value = {"all_concept_ids": [], "entry_concept_ids": []}
        (refs / f"{cid}.json").write_text(json.dumps(value))
        (refs_v2 / f"{cid}.json").write_text(json.dumps(value))
    return questions, FakeClient()


def test_run_order_interleaves_configurations_within_each_task(tmp_path, monkeypatch):
    questions, client = _setup(tmp_path, monkeypatch)
    seen = []

    def fake_run(task, config, cohort, track, model, run_dir, client, vocab_con, budget):
        seen.append((task["task_id"], config))
        return {"task_id": task["task_id"], "configuration": config,
                "status": "success", "reason": None, "wall_seconds": 1}

    monkeypatch.setattr(run_benchmark, "_run_one", fake_run)
    out = tmp_path / "runs/interleaved"
    run_benchmark.run_benchmark("v53", questions, "fake", out, ["C1", "C2"],
                                client=client, vocab_con=object(), preflight=False)
    assert seen == [("T01", "C1"), ("T01", "C2"), ("T02", "C1"), ("T02", "C2")]


def test_only_connection_failure_is_retried_once_and_logged(tmp_path, monkeypatch):
    questions, client = _setup(tmp_path, monkeypatch)
    attempts = []

    def fake_run(task, config, cohort, track, model, run_dir, client, vocab_con, budget):
        attempts.append(run_dir.name)
        if len(attempts) == 1:
            return {"status": "failed", "reason": "RuntimeError: Connection refused",
                    "wall_seconds": 0.5}
        return {"status": "success", "reason": None, "wall_seconds": 1}

    monkeypatch.setattr(run_benchmark, "_run_one", fake_run)
    out = tmp_path / "runs/retry"
    run_benchmark.run_benchmark("v53", questions, "fake", out, ["C1"],
                                tasks={"T01"}, client=client, vocab_con=object(),
                                preflight=False)
    checkpoint = json.loads((out / "checkpoint.json").read_text())
    row = checkpoint["runs"][0]
    assert attempts == ["T01_C1", "T01_C1_retry1"]
    assert row["status"] == "success" and row["attempts"] == 2
    assert row["retry_log"] == ["infrastructure retry: RuntimeError: Connection refused"]
