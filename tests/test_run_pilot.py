import json

import duckdb

from scripts.run_pilot import run_pilot


def test_pilot_writes_full_report_using_fake_client(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_FAKE_LLM", "1")
    root = tmp_path
    (root / "tasks").mkdir()
    (root / "tasks/benchmark_questions.jsonl").write_text(
        json.dumps({
            "task_id": "T01", "question": "Identify adults with a synthetic condition."
        }) + "\n")
    for folder in ("reference", "reference_v2"):
        target = root / "tasks" / folder
        target.mkdir()
        (target / "134.json").write_text(json.dumps({
            "all_concept_ids": [4027663], "entry_concept_ids": [4027663]}))

    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE concept(concept_id BIGINT, concept_name VARCHAR,
        domain_id VARCHAR, vocabulary_id VARCHAR, concept_class_id VARCHAR,
        standard_concept VARCHAR, invalid_reason VARCHAR)""")
    con.execute("INSERT INTO concept VALUES (4027663, 'fake', 'Condition', 'x', 'x', 'S', NULL)")
    con.execute("CREATE TABLE concept_ancestor(ancestor_concept_id BIGINT, descendant_concept_id BIGINT)")
    out = root / "results/codex_20261024/pilot"
    report = run_pilot("T01", "test-model", out, "v2", vocab_con=con, root=root)

    assert report["status"] == "success"
    assert report["model_names_used"] == ["test-model"]
    assert set(report["metrics"]) == {"v1", "v2"}
    assert report["final_spec"] is not None
    assert json.loads((out / "trace.json").read_text())["status"] == "success"
    assert json.loads((out / "checkpoint.json").read_text())["status"] == "success"
    con.close()
