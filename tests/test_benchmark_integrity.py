import csv
import hashlib
import json
from pathlib import Path

from src.benchmark_integrity import audit
from src.v53_reconciliation import acceptance_gate, task_attempt_ledger, write_package


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root):
    artifacts = root / "project" / "results" / "benchmark_runs" / "V5_3_REAL_RUN"
    artifacts.mkdir(parents=True)
    queue = artifacts / "RUN_QUEUE.csv"
    rows = [
        {"run_id": "T01_C1", "task_id": "T01", "cohort_id": "134", "configuration": "C1", "status": "FAILED", "reason": "network"},
        {"run_id": "T01_C2", "task_id": "T01", "cohort_id": "219", "configuration": "C2", "status": "SUCCESS", "reason": ""},
    ]
    with queue.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    (artifacts / "RUN_MANIFEST.json").write_text(json.dumps({"runtime_queue_sha256": "0" * 64, "questions_sha256": "f" * 64}), encoding="utf-8")
    qpath = root / "project" / "tasks" / "benchmark_questions.jsonl"
    qpath.parent.mkdir(parents=True)
    qpath.write_text('{"task":"synthetic"}\n', encoding="utf-8")
    for cohort in ("134", "219"):
        ref = qpath.parent / "reference" / f"{cohort}.json"
        ref.parent.mkdir(exist_ok=True)
        ref.write_text(json.dumps({"cohort_id": cohort, "concepts": []}), encoding="utf-8")
    with (artifacts / "RUN_RESULTS.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["run_id", "task_id", "configuration", "status", "concept_recall_full"])
        writer.writeheader()
        writer.writerows([
            {"run_id": "T01_C1", "task_id": "T01", "configuration": "C1", "status": "success", "concept_recall_full": "0.2"},
            {"run_id": "ORPHAN_C1", "task_id": "ORPHAN", "configuration": "C1", "status": "success", "concept_recall_full": "0.4"},
        ])
    individual = artifacts / "individual_results"
    individual.mkdir()
    (individual / "T01_C2.json").write_text(json.dumps({"status": "success", "concept_recall_full": 0.5}), encoding="utf-8")
    recovery = artifacts / "RECOVERY_QWEN3B" / "ATTEMPTS"
    (recovery / "traces").mkdir(parents=True)
    (recovery / "recovery_records.json").write_text(json.dumps({
        "T01_C1": {"run_id": "T01_C1", "attempt_id": "a1", "status": "success", "record": {"status": "success", "scoring_scope": "full", "metadata": {"reference_supplied": True}}}
    }), encoding="utf-8")
    (recovery / "attempts.jsonl").write_text(
        json.dumps({"run_id": "T01_C1", "attempt_id": "a1", "status": "success", "record": {"status": "success", "scoring_scope": "full", "metadata": {"reference_supplied": True}}}) + "\n" +
        "{bad json\nnull\n", encoding="utf-8")
    (recovery / "traces" / "a2.json").write_text(json.dumps({"run_id": "T01_C1", "status": "running"}), encoding="utf-8")
    return queue, artifacts


def test_integrity_findings_and_idempotent_read_only(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    before = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    result1 = audit(queue, artifacts, "incorrect-expected-hash", expected_tasks=1, expected_configs=("C1", "C2"))
    result2 = audit(queue, artifacts, "incorrect-expected-hash", expected_tasks=1, expected_configs=("C1", "C2"))
    after = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    assert before == after
    assert result1 == result2
    conditions = {f["condition"] for f in result1["findings"]}
    assert {"queue hash mismatch", "manifest queue hash mismatch", "manifest question hash mismatch",
            "queue/result status conflict", "orphan results", "malformed JSONL entry",
            "non-object JSONL entry", "trace left running"}.issubset(conditions)
    assert len(result1["runs"]) == 2
    assert result1["read_only"] is True


def test_missing_results_and_invalid_checkpoint_json(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    (artifacts / "RUN_RESULTS.csv").unlink()
    cp = artifacts / "RECOVERY_QWEN3B" / "ATTEMPTS" / "recovery_records.json"
    cp.write_text("{truncated", encoding="utf-8")
    result = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    conditions = {f["condition"] for f in result["findings"]}
    assert "results file missing" in conditions
    assert "unreadable or malformed JSON" in conditions


def test_manifest_missing_or_invalid_input_hashes_are_explicit_findings(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    path = artifacts / "RUN_MANIFEST.json"
    path.write_text(json.dumps({"runtime_queue_sha256": _sha(queue)}), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    conditions = {f["condition"] for f in report["findings"]}
    assert "manifest question hash missing or invalid" in conditions
    assert report["manifest_hashes"]["questions_sha256"] is None


def test_attempt_mirror_deduplicated_but_conflicting_duplicate_reported(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    journal = artifacts / "RECOVERY_QWEN3B" / "ATTEMPTS" / "attempts.jsonl"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()[:1]]
    rows[0]["status"] = "failed"
    journal.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    result = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert any(f["condition"] == "conflicting duplicate attempt IDs" for f in result["findings"])


def test_missing_queue_result_is_reported(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    (artifacts / "RUN_RESULTS.csv").write_text(
        "run_id,task_id,configuration,status,concept_recall_full\nT01_C2,T01,C2,success,0.5\n",
        encoding="utf-8")
    result = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert any(f["condition"] == "missing results" and "T01_C1" in f["affected_ids"] for f in result["findings"])


def test_matching_queue_manifest_hash_passes_queue_hash_check(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    manifest_path = artifacts / "RUN_MANIFEST.json"
    manifest_path.write_text(json.dumps({"runtime_queue_sha256": _sha(queue)}), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert "manifest queue hash mismatch" not in {f["condition"] for f in report["findings"]}
    assert report["queue_sha256"] == _sha(queue)


def test_legacy_freeze_hash_is_compared_to_design_input_not_runtime_queue(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    root = Path(__file__).resolve().parents[1]
    design = root / "results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv"
    questions = root / "tasks/benchmark_questions.jsonl"
    (artifacts / "RUN_MANIFEST.json").write_text(json.dumps({
        "freeze_csv_sha256": _sha(design),
        "questions_sha256": _sha(questions),
    }), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    conditions = {finding["condition"] for finding in report["findings"]}
    assert report["manifest_hashes"]["design_freeze_match"] is True
    assert report["manifest_hashes"]["runtime_queue_sha256"] is None
    assert "manifest queue hash mismatch" not in conditions
    assert "manifest question hash mismatch" not in conditions


def test_duplicate_original_task_and_design_gap_are_failures(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    rows = list(csv.DictReader(queue.open(encoding="utf-8")))
    rows[1]["run_id"] = rows[0]["run_id"]
    rows[1]["task_id"] = "T02"
    with queue.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    conditions = {f["condition"] for f in report["findings"]}
    assert "duplicate queue run IDs" in conditions
    assert "frozen design coverage mismatch" in conditions


def test_task_keeps_multiple_attempts_success_then_failure(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    recovery = artifacts / "RECOVERY_QWEN3B" / "MULTI"
    recovery.mkdir(parents=True)
    records = {
        "a-success": {"run_id": "T01_C1", "attempt_id": "a-success", "status": "success", "record": {"status": "success", "concept_recall_full": 0.7, "scoring_scope": "full", "metadata": {"reference_supplied": True}}},
        "a-failure": {"run_id": "T01_C1", "attempt_id": "a-failure", "status": "failed", "error_category": "timeout", "record": {"status": "failed", "reason": "timed out"}},
    }
    (recovery / "recovery_records.json").write_text(json.dumps(records), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    run = next(r for r in report["runs"] if r["run_id"] == "T01_C1")
    assert len(run["attempt_evidence"]) >= 2
    assert {a["attempt_id"] for a in run["attempt_evidence"]} >= {"a-success", "a-failure"}
    assert "success_and_failure_attempt_history" in run["conflict_flags"]
    ledger = task_attempt_ledger(report)
    assert sum(row["record_type"] == "original_task" and row["logical_run_id"] == "T01_C1" for row in ledger) == 1
    assert {row.get("attempt_id") for row in ledger if row["record_type"] == "attempt_evidence"} >= {"a-success", "a-failure"}


def test_failed_then_success_attempts_keep_ordered_evidence(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    records = [
        {"run_id": "T01_C1", "attempt_id": "first-fail", "status": "failed", "error_category": "validation_failure", "record": {"status": "failed", "reason": "bad schema"}},
        {"run_id": "T01_C1", "attempt_id": "later-success", "status": "success", "model": "local-model", "record": {"status": "success", "concept_recall_full": 0.4, "scoring_scope": "full", "metadata": {"reference_supplied": True}}},
    ]
    cp = artifacts / "RECOVERY_QWEN3B" / "SEQUENCE" / "recovery_records.json"
    cp.parent.mkdir(parents=True)
    cp.write_text(json.dumps(records), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    run = next(r for r in report["runs"] if r["run_id"] == "T01_C1")
    assert run["best_supported_classification"] == "EXECUTED, OUTPUT UNVERIFIED"
    attempts = [a["attempt_id"] for a in run["attempt_evidence"] if a.get("attempt_id")]
    assert attempts.index("first-fail") < attempts.index("later-success")


def test_empty_checkpoint_and_malformed_json_are_not_silent(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    bad = artifacts / "RECOVERY_QWEN3B" / "EMPTY" / "recovery_records.json"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert any(f["condition"] == "unreadable or malformed JSON" and f["evidence_path"] == str(bad) for f in report["findings"])
    assert any(f["condition"] == "malformed JSONL entry" for f in report["findings"])


def test_reordered_csv_rows_match_by_id_and_additional_ids_are_orphans(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    result = artifacts / "RUN_RESULTS.csv"
    result.write_text("run_id,task_id,configuration,status,concept_recall_full\n"
                      "T01_C2,T01,C2,success,0.5\nT01_C1,T01,C1,failed,\nX99_C1,X99,C1,failed,\n", encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert not any(f["condition"] == "queue/result status conflict" for f in report["findings"])
    assert any(f["condition"] == "orphan results" and "X99_C1" in f["affected_ids"] for f in report["findings"])


def test_attempt_configuration_mismatch_is_conflict(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    cp = artifacts / "RECOVERY_QWEN3B" / "MISMATCH" / "recovery_records.json"
    cp.parent.mkdir(parents=True)
    cp.write_text(json.dumps({"x": {"run_id": "T01_C1", "attempt_id": "x", "configuration": "C4", "status": "failed", "record": {"status": "failed"}}}), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    run = next(r for r in report["runs"] if r["run_id"] == "T01_C1")
    assert "attempt_configuration_mismatch" in run["conflict_flags"]
    assert any(f["condition"] == "attempt configuration mismatch" for f in report["findings"])


def test_acceptance_gate_passes_only_complete_80_row_baseline_and_fails_closed():
    base = _valid_acceptance_report()
    assert acceptance_gate(base)["overall_status"] == "PASS"
    base["findings"] = [{"condition": "queue/result status conflict", "evidence_path": "/results.csv"}]
    assert acceptance_gate(base)["overall_status"] == "FAIL"
    base["findings"].append({"condition": "missing immutable model/task/reference/vocabulary/scoring provenance", "evidence_path": "/checkpoint"})
    assert acceptance_gate(base)["overall_status"] == "FAIL"
    assert {g["status"] for g in acceptance_gate(base)["gates"]} >= {"FAIL", "BLOCKED"}


def _valid_acceptance_report():
    digest = "a" * 64
    question_hash = "b" * 64
    runs = []
    for task_num in range(1, 21):
        for config in ("C1", "C2", "C3", "C4"):
            model = "qwen-test:1"
            runs.append({
                "run_id": f"T{task_num:02d}_{config}",
                "task_id": f"T{task_num:02d}",
                "configuration": config,
                "original_queue_status": "SUCCESS",
                "aggregate_result_status": "SUCCESS",
                "normalized_reconciled_status": "VERIFIED_SUCCESS",
                "models_seen": [model],
                "original_log_model_label": model,
                "effective_configuration": {
                    "configuration_id": config,
                    "models": {"single_agent" if config == "C2" else "planner": model},
                },
                "output_available": True,
                "metric_available": True,
                "recorded_full_recall": 0.5,
                "metric_denominators": {"reference_unique_concepts": 2},
            })
    return {
        "queue_rows": 80, "queue_path": "/frozen/queue.csv", "queue_sha256": digest,
        "expected_queue_sha256": digest, "queue_status_counts": {"SUCCESS": 80},
        "queue_schema_valid": True, "runs": runs, "findings": [],
        "manifest_present": True, "manifest_hashes": {
            "freeze_csv_sha256": digest, "questions_sha256": question_hash,
            "runtime_queue_sha256": None, "design_freeze_match": True,
            "current_questions_sha256": question_hash,
        },
        "results_present": True, "attempt_records_present": True,
        "raw_output_complete": True, "model_provenance_complete": True,
        "model_digests": {"qwen-test:1": digest}, "verified_model_aliases": [],
        "metric_denominators_complete": True,
        "attempt_source_reconciliation": {
            "conflicting_duplicate_attempt_ids": [],
            "repeated_within_source_attempt_ids": [],
        },
    }


def test_acceptance_rejects_80_success_results_against_1_79_queue_statuses():
    report = _valid_acceptance_report()
    report["queue_status_counts"] = {"SUCCESS": 1, "FAILED": 79}
    for index, run in enumerate(report["runs"]):
        run["original_queue_status"] = "SUCCESS" if index == 0 else "FAILED"
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["result_status_consistency"] == "FAIL"
    assert gate["queue_uniqueness_and_schema"] == "PASS"


def test_acceptance_rejects_manifest_hash_mismatch_or_missing_hash():
    report = _valid_acceptance_report()
    report["manifest_hashes"]["design_freeze_match"] = False
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["manifest_to_queue_consistency"] == "FAIL"
    report = _valid_acceptance_report()
    del report["manifest_hashes"]["questions_sha256"]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["manifest_to_queue_consistency"] == "FAIL"
    report = _valid_acceptance_report()
    report["findings"] = [{"condition": "manifest design freeze hash mismatch"}]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["manifest_to_queue_consistency"] == "FAIL"


def test_missing_required_outputs_block_acceptance_even_if_top_level_flag_true():
    report = _valid_acceptance_report()
    report["runs"][23]["output_available"] = False
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["output_completeness"] == "BLOCKED"


def test_missing_normalized_status_blocks_output_completeness():
    report = _valid_acceptance_report()
    del report["runs"][0]["normalized_reconciled_status"]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["output_completeness"] == "BLOCKED"


def test_apparent_success_warning_blocks_output_completeness():
    report = _valid_acceptance_report()
    report["findings"] = [{
        "severity": "WARNING",
        "condition": "apparent success lacks independently reviewable output",
        "evidence_path": "/run/T01_C1",
    }]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["output_completeness"] == "BLOCKED"


def test_missing_metric_or_denominator_cannot_be_treated_as_zero_or_complete():
    report = _valid_acceptance_report()
    report["runs"][7]["metric_available"] = False
    report["runs"][7]["recorded_full_recall"] = None
    report["runs"][7]["metric_denominators"] = None
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["metric_completeness_and_denominators"] == "BLOCKED"


def test_unverified_model_alias_is_not_equated_with_configured_model():
    report = _valid_acceptance_report()
    report["runs"][0]["models_seen"] = ["jbi-qwen2.5:3b-8k"]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["configuration_and_model_provenance"] == "BLOCKED"
    report["model_digests"]["jbi-qwen2.5:3b-8k"] = "a" * 64
    report["verified_model_aliases"] = [{
        "model_id_a": "qwen-test:1", "model_id_b": "jbi-qwen2.5:3b-8k",
        "digest": "a" * 64, "verified": True,
        "verification_method": "same_model_digest", "evidence_path": "/proof/model-manifest.json",
        "evidence_sha256": "e" * 64,
    }]
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["configuration_and_model_provenance"] == "BLOCKED"


def test_incomplete_or_contradictory_audited_fixture_cannot_pass_output_or_result_gate(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    gate = {g["name"]: g["status"] for g in acceptance_gate(report)["gates"]}
    assert gate["result_status_consistency"] == "FAIL"
    assert gate["output_completeness"] == "BLOCKED"


def test_journal_mirror_reconciliation_is_idempotent_and_input_preserving(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    before = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    first = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    second = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    after = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    assert first == second and before == after
    assert first["attempt_source_reconciliation"]["unique_attempt_ids"] == 1
    assert first["attempt_source_reconciliation"]["identical_checkpoint_journal_mirrors"] == ["a1"]


def test_incomplete_provenance_and_missing_metrics_block_gate(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    gate = acceptance_gate(report)
    by_name = {g["name"]: g["status"] for g in gate["gates"]}
    assert by_name["configuration_and_model_provenance"] == "BLOCKED"
    assert by_name["metric_completeness_and_denominators"] == "BLOCKED"
    assert gate["overall_status"] == "FAIL"


def test_package_outputs_are_new_atomic_files_and_sources_unchanged(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    before = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    out = tmp_path / "deliverable"
    result = write_package(out, report, tmp_path / "project", artifacts,
                           {"state": "PASS", "commands": [{"exit_code": 0}]})
    after = {str(p): _sha(p) for p in artifacts.rglob("*") if p.is_file()}
    expected_files = {"integrity_report.json", "acceptance_gate.json", "manifest_discrepancies.json",
                      "provenance_manifest.json", "task_attempt_ledger.jsonl", "test_results.json",
                      "publication_evidence_summary.md", "codex1_handoff.md", "reproduction_commands.txt", "package_index.json"}
    assert before == after
    assert expected_files.issubset({p.name for p in out.iterdir()})
    assert result["ledger_rows"] == sum(1 for _ in (out / "task_attempt_ledger.jsonl").open(encoding="utf-8"))
    assert result["gate"]["overall_status"] == "FAIL"
    provenance = json.loads((out / "provenance_manifest.json").read_text(encoding="utf-8"))
    assert {entry["cohort_id"] for entry in provenance["reference_files"]} == {"134", "219"}
    assert all(entry["sha256"] for entry in provenance["reference_files"])
    try:
        write_package(out, report, tmp_path / "project", artifacts)
    except FileExistsError:
        pass
    else:
        raise AssertionError("package builder must refuse to overwrite an existing directory")


def test_attempt_linkage_and_reordered_queue_results_are_id_based(tmp_path):
    queue, artifacts = _fixture(tmp_path)
    # Reorder result rows and add an unlinked recovery attempt.
    result = artifacts / "RUN_RESULTS.csv"
    result.write_text("run_id,task_id,configuration,status,concept_recall_full\n"
                      "T01_C2,T01,C2,success,0.5\nT01_C1,T01,C1,failed,\n", encoding="utf-8")
    cp = artifacts / "RECOVERY_QWEN3B" / "ORPHAN" / "recovery_records.json"
    cp.parent.mkdir(parents=True)
    cp.write_text(json.dumps({"orphan": {"run_id": "T99_C3", "attempt_id": "orphan", "status": "failed"}}), encoding="utf-8")
    report = audit(queue, artifacts, _sha(queue), expected_tasks=1, expected_configs=("C1", "C2"))
    assert any(f["condition"] == "orphan recovery attempts" and "T99_C3" in f["affected_ids"] for f in report["findings"])
    assert not any(f["condition"] == "queue/result status conflict" for f in report["findings"])
