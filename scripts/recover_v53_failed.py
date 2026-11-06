from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
import argparse
import csv
import hashlib
import json
import os
import tempfile
import time
import traceback
import urllib.request
import uuid

import duckdb

from src import paths
from src.llm.client import make_client
from src.runner.experiment import run_experiment, benchmark_configurations
from src.pipelines.budget import Budget
from src.logging.provenance import RunLog
from src.agents.base import prompt_hashes

QUEUE = Path("/media/bharathwaj/HDD_Storage/project_jbi/results/benchmark_runs/V5_3_REAL_RUN/RUN_QUEUE.csv")
EXPECTED_SHA256 = "ac668c67c85ad69d061476c071f17c55ef24b0b4c913cebd42184687ddea6a66"
OUT = QUEUE.parent / "RECOVERY_QWEN3B"
MODEL = "jbi-qwen2.5:3b-8k"

def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, default=str)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Validate the completed temporary artifact before replacing state.
        with tmp.open(encoding="utf-8") as stream:
            validated = json.load(stream)
        if validated != obj:
            raise ValueError(f"temporary checkpoint validation mismatch: {tmp}")
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_checkpoint(path):
    """Load a checkpoint, treating only a zero-byte file as empty state."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"checkpoint must contain a JSON object: {path}")
    return {key: item for key, item in value.items() if isinstance(item, dict)}


def load_attempt_journal(path):
    """Read valid JSON object lines; skip and report malformed/null entries."""
    rows = []
    issues = []
    path = Path(path)
    if not path.exists():
        return rows, issues
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append((line_number, f"malformed JSON: {exc.msg}"))
                continue
            if not isinstance(value, dict):
                issues.append((line_number, f"expected object, got {type(value).__name__}"))
                continue
            rows.append(value)
    return rows, issues


def append_attempt_journal(path, row):
    """Durably append one JSON object without joining an unterminated tail."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(row, default=str) + "\n").encode("utf-8")
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        if end:
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                # Preserve the partial/malformed prior line as evidence while
                # ensuring this new record remains independently replayable.
                stream.seek(0, os.SEEK_END)
                stream.write(b"\n")
        stream.seek(0, os.SEEK_END)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def recovery_status(status):
    """Keep recognized terminal states distinct; unknown values fail closed."""
    value = str(status or "failed").lower()
    return value if value in {"success", "failed", "timeout"} else "failed"


def records_from_journal(checkpoint_records, journal_rows):
    """Reconcile durable journal entries over checkpoint state, retaining successes."""
    records = dict(checkpoint_records)
    latest = {}
    successful = {}
    for row in journal_rows:
        run_id = row.get("run_id")
        if not run_id:
            continue
        latest[run_id] = row
        if row.get("status") == "success":
            successful[run_id] = row
    for run_id, row in latest.items():
        existing = records.get(run_id)
        if existing and existing.get("status") == "success":
            continue
        records[run_id] = successful.get(run_id, row)
    return records


def error_category(error):
    text = str(error or "").lower()
    if "repeated identical" in text or "duplicate tool" in text:
        return "duplicate_tool_loop"
    if "budget exceeded" in text:
        return "budget_exhausted"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "validator" in text or "validationerror" in text or "invalid specification" in text:
        return "validation_failure"
    if "connection" in text or "remote end closed" in text or "network error" in text:
        return "connection_failure"
    if "reference" in text or "cohort mismatch" in text:
        return "reference_failure"
    return "pipeline_failure" if text else None


def usage_value(record, trace_totals, name):
    value = record.get(name)
    return value if value is not None else trace_totals.get(name)


def reconcile_interrupted_traces(queue, output_dir, journal_rows,
                                 baseline_records, current_records):
    """Turn orphaned running traces into explicit failed attempt records."""
    trace_dir = Path(output_dir) / "traces"
    if not trace_dir.exists():
        return []
    queue_by_key = {(row["task_id"], row["configuration"]): row for row in queue}
    journal_attempt_ids = {row.get("attempt_id") for row in journal_rows}
    reconciled = []
    journal = Path(output_dir) / "attempts.jsonl"
    for trace_path in sorted(trace_dir.glob("*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(trace, dict):
            continue
        attempt_id = trace.get("run_id")
        if (not isinstance(attempt_id, str) or not attempt_id
                or trace.get("status") != "running"
                or attempt_id in journal_attempt_ids):
            continue
        queue_row = queue_by_key.get((str(trace.get("task_id")), str(trace.get("config"))))
        if queue_row is None:
            continue
        run_id = queue_row["run_id"]
        trace_totals = trace.get("totals", {})
        if not isinstance(trace_totals, dict):
            trace_totals = {}
        attempt_number = int((baseline_records.get(run_id) or {}).get(
            "_prior_attempt_count", int(run_id in baseline_records)
        )) + sum(item.get("run_id") == run_id for item in journal_rows) + 1
        entry = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "task_id": str(trace.get("task_id")),
            "cohort_id": queue_row.get("cohort_id"),
            "configuration": str(trace.get("config")),
            "status": "failed",
            "execution_outcome": "interrupted",
            "started_at": None,
            # The source trace cannot establish a process completion time.
            "finished_at": None,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": trace_totals.get("wall_time_s"),
            "model": MODEL,
            "record": None,
            "error": "attempt interrupted before result checkpoint; inspect trace",
            "error_category": "interrupted",
            "trace_path": str(trace_path),
            "llm_calls": trace_totals.get("llm_calls"),
            "tool_calls": trace_totals.get("tool_calls"),
            "input_tokens": trace_totals.get("input_tokens"),
            "output_tokens": trace_totals.get("output_tokens"),
        }
        append_attempt_journal(journal, entry)
        journal_rows.append(entry)
        journal_attempt_ids.add(attempt_id)
        current_records[run_id] = entry
        reconciled.append(entry)
    return reconciled


def eligible_failed_rows(queue, baseline_records, current_records, journal_rows,
                         max_attempts):
    """Select failed queue rows while preserving successes and retry bounds."""
    eligible = []
    for row in queue:
        if row.get("status") != "FAILED":
            continue
        run_id = row["run_id"]
        journal_latest = next((item for item in reversed(journal_rows)
                               if item.get("run_id") == run_id), None)
        prior = (current_records.get(run_id) or journal_latest
                 or baseline_records.get(run_id))
        if prior and prior.get("status") == "success":
            continue
        attempts = int((baseline_records.get(run_id) or {}).get(
            "_prior_attempt_count", int(run_id in baseline_records)
        )) + sum(
            item.get("run_id") == run_id for item in journal_rows
        )
        if attempts < max_attempts:
            eligible.append(row)
    return eligible


def validate_run_id_selection(queue, run_id):
    """Reject explicit selections that cannot target one failed queue row."""
    if run_id is None:
        return
    matches = [row for row in queue if row.get("run_id") == run_id]
    if not matches:
        raise ValueError(f"unknown queue run ID: {run_id}")
    if len(matches) != 1:
        raise ValueError(f"queue run ID is not unique: {run_id}")
    if matches[0].get("status") != "FAILED":
        raise ValueError(f"queue run ID is not failed and recoverable: {run_id}")


class RecoveryRunLog(RunLog):
    """Provenance log whose unique output stays beside this recovery attempt."""
    def __init__(self, *args, trace_path: Path, **kwargs):
        self._trace_path = trace_path
        super().__init__(*args, **kwargs)

    class _CheckpointingStepCtx(RunLog._StepCtx):
        def __exit__(self, exc_type, exc, tb):
            result = super().__exit__(exc_type, exc, tb)
            self.log.save()
            return result

    def step(self, kind, actor, **detail):
        context = super().step(kind, actor, **detail)
        return self._CheckpointingStepCtx(self, context.ev)

    def note(self, actor, **detail):
        super().note(actor, **detail)
        self.save()

    def path(self):
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)
        return self._trace_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1,
                        help="Run at most N eligible entries; 0 means all (default: 1)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Unique attempt directory; reuse this exact path to resume")
    parser.add_argument("--max-attempts", type=int, default=2,
                        help="Maximum total attempts per queue run, counting legacy checkpoint attempts")
    parser.add_argument("--run-id", default=None,
                        help="Restrict this launch to one frozen queue run ID")
    args = parser.parse_args()
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts must be at least 1")

    digest = hashlib.sha256(QUEUE.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"STOP: queue checksum changed: {digest}")

    with QUEUE.open(newline="", encoding="utf-8") as f:
        queue = list(csv.DictReader(f))

    try:
        validate_run_id_selection(queue, args.run_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    failed = [r for r in queue if r["status"] == "FAILED"]
    if len(queue) != 80 or len(failed) != 79:
        raise SystemExit(f"STOP: expected 80 total/79 failed, found {len(queue)}/{len(failed)}")

    task_file = Path("tasks/benchmark_questions.jsonl")
    tasks = {}
    for line in task_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            tasks[str(item["task_id"])] = {
                "task_id": str(item["task_id"]),
                "question": str(item["question"]),
            }

    configs = {c.name: c for c in benchmark_configurations()}
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = OUT / f"ATTEMPTS_{stamp}_{uuid.uuid4().hex[:6]}"
        output_dir.mkdir(parents=True, exist_ok=False)
    else:
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "recovery_records.json"
    journal = output_dir / "attempts.jsonl"
    legacy_records = {}
    historical_paths = [OUT / "recovery_records.json"] + sorted(
        OUT.parent.glob("RECOVERY_QWEN3B_*/recovery_records.json")
    )
    for historical_path in historical_paths:
        if not historical_path.exists():
            continue
        historical = json.loads(historical_path.read_text(encoding="utf-8"))
        for run_id, item in historical.items():
            prior = legacy_records.setdefault(run_id, {
                "status": item.get("status"), "_prior_attempt_count": 0
            })
            prior["_prior_attempt_count"] += 1
            if item.get("status") == "success":
                prior["status"] = "success"
            elif prior.get("status") != "success":
                prior["status"] = item.get("status")
    checkpoint_records = load_checkpoint(checkpoint)
    journal_rows, journal_issues = load_attempt_journal(journal)
    records = records_from_journal(checkpoint_records, journal_rows)
    for line_number, issue in journal_issues:
        print(f"Preserved journal line {line_number}; skipped during replay ({issue}).", flush=True)

    # Persist replayed evidence before any new attempt can update state.
    if records != checkpoint_records:
        atomic_json(checkpoint, records)

    interrupted = reconcile_interrupted_traces(
        queue, output_dir, journal_rows, legacy_records, records
    )
    if interrupted:
        atomic_json(checkpoint, records)
        for entry in interrupted:
            print(f"Reconciled interrupted attempt {entry['attempt_id']} as failed; trace preserved.", flush=True)

    pending = eligible_failed_rows(
        queue, legacy_records, records, journal_rows, args.max_attempts
    )

    if args.run_id:
        pending = [row for row in pending if row["run_id"] == args.run_id]

    if args.limit:
        pending = pending[:args.limit]

    print(f"Frozen queue SHA256 verified: {digest}", flush=True)
    print(f"Original queue preserved: {QUEUE}", flush=True)
    print(f"Recovery directory: {output_dir}", flush=True)
    print(f"Failed in original queue: {len(failed)}", flush=True)
    latest_journal = {}
    for item in journal_rows:
        latest_journal[item.get("run_id")] = item
    print(f"Already recovered successfully: {sum((records.get(r['run_id']) or latest_journal.get(r['run_id']) or legacy_records.get(r['run_id']) or {}).get('status') == 'success' for r in failed)}", flush=True)
    print(f"This launch will attempt: {len(pending)}", flush=True)
    print(f"Ollama model: {MODEL}", flush=True)

    if not pending:
        print("No pending failed runs.", flush=True)
        return

    vocab = duckdb.connect(str(paths.VOCAB_DB), read_only=True)
    try:
        paths.configure(vocab)
        client = make_client("A", fake=False)
        if "127.0.0.1:11434" not in client.base_url and "localhost:11434" not in client.base_url:
            raise RuntimeError(f"Refusing non-local model endpoint: {client.base_url}")
        tags_url = client.base_url.replace("/v1", "") + "/api/tags"
        with urllib.request.urlopen(tags_url, timeout=5) as response:
            available = {m.get("name") for m in json.loads(response.read()).get("models", [])}
        if MODEL not in available:
            raise RuntimeError(f"Required Ollama model is not available: {MODEL}")
        budget = Budget()
        models = {
            "planner": MODEL,
            "concept": MODEL,
            "builder": MODEL,
            "critic": MODEL,
            "single_agent": MODEL,
        }

        for index, row in enumerate(pending, 1):
            run_id = row["run_id"]
            task_id = str(row["task_id"])
            config_name = row["configuration"]
            cohort_id = str(row["cohort_id"])
            started = datetime.now().astimezone().isoformat()
            attempt_id = f"{run_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
            attempt_number = int((legacy_records.get(run_id) or {}).get(
                "_prior_attempt_count", int(run_id in legacy_records)
            )) + sum(
                item.get("run_id") == run_id for item in journal_rows
            ) + 1
            clock = time.monotonic()
            print(f"\n[{index}/{len(pending)}] START {run_id}", flush=True)

            try:
                if task_id not in tasks:
                    raise ValueError(f"Task {task_id} missing from benchmark questions")
                if config_name not in configs:
                    raise ValueError(f"Unknown configuration: {config_name}")

                ref_path = paths.REFERENCE_DIR / f"{cohort_id}.json"
                if not ref_path.exists():
                    raise FileNotFoundError(f"Reference missing: {ref_path}")
                reference = json.loads(ref_path.read_text(encoding="utf-8"))
                if str(reference.get("cohort_id")) != cohort_id:
                    raise ValueError(f"Reference cohort mismatch for {run_id}")

                task = type("Task", (), tasks[task_id])()
                trace = RecoveryRunLog(
                    run_id=attempt_id, config=config_name, task_id=task_id,
                    repeat=attempt_number, models=models,
                    prompt_hashes=prompt_hashes(
                        ["single_agent"] if config_name == "C2" else
                        ["planner", "concept", "builder"] +
                        (["critic"] if configs[config_name].use_critic else [])
                    ),
                    caps=budget.to_dict(),
                    trace_path=output_dir / "traces" / f"{attempt_id}.json",
                )
                result = run_experiment(
                    tasks=[task],
                    configurations=[configs[config_name]],
                    client=client,
                    vocab_con=vocab,
                    models=models,
                    budget=budget,
                    reference_loader=lambda _task_id, ref=reference: ref,
                    log_factory=lambda **_kwargs: trace,
                )
                if len(result.records) != 1:
                    raise RuntimeError(f"Expected one result, got {len(result.records)}")
                record = asdict(result.records[0])
                status = recovery_status(record.get("status"))
                final_spec = record.get("final_spec")
                trace_totals = trace.totals()
                entry = {
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "task_id": task_id,
                    "cohort_id": cohort_id,
                    "configuration": config_name,
                    "status": status,
                    "execution_outcome": "completed",
                    "pipeline_status": record.get("status"),
                    "output_state": ("validated_spec_present"
                                     if isinstance(final_spec, dict)
                                     else "missing_or_unverified"),
                    "publication_eligible": bool(
                        status == "success" and isinstance(final_spec, dict)
                    ),
                    "started_at": started,
                    "finished_at": datetime.now().astimezone().isoformat(),
                    "elapsed_seconds": round(time.monotonic() - clock, 2),
                    "model": MODEL,
                    "record": record,
                    "error": None,
                    "error_category": error_category(record.get("reason")),
                    "tool_calls": usage_value(record, trace_totals, "tool_calls"),
                    "llm_calls": usage_value(record, trace_totals, "llm_calls"),
                    "input_tokens": usage_value(record, trace_totals, "input_tokens"),
                    "output_tokens": usage_value(record, trace_totals, "output_tokens"),
                }
                trace.finish(status=status, final_spec=final_spec,
                             error=record.get("reason"))
            except Exception as exc:
                entry = {
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "task_id": task_id,
                    "cohort_id": cohort_id,
                    "configuration": config_name,
                    "status": "failed",
                    "started_at": started,
                    "finished_at": datetime.now().astimezone().isoformat(),
                    "elapsed_seconds": round(time.monotonic() - clock, 2),
                    "model": MODEL,
                    "record": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_category": error_category(exc),
                    "traceback": traceback.format_exc(),
                }

            records[run_id] = entry
            journal_row = dict(entry)
            append_attempt_journal(journal, journal_row)
            journal_rows.append(journal_row)
            atomic_json(checkpoint, records)

            with (output_dir / "recovery_progress.csv.tmp").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "run_id", "task_id", "cohort_id", "configuration",
                    "status", "elapsed_seconds", "error"
                ])
                writer.writeheader()
                for saved in records.values():
                    writer.writerow({k: saved.get(k) for k in writer.fieldnames})
            (output_dir / "recovery_progress.csv.tmp").replace(output_dir / "recovery_progress.csv")

            successes = sum(x.get("status") == "success" for x in records.values())
            failures = sum(x.get("status") == "failed" for x in records.values())
            print(
                f"[{index}/{len(pending)}] {run_id}: {entry['status']} "
                f"in {entry['elapsed_seconds']}s | recovered success={successes}, "
                f"failed attempts={failures}",
                flush=True,
            )
            if entry.get("error"):
                print("ERROR:", entry["error"], flush=True)
            elif entry.get("record", {}).get("reason"):
                print("Reason:", entry["record"]["reason"], flush=True)

        print(f"\nCheckpoint: {checkpoint}", flush=True)
        print("Original RUN_QUEUE.csv remains unchanged.", flush=True)
    finally:
        vocab.close()

if __name__ == "__main__":
    main()
