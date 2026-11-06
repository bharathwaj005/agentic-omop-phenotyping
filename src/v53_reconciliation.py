"""Task/attempt ledger and fail-closed acceptance gates for V5.3 evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.benchmark_integrity import audit, sha256


def _status(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    value = str(value).strip().lower()
    if value in {"success", "succeeded", "verified success"}:
        return "success"
    if value in {"failed", "failure", "recorded_failure"}:
        return "failed"
    return value


def _valid_digest(value: Any) -> bool:
    value = str(value or "")
    if value.startswith("sha256:"):
        value = value[7:]
    return len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def _verified_model_provenance(report: dict[str, Any], runs: list[dict]) -> bool:
    """Require exact per-run model/config evidence; aliases need digest proof."""
    catalog = report.get("model_digests")
    if not isinstance(catalog, dict) or not catalog:
        return False
    if any(not _valid_digest(digest) for digest in catalog.values()):
        return False

    for run in runs:
        effective = run.get("effective_configuration")
        if not isinstance(effective, dict):
            return False
        if str(effective.get("configuration_id", "")) != str(run.get("configuration", "")):
            return False
        models = effective.get("models")
        if not isinstance(models, dict) or not models:
            return False
        configured = {str(model_id) for model_id in models.values() if model_id}
        if not configured or any(model_id not in catalog for model_id in configured):
            return False
        observed = {str(x) for x in run.get("models_seen", []) if x}
        if run.get("original_log_model_label"):
            observed.add(str(run["original_log_model_label"]))
        # Model IDs remain literal. A matching alias claim in the report is not
        # identity evidence; normalization requires a separately verified
        # artifact before the report can use one canonical ID.
        if not observed or not observed.issubset(configured):
            return False
    return True


def acceptance_gate(report: dict[str, Any]) -> dict[str, Any]:
    """Evaluate explicit machine-readable gates; missing evidence never passes."""
    findings = report.get("findings", [])
    conditions = {f.get("condition") for f in findings}
    runs = report.get("runs", [])
    statuses = Counter(r.get("normalized_reconciled_status") for r in runs)

    def gate(name: str, status: str, evidence: list[str], reason: str | None) -> dict:
        return {"name": name, "status": status, "evidence": evidence, "failure_reason": reason}

    run_ids = [r.get("run_id") for r in runs]
    tasks = Counter(r.get("task_id") for r in runs)
    configs = Counter(r.get("configuration") for r in runs)
    task_config_pairs = Counter((r.get("task_id"), r.get("configuration")) for r in runs)
    design_complete = (len(tasks) == 20 and set(configs) == {"C1", "C2", "C3", "C4"}
                       and all(n == 4 for n in tasks.values())
                       and all(n == 20 for n in configs.values())
                       and all(n == 1 for n in task_config_pairs.values()))
    expected_count = (report.get("queue_rows") == 80 and len(runs) == 80
                      and len(set(run_ids)) == 80 and all(run_ids) and design_complete)
    run_queue_statuses = Counter(_status(r.get("original_queue_status")) for r in runs)
    queue_status_counts = {_status(k): int(v) for k, v in report.get("queue_status_counts", {}).items()}
    queue_counts_consistent = bool(queue_status_counts) and run_queue_statuses == Counter(queue_status_counts)
    valid_queue_statuses = all(s in {"success", "failed"} for s in run_queue_statuses)
    queue_valid = (report.get("queue_schema_valid", False) and queue_counts_consistent and design_complete
                   and valid_queue_statuses
                   and not ({"queue hash mismatch", "duplicate queue run IDs", "frozen design coverage mismatch", "invalid queue schema"} & conditions))
    row_status_conflicts = []
    unknown_result_statuses = []
    if report.get("results_present", False):
        for run in runs:
            original = _status(run.get("original_queue_status"))
            aggregate = _status(run.get("aggregate_result_status"))
            if aggregate is None or aggregate not in {"success", "failed"}:
                unknown_result_statuses.append(run.get("run_id"))
            elif aggregate != original:
                row_status_conflicts.append(run.get("run_id"))
    result_conflict = ("queue/result status conflict" in conditions
                       or "invalid result row schema" in conditions
                       or "invalid result schema" in conditions
                       or "queue/result identity conflict" in conditions
                       or "missing results" in conditions
                       or "orphan results" in conditions
                       or "duplicate result rows" in conditions
                       or bool(row_status_conflicts) or bool(unknown_result_statuses)
                       or not queue_counts_consistent)
    attempt_bad = bool(report.get("attempt_source_reconciliation", {}).get("conflicting_duplicate_attempt_ids") or
                       report.get("attempt_source_reconciliation", {}).get("repeated_within_source_attempt_ids"))
    attempt_orphan = "orphan recovery attempts" in conditions or "orphan trace" in conditions or "unlinked attempt records" in conditions
    manifest_hashes = report.get("manifest_hashes", {})
    legacy_design_hash = manifest_hashes.get("freeze_csv_sha256") if isinstance(manifest_hashes, dict) else None
    runtime_queue_hash = manifest_hashes.get("runtime_queue_sha256") if isinstance(manifest_hashes, dict) else None
    design_freeze_match = manifest_hashes.get("design_freeze_match") if isinstance(manifest_hashes, dict) else None
    question_manifest_hash = manifest_hashes.get("questions_sha256") if isinstance(manifest_hashes, dict) else None
    question_actual_hash = manifest_hashes.get("current_questions_sha256") if isinstance(manifest_hashes, dict) else None
    manifest_bad = ({"manifest queue hash mismatch", "manifest runtime queue hash missing or invalid",
                     "manifest design freeze hash mismatch", "manifest design freeze hash missing or invalid",
                     "manifest question hash mismatch", "manifest question hash missing or invalid"} & conditions)
    runtime_hash_valid = (_valid_digest(runtime_queue_hash)
                          and runtime_queue_hash == report.get("queue_sha256"))
    legacy_freeze_valid = (_valid_digest(legacy_design_hash) and design_freeze_match is True)
    question_hash_valid = (_valid_digest(question_manifest_hash)
                           and _valid_digest(question_actual_hash)
                           and question_manifest_hash == question_actual_hash)
    manifest_hashes_valid = (runtime_hash_valid or legacy_freeze_valid) and question_hash_valid
    manifest_status = ("FAIL" if manifest_bad or
                       (report.get("manifest_present", False) and not manifest_hashes_valid)
                       else "PASS" if report.get("manifest_present", False) and manifest_hashes_valid
                       else "NOT_ASSESSABLE")
    result_status = "FAIL" if result_conflict else "PASS" if report.get("results_present", False) else "NOT_ASSESSABLE"
    metric_rows_complete = all(
        run.get("metric_available") is True
        and isinstance(run.get("recorded_full_recall"), (int, float))
        and math.isfinite(float(run["recorded_full_recall"]))
        and 0 <= float(run["recorded_full_recall"]) <= 1
        and isinstance(run.get("metric_denominators"), dict)
        and isinstance(run["metric_denominators"].get("reference_unique_concepts"), int)
        and run["metric_denominators"]["reference_unique_concepts"] > 0
        for run in runs
    )
    gates = [
        gate("queue_uniqueness_and_schema", "PASS" if expected_count and queue_valid else "FAIL",
             [report.get("queue_path", "")], None if expected_count and queue_valid else "Queue IDs/design/hash do not satisfy the frozen 80-row contract."),
        gate("frozen_input_hash", "PASS" if report.get("queue_sha256") == report.get("expected_queue_sha256") else "FAIL",
             [report.get("queue_path", "")], None if report.get("queue_sha256") == report.get("expected_queue_sha256") else "Canonical queue hash differs from expected freeze."),
        gate("manifest_to_queue_consistency", manifest_status,
             [f.get("evidence_path", "") for f in findings if "manifest" in f.get("condition", "")], "Manifest hashes do not match available canonical inputs." if manifest_status == "FAIL" else "Manifest is missing." if manifest_status == "NOT_ASSESSABLE" else None),
        gate("original_task_coverage", "PASS" if expected_count else "FAIL", [report.get("queue_path", "")], None if expected_count else "Queue does not contain 80 unique logical task/configuration rows."),
        gate("attempt_to_task_linkage", "FAIL" if attempt_orphan or "attempt configuration mismatch" in conditions else "PASS", ["recovery checkpoint and journal inventory"], "Orphan attempt/trace IDs or configuration mismatches are present." if attempt_orphan or "attempt configuration mismatch" in conditions else None),
        gate("duplicate_and_conflicting_attempts", "NOT_ASSESSABLE" if not report.get("attempt_records_present", False) else "FAIL" if attempt_bad else "PASS", ["attempt_source_reconciliation"], "Conflicting or repeated attempt IDs were detected." if attempt_bad else "No attempt records are available." if not report.get("attempt_records_present", False) else None),
        gate("checkpoint_journal_integrity", "NOT_ASSESSABLE" if not report.get("attempt_records_present", False) else "FAIL" if any(f.get("condition") in {"malformed JSONL entry", "unreadable or malformed JSON", "conflicting duplicate attempt IDs", "duplicate attempt ID repeated within one source", "attempt journal/checkpoint representation differs"} for f in findings) else "PASS", ["attempt_source_reconciliation", "findings"], "Malformed or inconsistent checkpoint/journal evidence exists." if any(f.get("condition") in {"malformed JSONL entry", "unreadable or malformed JSON", "conflicting duplicate attempt IDs", "duplicate attempt ID repeated within one source", "attempt journal/checkpoint representation differs"} for f in findings) else "No checkpoint/journal evidence is available." if not report.get("attempt_records_present", False) else None),
        gate("result_status_consistency", result_status,
             [f.get("evidence_path", "") for f in findings if f.get("condition") in {"queue/result status conflict", "invalid result row schema"}],
             "Per-run result statuses conflict with the original queue or are missing/invalid." if result_conflict else "Aggregate result file is absent." if result_status == "NOT_ASSESSABLE" else None),
        # A top-level completeness flag and artifact booleans are insufficient
        # without a recognized reconciled classification for every logical
        # run. In particular, absent classifications must not hide warnings
        # about apparent successes whose outputs cannot be reviewed.
        gate("output_completeness", "PASS" if (
                 report.get("raw_output_complete") is True
                 and all(r.get("output_available") is True for r in runs)
                 and all(r.get("normalized_reconciled_status") in {
                     "VERIFIED_SUCCESS", "RECORDED_FAILURE", "INTERRUPTED_ATTEMPT",
                     "MISSING_ATTEMPT_EVIDENCE", "INVALID_OR_INCOMPLETE_RESULT",
                     "CONFLICTING_RECORDS",
                 } for r in runs)
                 and "apparent success lacks independently reviewable output" not in conditions
             ) else "BLOCKED",
             [f.get("evidence_path", "") for f in findings if f.get("condition") == "apparent success lacks independently reviewable output"],
             "Required independently reviewable output or normalized per-run status evidence is missing for one or more logical runs."
             if not (report.get("raw_output_complete") is True
                     and all(r.get("output_available") is True for r in runs)
                     and all(r.get("normalized_reconciled_status") in {
                         "VERIFIED_SUCCESS", "RECORDED_FAILURE", "INTERRUPTED_ATTEMPT",
                         "MISSING_ATTEMPT_EVIDENCE", "INVALID_OR_INCOMPLETE_RESULT",
                         "CONFLICTING_RECORDS",
                     } for r in runs)
                     and "apparent success lacks independently reviewable output" not in conditions)
             else None),
        gate("configuration_and_model_provenance", "PASS" if report.get("model_provenance_complete") is True and _verified_model_provenance(report, runs) and "missing immutable model/task/reference/vocabulary/scoring provenance" not in conditions else "BLOCKED", [f.get("evidence_path", "") for f in findings if "provenance" in f.get("condition", "")], "Exact model identities/digests and per-run effective configuration are incomplete or unverified." if not (report.get("model_provenance_complete") is True and _verified_model_provenance(report, runs)) else None),
        gate("metric_completeness_and_denominators", "PASS" if report.get("metric_denominators_complete") is True and metric_rows_complete and "metric denominator missingness" not in conditions else "BLOCKED", ["scientific_summary_root_recovery_only"], "Per-run metrics or their denominators are missing, invalid, or unequal." if not (report.get("metric_denominators_complete") is True and metric_rows_complete and "metric denominator missingness" not in conditions) else None),
    ]
    failed = any(g["status"] == "FAIL" for g in gates)
    blocked = any(g["status"] in {"BLOCKED", "NOT_ASSESSABLE"} for g in gates)
    gates.append(gate("reproducibility_readiness", "FAIL" if failed else "BLOCKED" if blocked else "PASS",
                      ["all preceding gates"], "Overall gate fails closed: at least one critical gate fails." if failed else "Overall gate blocked: required output/provenance evidence is missing." if blocked else None))
    overall = "FAIL" if failed else "BLOCKED" if blocked else "PASS"
    return {"overall_status": overall, "gates": gates, "normalized_status_counts": dict(statuses),
            "policy": "missing evidence is never PASS; failed critical checks fail closed"}


def _normalized_attempt(record: dict, trace_by_attempt: dict[str, dict]) -> str:
    aid = str(record.get("attempt_id") or "")
    trace = trace_by_attempt.get(aid, {})
    if trace.get("status") == "running":
        return "INTERRUPTED_ATTEMPT"
    status = str(record.get("status", "")).lower()
    inner = record.get("record") if isinstance(record.get("record"), dict) else record
    if status == "success" and inner.get("status") == "success":
        return "RECORDED_SUCCESS_OUTPUT_UNVERIFIED"
    if status == "failed":
        return "RECORDED_FAILURE"
    if status:
        return "INVALID_OR_INCOMPLETE_RESULT"
    return "UNKNOWN_STATUS"


def task_attempt_ledger(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one original-task row plus one row per checkpoint/journal record."""
    attempt_records = report.get("attempt_records", [])
    trace_by_attempt = {}
    for run in report.get("runs", []):
        for trace in run.get("trace_evidence", []):
            trace_by_attempt[trace.get("attempt_id", "")] = trace
    output = []
    for run in report.get("runs", []):
        output.append({"record_type": "original_task", "logical_run_id": run.get("run_id"),
                       "task_id": run.get("task_id"), "configuration_id": run.get("configuration"),
                       "attempt_id": None, "source_artifact": report.get("queue_path"),
                       "record_location": None, "original_recorded_status": run.get("original_queue_status"),
                       "attempt_status": None, "normalized_status": run.get("normalized_reconciled_status"),
                       "started_at": None, "finished_at": run.get("recovery_timestamp"),
                       "model_id": ";".join(run.get("models_seen", [])) or run.get("original_log_model_label"),
                       "configuration_identity": run.get("configuration"),
                       "error_category": None, "error_details": run.get("original_failure_reason"),
                       "output_available": run.get("output_available", False),
                       "result_record_available": run.get("result_record_available", False),
                       "metric_available": run.get("metric_available", False),
                       "metric_value": run.get("recorded_full_recall"),
                       "provenance_completeness": run.get("provenance_completeness"),
                       "hash_verification_state": run.get("hash_verification_state"),
                       "conflict_flags": run.get("conflict_flags", []),
                       "unresolved_reason": run.get("unresolved_status_reason")})
        for record in attempt_records:
            if record.get("run_id") != run.get("run_id"):
                continue
            inner = record.get("record") if isinstance(record.get("record"), dict) else record
            output.append({"record_type": "attempt_evidence", "logical_run_id": run.get("run_id"),
                           "task_id": run.get("task_id"), "configuration_id": run.get("configuration"),
                           "attempt_id": record.get("attempt_id"), "source_artifact": record.get("_source_path"),
                           "source_artifacts": record.get("_source_paths", []),
                           "source_locations": record.get("_source_locations", []),
                           "record_location": record.get("_record_location"),
                           "original_recorded_status": run.get("original_queue_status"),
                           "attempt_status": record.get("status"),
                           "normalized_status": _normalized_attempt(record, trace_by_attempt),
                           "started_at": record.get("started_at"), "finished_at": record.get("finished_at"),
                           "model_id": record.get("model"), "configuration_identity": record.get("configuration", run.get("configuration")),
                           "error_category": record.get("error_category"),
                           "error_details": record.get("error") or inner.get("reason"),
                           "output_available": bool(record.get("final_spec") or inner.get("final_spec") or inner.get("phenotype_output")),
                           "result_record_available": bool(record.get("record") or record.get("status")),
                           "metric_available": isinstance(inner.get("concept_recall_full"), (int, float)),
                           "metric_value": inner.get("concept_recall_full"),
                           "provenance_completeness": "PARTIAL" if record.get("model") and inner.get("scoring_scope") else "NOT_AVAILABLE",
                           "hash_verification_state": run.get("hash_verification_state"),
                           "conflict_flags": run.get("conflict_flags", []),
                           "unresolved_reason": None if record.get("status") == "success" and inner.get("status") == "success" else (record.get("error") or inner.get("reason"))})
    return output


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _artifact_inventory(paths: list[Path], root: Path | list[Path]) -> list[dict]:
    entries = []
    for path in sorted(set(paths)):
        if not path.is_file():
            entries.append({"path": str(path), "size_bytes": None, "mtime": None, "sha256": None, "state": "NOT_AVAILABLE"})
            continue
        stat = path.stat()
        relative = None
        for candidate_root in root if isinstance(root, list) else [root]:
            if path.is_relative_to(candidate_root):
                relative = str(path.relative_to(candidate_root))
                break
        entry = {"path": str(path), "relative_path": relative,
                 "size_bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                 "sha256": sha256(path), "state": "HASHED", "format": path.suffix.lower() or "no_extension"}
        if path.suffix.lower() == ".csv" and stat.st_size <= 10_000_000:
            with path.open(newline="", encoding="utf-8", errors="replace") as stream:
                reader = csv.reader(stream)
                entry["columns"] = next(reader, [])
                entry["data_row_count"] = sum(1 for _ in reader)
        elif path.suffix.lower() == ".jsonl" and stat.st_size <= 10_000_000:
            entry["line_count"] = sum(1 for line in path.open(encoding="utf-8", errors="replace") if line.strip())
        elif path.suffix.lower() == ".json" and stat.st_size <= 10_000_000:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                entry["json_root_type"] = type(value).__name__
                entry["json_top_level_keys"] = list(value)[:200] if isinstance(value, dict) else None
            except (OSError, json.JSONDecodeError):
                entry["json_schema_state"] = "MALFORMED"
        entries.append(entry)
    return entries


def build_provenance_manifest(report: dict, project_root: Path, artifacts: Path,
                              test_results: dict | None = None) -> dict:
    project_root, artifacts = Path(project_root), Path(artifacts)
    evidence_root = artifacts.parents[2] if len(artifacts.parents) > 2 else artifacts.parent
    queue_rows = report.get("runs", [])
    cohorts = sorted({str(r.get("cohort_id")) for r in queue_rows if r.get("cohort_id") is not None})
    ref_dir = evidence_root / "tasks" / "reference"
    source_paths = [Path(report["queue_path"]), artifacts / "RUN_MANIFEST.json", artifacts / "RUN_RESULTS.csv",
                    artifacts / "qwen3b_run.log", evidence_root / "tasks" / "benchmark_questions.jsonl",
                    evidence_root / "data" / "eunomia.duckdb", evidence_root / "data" / "vocab.duckdb",
                    evidence_root / "athena_raw" / "CONCEPT_METADATA.csv",
                    evidence_root / "athena_raw" / "CONCEPT_RELATIONSHIP_METADATA.csv",
                    evidence_root / "athena_candidate" / "CONCEPT_METADATA.csv",
                    evidence_root / "athena_candidate" / "CONCEPT_RELATIONSHIP_METADATA.csv",
                    project_root / "src" / "metrics" / "evaluation.py", project_root / "src" / "tools" / "compiler.py"]
    source_paths.extend(path for path in artifacts.rglob("*") if path.is_file())
    source_paths.extend(ref_dir / f"{cohort}.json" for cohort in cohorts)
    inventory = _artifact_inventory(source_paths, [project_root, evidence_root])
    by_path = {e["path"]: e for e in inventory}
    qpath = str(Path(report["queue_path"]))
    return {"created_at_utc": datetime.now(timezone.utc).isoformat(),
            "package_scope": "existing V5.3 benchmark evidence; read-only source audit",
            "queue": {"path": qpath, "sha256": report.get("queue_sha256"),
                      "expected_sha256": report.get("expected_queue_sha256"),
                      "hash_verified": report.get("queue_sha256") == report.get("expected_queue_sha256"),
                      "row_count": report.get("queue_rows")},
            "task_and_attempt_ids": {"original_task_ids": [r.get("run_id") for r in queue_rows],
                                     "attempt_ids": sorted({str(a.get("attempt_id")) for a in report.get("attempt_records", []) if a.get("attempt_id")})},
            "model_provenance": {"model_labels_seen": sorted({m for r in queue_rows for m in r.get("models_seen", [])} | {str(r.get("original_log_model_label")) for r in queue_rows if r.get("original_log_model_label")}),
                                 "model_digest": None, "state": "NOT_AVAILABLE", "reason": "No immutable model digest is recorded in historical artifacts."},
            "configuration_ids": sorted({str(r.get("configuration")) for r in queue_rows}),
            "configuration_version": None, "compiler_version": None, "scorer_version": None,
            "historical_version_state": "NOT_AVAILABLE; current working-tree source hashes do not establish historical execution versions",
            "vocabulary_release": None, "reference_version": None,
            "reference_files": [{"cohort_id": cohort,
                                 "task_ids": sorted({str(r.get("task_id")) for r in queue_rows if str(r.get("cohort_id")) == cohort}),
                                 "path": str(ref_dir / f"{cohort}.json"),
                                 "sha256": by_path.get(str(ref_dir / f"{cohort}.json"), {}).get("sha256"),
                                 "state": "HASHED" if by_path.get(str(ref_dir / f"{cohort}.json"), {}).get("sha256") else "NOT_AVAILABLE"} for cohort in cohorts],
            "execution_environment": {"python_version": platform.python_version(), "platform": platform.platform(),
                                      "historical_environment": None, "reason": "Per-run immutable environment capture absent."},
            "artifact_inventory": inventory,
            "test_results": test_results or {"state": "NOT_AVAILABLE", "reason": "Not supplied to manifest builder."},
            "missing_provenance_fields": ["model digest", "per-run configuration resolution", "historical compiler version",
                                          "historical scorer version", "vocabulary release", "per-run reference hash binding",
                                          "raw output hashes for recovered successes", "historical runtime environment"],
            "self_hash": None, "self_hash_reason": "A manifest cannot contain its own stable SHA-256."}


def discrepancy_report(report: dict) -> dict:
    explanations = {
        "manifest queue hash mismatch": {"possible_explanations": ["stale manifest", "manifest references another queue serialization/version"], "root_cause_status": "UNRESOLVED"},
        "manifest question hash mismatch": {"possible_explanations": ["questions changed after manifest creation", "manifest references a different question file/version"], "root_cause_status": "UNRESOLVED"},
        "queue/result status conflict": {"possible_explanations": ["stale results artifact", "different run/input version", "incorrect status aggregation"], "root_cause_status": "UNRESOLVED"},
        "invalid result row schema": {"possible_explanations": ["column misalignment/serialization defect", "different result schema"], "root_cause_status": "UNRESOLVED"},
        "original queue/log failure reason conflict": {"possible_explanations": ["error-recording failure obscured original API error", "queue contains a later or different error summary"], "root_cause_status": "UNRESOLVED"},
    }
    discrepancies = []
    for f in report.get("findings", []):
        item = {"condition": f.get("condition"), "severity": f.get("severity"),
                               "evidence_path": f.get("evidence_path"), "affected_ids": f.get("affected_ids"),
                               "observed": f.get("observed"), "confidence": f.get("confidence"),
                               "disposition": "UNRESOLVED" if f.get("severity") in {"CRITICAL", "ERROR"} else "DOCUMENTED_LIMITATION",
                               "recommended_action": f.get("recommended_action")}
        item.update(explanations.get(f.get("condition"), {"root_cause_status": "NOT_ESTABLISHED"}))
        discrepancies.append(item)
    return {"queue_sha256": report.get("queue_sha256"), "expected_queue_sha256": report.get("expected_queue_sha256"),
            "discrepancies": discrepancies}


def write_package(output_dir: Path, report: dict, project_root: Path, artifacts: Path,
                  test_results: dict | None = None) -> dict:
    """Write package atomically into a new directory; never overwrite an existing one."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    gate = acceptance_gate(report)
    ledger = task_attempt_ledger(report)
    statuses = Counter(row.get("normalized_reconciled_status") for row in report.get("runs", []))
    best_statuses = Counter(row.get("best_supported_classification") for row in report.get("runs", []))
    conflicting_ids = {rid for finding in report.get("findings", [])
                       if finding.get("condition") in {"queue/result status conflict", "original queue/log failure reason conflict"}
                       for rid in finding.get("affected_ids", [])}
    provenance = build_provenance_manifest(report, project_root, artifacts, test_results)
    files = {
        "integrity_report.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
        "acceptance_gate.json": json.dumps(gate, indent=2, sort_keys=True) + "\n",
        "manifest_discrepancies.json": json.dumps(discrepancy_report(report), indent=2, sort_keys=True) + "\n",
        "provenance_manifest.json": json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        "task_attempt_ledger.jsonl": "".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger),
        "test_results.json": json.dumps(test_results or {"state": "NOT_AVAILABLE"}, indent=2, sort_keys=True) + "\n",
    }
    summary = ["# V5.3 existing-evidence summary", "", f"Queue rows: {report.get('queue_rows')}.",
               f"Queue SHA-256: `{report.get('queue_sha256')}` (expected `{report.get('expected_queue_sha256')}`).",
               f"Integrity acceptance gate: **{gate['overall_status']}**.", "",
               "| Evidence classification | Count | Interpretation |",
               "|---|---:|---|",
               f"| Verified original success | {best_statuses.get('VERIFIED SUCCESS', 0)} | One original result record; not proof of full scientific validity. |",
               f"| Executed, output unverified | {best_statuses.get('EXECUTED, OUTPUT UNVERIFIED', 0)} | Recovery success records exist; raw final outputs are not available for independent review. |",
               f"| Recorded failures | {best_statuses.get('FAILED — BUDGET/VALIDATION', 0) + best_statuses.get('FAILED — TIMEOUT', 0)} | Budget/validation or timeout failures in best-supported history. |",
               f"| Interrupted | {best_statuses.get('INTERRUPTED', 0)} | Trace remains nonterminal. |",
               f"| Conflicting evidence | {len(conflicting_ids)} | Queue/result or original queue/log conflict; overlaps with current best-supported status. |",
               f"| Missing attempt evidence | {best_statuses.get('MISSING ATTEMPT EVIDENCE', 0)} | No attempt/result evidence is available. |",
               "",
               "This evidence supports descriptive summaries of recorded successful recovery metrics only. It does not support configuration ranking, patient-level comparison, or a claim that all original tasks succeeded.", "",
               "| Configuration | Metric n | Queue denominator | Mean full-concept recall |",
               "|---|---:|---:|---:|"]
    for config, values in report.get("scientific_summary_root_recovery_only", {}).items():
        mean = values.get("mean_full_concept_recall")
        summary.append(f"| {config} | {values.get('successful_metric_n')} | {values.get('recovery_records_denominator')} | {mean if mean is not None else 'NOT_AVAILABLE'} |")
    pair_n = [value["paired_successful_task_count"] for value in report.get("pairwise_successful_task_coverage", {}).values()]
    summary.extend(["", f"Paired successful-task overlap spans {min(pair_n) if pair_n else 0}–{max(pair_n) if pair_n else 0} tasks across configuration pairs; success-selected task sets are unequal.",
                    "Patient-level metrics are unavailable. Recovered successes lack independently reviewable output and complete immutable provenance."])
    files["publication_evidence_summary.md"] = "\n".join(summary) + "\n"
    files["codex1_handoff.md"] = ("# Codex 1 integrity handoff\n\n"
        "Do not modify the frozen queue, `RUN_MANIFEST.json`, or `RUN_RESULTS.csv`. Before a controlled run, require the canonical queue hash, unique task/config pairs, manifest hashes bound to exact inputs, results schema/status reconciliation by run ID, terminal trace reconciliation, and an explicit attempt cap.\n\n"
        "Historical artifact defects: `RUN_RESULTS.csv` reports 80 successes against 79 original queue failures and has invalid success metrics/numeric reason fields; the manifest queue/questions hashes do not match current canonical inputs; `qwen3b_run.log` shows the T01_C3 HTTP 404 for model `strong` followed by a pandas `TypeError` while the queue says timeout. Root cause of the all-success CSV and exact queue/manifest version linkage remain unresolved. Required acceptance test: synthetic 80-row queue with mixed statuses must fail the gate when the aggregate marks every row successful, preserve each attempt separately, and reject `running` traces as terminal. Current blockers also include missing immutable model/task/reference/vocabulary/scorer provenance and traces still running for T03_C4/T07_C2. Interface: `src.benchmark_integrity.audit(queue_path, artifacts, expected_sha256)` plus `src.v53_reconciliation.acceptance_gate(report)`.\n")
    files["reproduction_commands.txt"] = (
        "PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_benchmark_integrity.py\n"
        "PYTHONPATH=. .venv/bin/python -m pytest -q\n"
        "PYTHONPATH=. .venv/bin/python scripts/build_v53_evidence_package.py --queue <RUN_QUEUE.csv> --artifacts <V5_3_REAL_RUN> --expected-sha256 ac668c67c85ad69d061476c071f17c55ef24b0b4c913cebd42184687ddea6a66 --output-dir <new-results-directory>\n")
    provenance["reconciled_output_artifacts"] = {name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                                        "size_bytes": len(content.encode("utf-8"))}
                                                 for name, content in files.items() if name != "provenance_manifest.json"}
    provenance["reconciled_output_artifacts_state"] = "HASHED; provenance manifest self-hash intentionally omitted"
    files["provenance_manifest.json"] = json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    files["package_index.json"] = json.dumps({"files": {name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                                                    "size_bytes": len(content.encode("utf-8"))}
                                                           for name, content in files.items()},
                                               "self_hash": None, "self_hash_reason": "Index cannot contain its own stable digest."},
                                              indent=2, sort_keys=True) + "\n"
    for name, text in files.items():
        _atomic_write(output_dir / name, text.encode("utf-8"))
    return {"output_dir": str(output_dir), "gate": gate, "ledger_rows": len(ledger),
            "file_hashes": {name: sha256(output_dir / name) for name in files}}
