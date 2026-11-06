"""Read-only integrity audit for frozen benchmark and recovery artifacts.

The auditor never edits its inputs. It returns deterministic findings and a
per-logical-run history; timestamps in the report are intentionally omitted.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_records(path: Path, findings: list[dict]) -> list[dict]:
    """Read a checkpoint map/list or JSONL without losing malformed-line evidence."""
    try:
        if path.suffix.lower() == ".jsonl":
            rows = []
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    findings.append(_finding("WARNING", path, [], "blank JSONL line",
                                             f"line {lineno} is blank", "high", "Preserve and review journal line."))
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    findings.append(_finding("ERROR", path, [], "malformed JSONL entry",
                                             f"line {lineno}: {exc.msg}", "high", "Quarantine the line; do not infer an attempt."))
                    continue
                if not isinstance(row, dict):
                    findings.append(_finding("ERROR", path, [], "non-object JSONL entry",
                                             f"line {lineno} contains {type(row).__name__}", "high", "Preserve and review entry."))
                    continue
                row["_record_location"] = f"line:{lineno}"
                rows.append(row)
            return rows
        value = _json(path)
        if isinstance(value, dict):
            return [dict(v, run_id=v.get("run_id", k), _record_location=f"key:{k}")
                    for k, v in value.items() if isinstance(v, dict)]
        if isinstance(value, list):
            return [dict(v, _record_location=f"index:{index}") for index, v in enumerate(value)
                    if isinstance(v, dict)]
        findings.append(_finding("ERROR", path, [], "invalid checkpoint root", type(value).__name__, "high", "Preserve and inspect checkpoint."))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(_finding("ERROR", path, [], "unreadable or malformed JSON", str(exc), "high", "Preserve the artifact and inspect its encoding/content."))
    return []


def _finding(severity: str, path: Path | str, ids: list[str], condition: str,
             observed: str, confidence: str, action: str) -> dict:
    return {"severity": severity, "evidence_path": str(path), "affected_ids": sorted(set(ids)),
            "condition": condition, "observed": observed, "confidence": confidence,
            "recommended_action": action}


def _metric_record(item: dict) -> dict:
    return item.get("record") if isinstance(item.get("record"), dict) else item


def audit(queue_path: Path, artifacts: Path, expected_sha256: str,
          expected_tasks: int = 20, expected_configs: tuple[str, ...] = ("C1", "C2", "C3", "C4")) -> dict:
    """Audit V5.3 artifacts. `artifacts` is the directory containing queue-adjacent files."""
    queue_path, artifacts = Path(queue_path), Path(artifacts)
    findings: list[dict] = []
    evidence_root = artifacts.parents[2] if len(artifacts.parents) > 2 else artifacts.parent
    project_root = Path(__file__).resolve().parents[1]
    question_candidates = [project_root / "tasks" / "benchmark_questions.jsonl",
                           evidence_root / "tasks" / "benchmark_questions.jsonl"]
    question_path = next((p for p in question_candidates if p.is_file()), question_candidates[0])
    try:
        queue_hash = sha256(queue_path)
        with queue_path.open(newline="", encoding="utf-8") as stream:
            queue = list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        return {"queue_path": str(queue_path), "queue_sha256": None, "findings": [
            _finding("CRITICAL", queue_path, [], "queue unreadable", str(exc), "high", "Restore access to the frozen queue before any continuation.")],
            "runs": [], "attempts": [], "read_only": True}

    if queue_hash != expected_sha256:
        findings.append(_finding("CRITICAL", queue_path, [r.get("run_id", "") for r in queue],
                                 "queue hash mismatch", f"expected {expected_sha256}; observed {queue_hash}",
                                 "high", "Stop; do not repair or execute against a changed queue."))
    ids = [r.get("run_id", "") for r in queue]
    duplicates = [k for k, n in Counter(ids).items() if k and n > 1]
    if duplicates:
        findings.append(_finding("CRITICAL", queue_path, duplicates, "duplicate queue run IDs", str(duplicates), "high", "Resolve only through an authorized queue freeze process."))
    tasks = Counter(r.get("task_id", "") for r in queue)
    configs = Counter(r.get("configuration", "") for r in queue)
    task_config_counts = Counter((r.get("task_id", ""), r.get("configuration", "")) for r in queue)
    queue_required = {"run_id", "task_id", "configuration", "status", "reason"}
    queue_schema_ok = bool(queue) and queue_required.issubset(queue[0]) and all(all(r.get(k) is not None for k in queue_required) for r in queue)
    if not queue_schema_ok:
        findings.append(_finding("CRITICAL", queue_path, ids, "invalid queue schema", f"required columns={sorted(queue_required)}", "high", "Stop; do not continue with an invalid task ledger."))
    if len(tasks) != expected_tasks or any(n != len(expected_configs) for n in tasks.values()) or set(configs) != set(expected_configs) or any(n != expected_tasks for n in configs.values()) or any(n != 1 for n in task_config_counts.values()):
        findings.append(_finding("CRITICAL", queue_path, ids, "frozen design coverage mismatch",
                                 f"tasks={len(tasks)} counts={dict(tasks)} configs={dict(configs)}", "high", "Do not run until queue design is verified."))

    queue_by_id = {r.get("run_id"): r for r in queue if r.get("run_id")}
    original = Counter(r.get("status", "") for r in queue)
    manifest_path = artifacts / "RUN_MANIFEST.json"
    manifest = {}
    manifest_hashes: dict[str, str | None] = {
        "freeze_csv_sha256": None,
        "runtime_queue_sha256": None,
        "design_freeze_actual_sha256": None,
        "design_freeze_match": None,
        "questions_sha256": None,
        "current_questions_sha256": sha256(question_path) if question_path.is_file() else None,
        "current_questions_path": str(question_path),
    }
    if manifest_path.exists():
        try:
            manifest = _json(manifest_path)
            observed = manifest.get("freeze_csv_sha256")
            runtime_queue_observed = manifest.get("runtime_queue_sha256")
            questions_observed = manifest.get("questions_sha256")
            manifest_hashes["freeze_csv_sha256"] = observed
            manifest_hashes["runtime_queue_sha256"] = runtime_queue_observed
            manifest_hashes["questions_sha256"] = questions_observed
            design_path = project_root / "results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv"
            design_hash = sha256(design_path) if design_path.is_file() else None
            manifest_hashes["design_freeze_actual_sha256"] = design_hash
            legacy_design_match = bool(isinstance(observed, str) and design_hash and observed == design_hash)
            manifest_hashes["design_freeze_match"] = legacy_design_match
            if runtime_queue_observed is not None and (
                    not isinstance(runtime_queue_observed, str)
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", runtime_queue_observed)):
                findings.append(_finding("ERROR", manifest_path, ids, "manifest runtime queue hash missing or invalid",
                                         f"runtime_queue_sha256={runtime_queue_observed!r}", "high", "Record a SHA-256 for the exact runtime queue artifact."))
            elif isinstance(runtime_queue_observed, str) and runtime_queue_observed != queue_hash:
                findings.append(_finding("ERROR", manifest_path, ids, "manifest queue hash mismatch",
                                         f"manifest={runtime_queue_observed}; canonical queue={queue_hash}", "high", "Mark runtime queue hash mismatch; bind future manifests to exact inputs."))
            elif runtime_queue_observed is None and not legacy_design_match:
                if not isinstance(observed, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", observed):
                    findings.append(_finding("ERROR", manifest_path, ids, "manifest design freeze hash missing or invalid",
                                             f"freeze_csv_sha256={observed!r}", "high", "Bind the legacy freeze hash to its design CSV or emit an explicit runtime_queue_sha256."))
                elif not design_hash:
                    findings.append(_finding("WARNING", manifest_path, ids, "manifest design freeze hash unverifiable",
                                             "legacy freeze_csv_sha256 is present but the design CSV is unavailable", "medium", "Preserve the legacy field and capture explicit versioned input hashes for new runs."))
                else:
                    findings.append(_finding("ERROR", manifest_path, ids, "manifest design freeze hash mismatch",
                                             f"manifest={observed}; design freeze={design_hash}", "high", "Resolve which design-freeze artifact the legacy manifest identifies."))
            if not isinstance(questions_observed, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", questions_observed):
                findings.append(_finding("ERROR", manifest_path, ids, "manifest question hash missing or invalid",
                                         f"questions_sha256={questions_observed!r}", "high", "Require an explicit SHA-256 bound to the task definitions."))
            elif manifest_hashes["current_questions_sha256"] is None:
                findings.append(_finding("ERROR", question_path, ids, "question definitions missing for manifest verification",
                                         "cannot verify manifest questions_sha256", "high", "Restore/read the exact frozen question input before accepting provenance."))
            elif questions_observed != manifest_hashes["current_questions_sha256"]:
                findings.append(_finding("ERROR", manifest_path, ids, "manifest question hash mismatch",
                                         f"manifest={questions_observed}; current file={manifest_hashes['current_questions_sha256']}", "high", "Do not assume current questions generated historical results."))
            if manifest.get("real_api_used") is False and any(r.get("status") == "SUCCESS" for r in queue):
                findings.append(_finding("WARNING", manifest_path, [r["run_id"] for r in queue if r.get("status") == "SUCCESS"],
                                         "manifest provider declaration conflicts with executed run evidence",
                                         "manifest real_api_used=false while run log records model calls", "medium", "Resolve manifest provenance before interpreting model identity."))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(_finding("ERROR", manifest_path, [], "manifest unreadable", str(exc), "high", "Preserve and review manifest."))
    else:
        findings.append(_finding("ERROR", manifest_path, ids, "manifest missing", "RUN_MANIFEST.json absent", "high", "Record a new manifest bound to exact inputs before continuation."))

    results_path = artifacts / "RUN_RESULTS.csv"
    results: dict[str, dict] = {}
    if results_path.exists():
        try:
            with results_path.open(newline="", encoding="utf-8") as stream:
                result_rows = list(csv.DictReader(stream))
            rids = [r.get("run_id", "") for r in result_rows]
            for r in result_rows:
                if r.get("run_id"):
                    results.setdefault(r["run_id"], r)
            extras = sorted(set(rids) - set(queue_by_id))
            missing = sorted(set(queue_by_id) - set(rids))
            if extras:
                findings.append(_finding("ERROR", results_path, extras, "orphan results", f"{len(extras)} IDs absent from queue", "high", "Do not aggregate orphan rows."))
            if missing:
                findings.append(_finding("ERROR", results_path, missing, "missing results", f"{len(missing)} queued IDs absent", "high", "Keep missing results explicit; do not impute."))
            dups = [k for k, n in Counter(rids).items() if k and n > 1]
            if dups:
                findings.append(_finding("ERROR", results_path, dups, "duplicate result rows", str(dups), "high", "Retain attempt identities and avoid implicit row selection."))
            conflicts = [k for k, r in results.items() if k in queue_by_id and r.get("status", "").upper() != queue_by_id[k].get("status", "").upper()]
            if conflicts:
                findings.append(_finding("CRITICAL", results_path, conflicts, "queue/result status conflict",
                                         f"result statuses={dict(Counter(results[k].get('status') for k in conflicts))}; queue={dict(Counter(queue_by_id[k].get('status') for k in conflicts))}", "high", "Treat queue and result status as conflicting evidence; never accept aggregate success alone."))
            identity_conflicts = [k for k, r in results.items() if k in queue_by_id and
                                  (r.get("task_id") != queue_by_id[k].get("task_id") or
                                   r.get("configuration") != queue_by_id[k].get("configuration"))]
            if identity_conflicts:
                findings.append(_finding("CRITICAL", results_path, identity_conflicts, "queue/result identity conflict",
                                         "result task_id or configuration does not match the row with the same run_id", "high", "Do not merge or score mismatched run identities."))
            required = {"run_id", "task_id", "configuration", "status", "concept_recall_full"}
            if result_rows and not required.issubset(result_rows[0]):
                findings.append(_finding("ERROR", results_path, rids, "invalid result schema", f"missing columns={sorted(required-set(result_rows[0]))}", "high", "Reject result table until schema is repaired in a new output."))
            malformed = [r.get("run_id", "") for r in result_rows if not r.get("task_id") or not r.get("configuration") or r.get("status", "").lower() not in {"success", "failed"}]
            for row in result_rows:
                rid = row.get("run_id", "")
                if row.get("status", "").lower() == "success":
                    raw_metric = row.get("concept_recall_full", "")
                    try:
                        if not raw_metric or not 0 <= float(raw_metric) <= 1:
                            malformed.append(rid)
                    except (TypeError, ValueError):
                        malformed.append(rid)
                    if row.get("reason", "") and row["reason"].strip().isdigit():
                        malformed.append(rid)
            if malformed:
                findings.append(_finding("ERROR", results_path, malformed, "invalid result row schema",
                                         "missing identity fields, unsupported status, missing/out-of-range success metric, or numeric reason value",
                                         "high", "Preserve source and reject this table as a metric/status ledger."))
        except (OSError, UnicodeError, csv.Error) as exc:
            findings.append(_finding("ERROR", results_path, [], "results unreadable", str(exc), "high", "Preserve and inspect the CSV."))
    else:
        result_rows = []
        findings.append(_finding("ERROR", results_path, ids, "results file missing", "RUN_RESULTS.csv absent", "high", "Keep missing results explicit."))

    individual_dir = artifacts / "individual_results"
    individual: dict[str, dict] = {}
    if individual_dir.exists():
        for path in sorted(individual_dir.glob("*.json")):
            try:
                value = _json(path)
                if not isinstance(value, dict):
                    findings.append(_finding("ERROR", path, [path.stem], "invalid individual result schema", f"root is {type(value).__name__}", "high", "Exclude from scored evidence."))
                    continue
                rid = value.get("run_id") or path.stem
                individual[rid] = value
                if not (isinstance(value.get("record"), dict) or value.get("status") in {"success", "failed"}):
                    findings.append(_finding("ERROR", path, [rid], "invalid individual result schema", "expected status record or nested record", "high", "Exclude from scored evidence."))
                rec = _metric_record(value)
                if rec.get("status") == "success":
                    valid_recall = isinstance(rec.get("concept_recall_full"), (int, float)) and 0 <= rec["concept_recall_full"] <= 1
                    if not valid_recall or not rec.get("scoring_scope"):
                        findings.append(_finding("ERROR", path, [rid], "success output lacks valid metric schema",
                                                 "success lacks numeric full recall in [0,1] or scoring_scope", "high", "Do not score this record until its evaluation provenance is restored."))
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(_finding("ERROR", path, [path.stem], "malformed individual result", str(exc), "high", "Preserve; do not silently skip."))
        orphan_ind = sorted(set(individual) - set(queue_by_id))
        if orphan_ind:
            findings.append(_finding("WARNING", individual_dir, orphan_ind, "orphan individual results", "artifact ID absent from queue", "high", "Keep outside canonical cohort pending provenance."))

    original_log = artifacts / "qwen3b_run.log"
    log_evidence: dict[str, str] = {}
    if original_log.exists():
        try:
            log_text = original_log.read_text(encoding="utf-8", errors="replace")
            starts = list(re.finditer(r"RUNNING\s+(T\d+)\s*[×x]\s*(C[1-4])", log_text))
            for index, match in enumerate(starts):
                end = starts[index + 1].start() if index + 1 < len(starts) else len(log_text)
                rid = f"{match.group(1)}_{match.group(2)}"
                block = log_text[match.start():end]
                relevant = [line.strip() for line in block.splitlines()
                            if any(token in line.lower() for token in ("finished", "traceback", "apierror", "model :"))]
                log_evidence[rid] = "\n".join(relevant)[:2000]
            model_match = re.search(r"^Model\s*:\s*(.+)$", log_text, flags=re.MULTILINE)
            if model_match:
                log_evidence["_model"] = model_match.group(1).strip()
            t1c3 = log_evidence.get("T01_C3", "")
            if "model 'strong' not found" in t1c3 and "timed out" in queue_by_id.get("T01_C3", {}).get("reason", "").lower():
                findings.append(_finding("ERROR", original_log, ["T01_C3"], "original queue/log failure reason conflict",
                                         "queue records request timeout; original launch log shows HTTP 404 model 'strong' not found followed by a dtype TypeError while recording the error",
                                         "high", "Retain both failure observations; do not choose a single cause without the complete launcher trace."))
        except OSError as exc:
            findings.append(_finding("WARNING", original_log, [], "original log unreadable", str(exc), "high", "Preserve and inspect log accessibility."))

    rec_root = artifacts
    attempts: list[dict] = []
    for path in sorted(artifacts.rglob("recovery_records.json")) + sorted(artifacts.rglob("attempts.jsonl")):
        for item in _read_records(path, findings):
            item["_source_path"] = str(path)
            attempts.append(item)
    # The journal and its checkpoint intentionally mirror the same attempt IDs.
    # Collapse identical representations for run-level accounting but preserve both
    # in source evidence; only conflicting payloads are a duplicate-ID defect.
    by_attempt_id: dict[str, list[dict]] = defaultdict(list)
    for item in attempts:
        if item.get("attempt_id"):
            by_attempt_id[str(item["attempt_id"])].append(item)
    duplicate_attempts = []
    repeated_in_source = []
    unique_attempts = []
    for attempt_id, mirrors in by_attempt_id.items():
        source_counts = Counter(m.get("_source_path") for m in mirrors)
        if any(count > 1 for count in source_counts.values()):
            repeated_in_source.append(attempt_id)
        normalized = [{k: v for k, v in row.items() if not k.startswith("_")} for row in mirrors]
        if any(value != normalized[0] for value in normalized[1:]):
            duplicate_attempts.append(attempt_id)
            unique_attempts.extend(mirrors)
        else:
            merged = dict(mirrors[0])
            merged["_source_paths"] = sorted({m["_source_path"] for m in mirrors})
            merged["_source_locations"] = [{"path": m.get("_source_path"), "location": m.get("_record_location")} for m in mirrors]
            unique_attempts.append(merged)
    unique_attempts.extend(a for a in attempts if not a.get("attempt_id"))
    if duplicate_attempts:
        findings.append(_finding("CRITICAL", rec_root, [a.get("run_id", "") for a in attempts if a.get("attempt_id") in duplicate_attempts],
                                 "conflicting duplicate attempt IDs", str(duplicate_attempts), "high", "Reconcile checkpoint and journal by attempt_id; preserve both records."))
    if repeated_in_source:
        findings.append(_finding("CRITICAL", rec_root, [a.get("run_id", "") for a in attempts if a.get("attempt_id") in repeated_in_source],
                                 "duplicate attempt ID repeated within one source", str(repeated_in_source), "high", "Do not count duplicate journal/checkpoint entries as separate executions."))
    orphan_attempts = sorted({str(a.get("run_id")) for a in attempts if a.get("run_id") and a.get("run_id") not in queue_by_id})
    if orphan_attempts:
        findings.append(_finding("WARNING", rec_root, orphan_attempts, "orphan recovery attempts", "attempt run IDs are absent from the frozen queue", "high", "Preserve separately; do not merge into canonical cohort."))
    unlinked_records = [a for a in attempts if not a.get("run_id")]
    if unlinked_records:
        findings.append(_finding("ERROR", rec_root, [], "unlinked attempt records",
                                 f"{len(unlinked_records)} attempt/checkpoint entries have no logical run ID", "high",
                                 "Preserve records and resolve identity before task linkage or aggregation."))
    journal_mismatches = []
    for attempt_id, mirrors in by_attempt_id.items():
        sources = [m.get("_source_path", "") for m in mirrors]
        if any("ATTEMPTS_" in source for source in sources):
            kinds = {"journal" if source.endswith("attempts.jsonl") else "checkpoint" for source in sources}
            if kinds != {"journal", "checkpoint"}:
                journal_mismatches.append((attempt_id, mirrors[0].get("run_id", "")))
    if journal_mismatches:
        findings.append(_finding("WARNING", rec_root, [rid for _, rid in journal_mismatches],
                                 "attempt journal/checkpoint representation differs",
                                 f"attempt IDs without both representations={[aid for aid, _ in journal_mismatches]}", "medium",
                                 "Reconcile from valid evidence before resuming; do not rewrite a checkpoint from partial state."))
    attempts = unique_attempts
    terminal = defaultdict(list)
    for a in attempts:
        if a.get("run_id"):
            terminal[a["run_id"]].append(a)
    traces_by_run: dict[str, list[dict]] = defaultdict(list)
    for trace in sorted(artifacts.rglob("traces/*.json")):
        try:
            t = _json(trace)
            trace_id = str(t.get("run_id", ""))
            if trace_id:
                entry = {"path": str(trace), "status": t.get("status"),
                         "events": len(t.get("events", [])), "attempt_id": trace_id,
                         "final_spec_available": bool(t.get("final_spec"))}
                matched = False
                for logical_id in queue_by_id:
                    if trace_id == logical_id or trace_id.startswith(logical_id + "_"):
                        traces_by_run[logical_id].append(entry)
                        matched = True
                if not matched:
                    findings.append(_finding("WARNING", trace, [], "orphan trace", f"trace run_id={trace_id} does not map to queue ID", "high", "Preserve and reconcile against attempt journal."))
            if t.get("status") == "running":
                rid = t.get("run_id", "")
                findings.append(_finding("ERROR", trace, [rid] if rid else [], "trace left running",
                                         "trace has no terminal status; not a success", "high", "Reconcile as interrupted while preserving the trace."))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(_finding("ERROR", trace, [], "malformed trace", str(exc), "high", "Preserve and classify as unknown/interrupted only with corroborating evidence."))

    runs = []
    unverified_success_ids = []
    for rid, qrow in queue_by_id.items():
        hist = terminal.get(rid, [])
        # A run-keyed checkpoint is not itself an attempt ID; retain every source record.
        statuses = [str(a.get("status", "unknown")).lower() for a in hist]
        success_records = [a for a in hist if a.get("status", "").lower() == "success" and _metric_record(a).get("status") == "success"]
        inst = individual.get(rid, {})
        inst_record = _metric_record(inst)
        if any(t.get("status") == "running" for t in traces_by_run.get(rid, [])) and not success_records:
            classification = "INTERRUPTED"
        elif qrow.get("status", "").upper() == "SUCCESS" and inst_record.get("status") == "success":
            classification = "VERIFIED SUCCESS"
        elif success_records:
            classification = "EXECUTED, OUTPUT UNVERIFIED"
        elif any(s == "running" for s in statuses):
            classification = "INTERRUPTED"
        elif any("timeout" in str(a.get("error_category", "")).lower() or "timed out" in str(_metric_record(a).get("reason", "")).lower() for a in hist):
            classification = "FAILED — TIMEOUT"
        elif hist and any(s == "failed" for s in statuses):
            classification = "FAILED — BUDGET/VALIDATION"
        elif qrow.get("status", "").upper() == "FAILED":
            reason = qrow.get("reason", "")
            if not hist and not inst_record.get("status"):
                classification = "MISSING ATTEMPT EVIDENCE"
            else:
                classification = "FAILED — NETWORK/PROVIDER" if "route to host" in reason.lower() else "FAILED — MODEL CONFIGURATION" if "not set in .env" in reason else "FAILED — TIMEOUT" if "timed out" in reason.lower() else "UNKNOWN"
        else:
            classification = "UNKNOWN"
        scored = any(bool(_metric_record(a).get("scoring_scope")) and _metric_record(a).get("metadata", {}).get("reference_supplied") is True for a in success_records)
        if classification == "EXECUTED, OUTPUT UNVERIFIED":
            unverified_success_ids.append(rid)
        chosen = success_records[-1] if success_records else {}
        chosen_record = _metric_record(chosen)
        aggregate = results.get(rid, {})
        conflict_flags = []
        if aggregate and aggregate.get("status", "").upper() != str(qrow.get("status", "")).upper():
            conflict_flags.append("aggregate_status_vs_original_queue")
        if rid == "T01_C3" and "model 'strong' not found" in log_evidence.get(rid, ""):
            conflict_flags.append("original_queue_vs_launcher_log_failure_reason")
        if success_records and any(s == "failed" for s in statuses):
            conflict_flags.append("success_and_failure_attempt_history")
        mismatched_attempt_configs = [a.get("attempt_id") or a.get("_record_location") for a in hist
                                      if a.get("configuration") and str(a.get("configuration")) != str(qrow.get("configuration"))]
        if mismatched_attempt_configs:
            conflict_flags.append("attempt_configuration_mismatch")
        norm_status = {
            "VERIFIED SUCCESS": "VERIFIED_SUCCESS",
            "EXECUTED, OUTPUT UNVERIFIED": "EXECUTED_OUTPUT_UNVERIFIED",
            "FAILED — BUDGET/VALIDATION": "RECORDED_FAILURE",
            "FAILED — TIMEOUT": "RECORDED_FAILURE",
            "INTERRUPTED": "INTERRUPTED_ATTEMPT",
            "MISSING ATTEMPT EVIDENCE": "MISSING_ATTEMPT_EVIDENCE",
            "UNKNOWN": "UNKNOWN_STATUS",
        }.get(classification, "UNKNOWN_STATUS")
        if conflict_flags and not success_records:
            norm_status = "CONFLICTING_RECORDS"
        if classification == "VERIFIED SUCCESS" and (not inst_record.get("scoring_scope") or inst_record.get("concept_recall_full") is None):
            norm_status = "INVALID_OR_INCOMPLETE_RESULT"
        chosen_time = chosen.get("finished_at") or chosen.get("started_at")
        evidence_path = str(chosen.get("_source_path") or individual_dir / f"{rid}.json")
        project_root_for_run = artifacts.parents[2] if len(artifacts.parents) > 2 else artifacts.parent
        ref_path = project_root_for_run / "tasks" / "reference" / f"{qrow.get('cohort_id')}.json"
        ref_hash = sha256(ref_path) if ref_path.is_file() else None
        runs.append({"run_id": rid, "task_id": qrow.get("task_id"), "configuration": qrow.get("configuration"),
                     "cohort_id": qrow.get("cohort_id"),
                     "original_queue_status": qrow.get("status"), "original_failure_reason": qrow.get("reason"),
                     "aggregate_result_status": aggregate.get("status"), "aggregate_result_reason": aggregate.get("reason"),
                     "individual_result_status": inst_record.get("status"), "attempt_statuses": statuses,
                     "attempt_count_records": len(hist), "best_supported_classification": classification,
                     "normalized_reconciled_status": norm_status, "source_artifact": evidence_path,
                     "record_location": chosen.get("_record_location"), "conflict_flags": conflict_flags,
                     "unresolved_status_reason": ("; ".join(conflict_flags) if conflict_flags else
                                                   "raw phenotype output or immutable provenance unavailable" if classification == "EXECUTED, OUTPUT UNVERIFIED" else None),
                     "recovery_timestamp": chosen_time,
                     "individual_result_path": str(individual_dir / f"{rid}.json"),
                     "reference_artifact_path": str(ref_path), "reference_sha256": ref_hash,
                     "original_log_excerpt": log_evidence.get(rid),
                     "original_log_model_label": log_evidence.get("_model"),
                     "trace_evidence": traces_by_run.get(rid, []),
                     "output_available": any(t.get("final_spec_available") for t in traces_by_run.get(rid, [])),
                     "result_record_available": inst_record.get("status") is not None,
                     "attempt_evidence": [{"attempt_id": a.get("attempt_id"), "status": a.get("status"),
                                           "source_path": a.get("_source_path"), "source_paths": a.get("_source_paths", []),
                                           "record_location": a.get("_record_location"),
                                           "model": a.get("model"), "error_category": a.get("error_category"),
                                           "reason": (a.get("error") or _metric_record(a).get("reason")),
                                           "started_at": a.get("started_at"), "finished_at": a.get("finished_at"),
                                           "trace_path": a.get("trace_path")} for a in hist],
                     "models_seen": sorted({str(a.get("model")) for a in hist if a.get("model")}),
                     "scored_recovery_success": scored,
                     "recorded_scoring_scope": chosen_record.get("scoring_scope"),
                     "recorded_full_recall": chosen_record.get("concept_recall_full"),
                     "metric_available": isinstance(chosen_record.get("concept_recall_full"), (int, float)),
                     "reference_supplied_recorded": chosen_record.get("metadata", {}).get("reference_supplied"),
                     "provenance_completeness": "PARTIAL" if scored else "NOT_AVAILABLE",
                     "hash_verification_state": "queue_verified; manifest_mismatch" if queue_hash == expected_sha256 else "queue_hash_mismatch",
                     "metric_provenance": "recorded; versions not bound" if scored else "unavailable or unverified"})
    if unverified_success_ids:
        findings.append(_finding("WARNING", rec_root, unverified_success_ids, "apparent success lacks independently reviewable output",
                                 "checkpoint success record exists; raw final phenotype/output is not bound to this record", "medium", "Retain as execution evidence only; do not use as independently validated phenotype."))
    config_mismatch_ids = [run["run_id"] for run in runs if "attempt_configuration_mismatch" in run.get("conflict_flags", [])]
    if config_mismatch_ids:
        findings.append(_finding("CRITICAL", artifacts, config_mismatch_ids, "attempt configuration mismatch",
                                 "attempt configuration field differs from original queue configuration", "high", "Do not merge the attempt with the queue task until identity is resolved."))

    scientific_summary = {}
    base_checkpoint = artifacts / "RECOVERY_QWEN3B" / "recovery_records.json"
    base_records = {}
    if base_checkpoint.exists():
        try:
            value = _json(base_checkpoint)
            if isinstance(value, dict):
                base_records = value
        except (OSError, json.JSONDecodeError):
            pass
    task_sets = {}
    for config in expected_configs:
        config_rows = [r for r in queue if r.get("configuration") == config]
        successes = []
        for row in config_rows:
            item = base_records.get(row.get("run_id"), {})
            record = _metric_record(item) if isinstance(item, dict) else {}
            value = record.get("concept_recall_full")
            if item.get("status") == "success" and record.get("status") == "success" and isinstance(value, (int, float)):
                successes.append((row["run_id"], row["task_id"], float(value)))
        task_sets[config] = {task for _, task, _ in successes}
        values = [value for _, _, value in successes]
        scientific_summary[config] = {"queue_denominator": len(config_rows), "recovery_records_denominator": sum(r.get("run_id") in base_records for r in config_rows),
                                      "successful_metric_n": len(values), "mean_full_concept_recall": sum(values) / len(values) if values else None,
                                      "successful_run_ids": [rid for rid, _, _ in successes],
                                      "successful_task_ids": sorted(task_sets[config]), "patient_metrics_available": False}
    pairwise = {}
    for index, first in enumerate(expected_configs):
        for second in expected_configs[index + 1:]:
            shared = sorted(task_sets[first] & task_sets[second])
            pairwise[f"{first}_vs_{second}"] = {"paired_successful_task_count": len(shared), "task_ids": shared}
    mirrored_attempt_ids = sorted(aid for aid, mirrors in by_attempt_id.items()
                                  if len({m.get("_source_path") for m in mirrors}) > 1
                                  and aid not in duplicate_attempts)
    attempt_source_reconciliation = {"unique_attempt_ids": len(by_attempt_id),
                                    "identical_checkpoint_journal_mirrors": mirrored_attempt_ids,
                                    "conflicting_duplicate_attempt_ids": duplicate_attempts,
                                    "repeated_within_source_attempt_ids": repeated_in_source,
                                    "mirror_policy": "identical copies count as one attempt; all source paths retained"}

    # No artifact hashes or immutable version IDs are present for most scientific inputs.
    for key, paths in (("task questions", [project_root / "tasks" / "benchmark_questions.jsonl"]),
                       ("Eunomia/vocabulary databases", [project_root / "data" / "eunomia.duckdb", project_root / "data" / "vocab.duckdb"])):
        for path in paths:
            if not path.exists():
                findings.append(_finding("WARNING", path, ids, f"missing {key} provenance artifact", "file absent at expected location", "medium", "Record immutable source/version and hash before new execution."))
    # Version fields absent from historical run metadata are provenance gaps even
    # where a scalar metric was recorded successfully.
    recovery_success_ids = [a.get("run_id", "") for a in attempts
                            if a.get("status", "").lower() == "success"
                            and _metric_record(a).get("status") == "success"]
    if queue:
        findings.append(_finding("WARNING", rec_root, recovery_success_ids or ids,
                                 "missing immutable model/task/reference/vocabulary/scoring provenance",
                                 "records identify model labels and scoring scope but do not bind every run to model digest, task/reference hashes, vocabulary database version, and scorer version",
                                 "high", "Limit metrics to descriptive records; capture immutable input/model/scorer identities before continuation."))
    metric_denominators_complete = bool(scientific_summary) and all(
        summary["successful_metric_n"] == summary["queue_denominator"] for summary in scientific_summary.values())
    if not metric_denominators_complete:
        denom = {config: {"n": row["successful_metric_n"], "queue_denominator": row["queue_denominator"]}
                 for config, row in scientific_summary.items()}
        findings.append(_finding("WARNING", results_path, ids, "metric denominator missingness",
                                 f"successful metric denominators are incomplete/unequal: {denom}", "high", "Report per-configuration n and task IDs; do not rank selected successes."))

    findings.sort(key=lambda f: (f["severity"], f["evidence_path"], f["condition"], f["affected_ids"]))
    return {"queue_path": str(queue_path), "queue_sha256": queue_hash, "expected_queue_sha256": expected_sha256,
            "queue_rows": len(queue), "queue_status_counts": dict(original), "task_count": len(tasks),
            "configuration_counts": dict(configs), "runs": runs, "attempt_records": attempts,
            "queue_schema_valid": queue_schema_ok, "manifest_present": manifest_path.exists(),
            "manifest_hashes": manifest_hashes,
            "results_present": results_path.exists(), "attempt_records_present": bool(attempts),
            "raw_output_complete": False, "model_provenance_complete": False,
            "metric_denominators_complete": metric_denominators_complete,
            "scientific_summary_root_recovery_only": scientific_summary,
            "pairwise_successful_task_coverage": pairwise,
            "attempt_source_reconciliation": attempt_source_reconciliation,
            "findings": findings, "read_only": True,
            "attempt_aggregation_policy": "all evidence retained; no attempt is allowed to overwrite prior history"}
