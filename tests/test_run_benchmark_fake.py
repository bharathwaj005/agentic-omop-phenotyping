import json

import duckdb

from scripts import run_benchmark
from src.llm.fake_client import FakeClient


def test_fake_benchmark_run_checkpoints_and_resume_skips_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_FAKE_LLM", "1")
    monkeypatch.delenv("JBI_RUN_DEADLINE_S", raising=False)
    monkeypatch.setattr(run_benchmark, "ROOT", tmp_path)
    run_root = tmp_path / "results/codex_20261025/runs"
    monkeypatch.setattr(run_benchmark, "RUNS_ROOT", run_root)
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({
        "task_id": "T01", "question": "Identify adults with a synthetic condition."
    }) + "\n")
    for folder in ("reference", "reference_v2"):
        directory = tmp_path / "tasks" / folder
        directory.mkdir(parents=True)
        (directory / "134.json").write_text(json.dumps({
            "all_concept_ids": [4027663], "entry_concept_ids": [4027663]}))
    freeze = tmp_path / "results/benchmark_design/V5_3_FREEZE"
    freeze.mkdir(parents=True)
    (freeze / "BENCHMARK_FINAL20_V5_3_FINAL.csv").write_text("synthetic freeze\n")
    out = run_root / "fake-run"
    client = FakeClient()
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE concept(concept_id BIGINT, concept_name VARCHAR,
        domain_id VARCHAR, vocabulary_id VARCHAR, concept_class_id VARCHAR,
        standard_concept VARCHAR, invalid_reason VARCHAR)""")
    con.execute("INSERT INTO concept VALUES (4027663, 'fake', 'Condition', 'x', 'x', 'S', NULL)")
    con.execute("CREATE TABLE concept_ancestor(ancestor_concept_id BIGINT, descendant_concept_id BIGINT)")

    assert run_benchmark.run_benchmark("v53", questions, "test-model", out,
                                       ["C2"], client=client, vocab_con=con,
                                       preflight=False) == 0
    calls_after_first = client.calls
    checkpoint = json.loads((out / "checkpoint.json").read_text())
    assert checkpoint["runs"][0]["status"] == "success"
    assert (out / "T01_C2/trace.json").is_file()
    assert (out / "T01_C2/raw_replies.json").is_file()
    assert (out / "T01_C2/report.json").is_file()
    report = json.loads((out / "T01_C2/report.json").read_text())
    trace = json.loads((out / "T01_C2/trace.json").read_text())
    assert report["attempt_number"] == 1
    assert report["attempt_id"] == "fake-run_v53_T01_C2_attempt1"
    assert report["experiment_id"] == "fake-run"
    assert report["schema_version"] == 1
    assert report["logical_run_id"] == "v53_T01_C2"
    assert report["prompt_hashes"]
    assert trace["run_id"] == report["attempt_id"]
    assert checkpoint["runs"][0]["report_sha256"]
    assert checkpoint["runs"][0]["trace_sha256"]
    run_manifest = json.loads((out / "run_manifest.v1.json").read_text())
    assert run_manifest["runtime_queue_initial"]["sha256"]
    assert run_manifest["experiment_id"] == "fake-run"
    assert run_manifest["task_file"]["sha256"]
    assert run_manifest["design_freeze_input"]["sha256"]
    assert [(item["version"], item["cohort_id"]) for item in run_manifest["reference_inputs"]] == [
        ("v1", "134"), ("v2", "134")
    ]
    assert run_manifest["model_identity"] is None  # fake client did not query an endpoint

    assert run_benchmark.run_benchmark("v53", questions, "test-model", out,
                                       ["C2"], resume=True, client=client,
                                       vocab_con=con, preflight=False) == 0
    assert client.calls == calls_after_first

    second_out = run_root / "fake-run-second"
    assert run_benchmark.run_benchmark("v53", questions, "test-model", second_out,
                                       ["C2"], client=FakeClient(), vocab_con=con,
                                       preflight=False) == 0
    second = json.loads((second_out / "T01_C2/report.json").read_text())
    assert second["logical_run_id"] == report["logical_run_id"]
    assert second["attempt_id"] != report["attempt_id"]
    con.close()
