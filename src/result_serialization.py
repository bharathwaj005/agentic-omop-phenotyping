"""Versioned, fail-closed serialization for newly produced run reports.

Historical benchmark files are intentionally not handled by this module.
Each report is one attempt artifact; aggregate evaluation is a separate view.
"""

from __future__ import annotations

import json
import os
import tempfile
import csv
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any


RESULT_SCHEMA_VERSION = 1
TERMINAL_STATUSES = {
    "success", "failed", "timeout", "interrupted", "budget_exhausted",
    "validator_exhausted", "completed",
}
RUN_RECORD_CSV_COLUMNS = ["schema_version", "logical_run_id", "attempt_id"]


def validate_result_report(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise TypeError("result report must be an object")
    if report.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError("unsupported or missing result schema_version")
    for key in ("logical_run_id", "attempt_id", "task_id", "configuration"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ValueError(f"result report requires non-empty {key}")
    status = report.get("status")
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"result status is not a recognized terminal state: {status!r}")
    if status == "success" and not isinstance(report.get("final_spec"), dict):
        raise ValueError("successful result requires a reviewable final_spec object")
    metrics = report.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        raise ValueError("metrics must be an object or null")
    return report


def write_result_report(path: str | Path, report: dict[str, Any]) -> str:
    """Validate and atomically create one report; never replace an artifact."""
    path = Path(path)
    validate_result_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with tmp.open(encoding="utf-8") as stream:
            round_trip = json.load(stream)
        validate_result_report(round_trip)
        if round_trip != report:
            raise ValueError("serialized result did not round-trip exactly")
        # link() is create-only, unlike replace(); existing evidence survives.
        os.link(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()
    return str(path)


def write_run_records_csv(records: Any, path: str | Path) -> str:
    """Atomically write fixed-width, versioned evaluation projections."""
    records = list(records)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if records:
        record_fields = [field.name for field in fields(records[0])]
    else:
        from src.metrics.evaluation import RunRecord
        record_fields = [field.name for field in fields(RunRecord)]
    columns = RUN_RECORD_CSV_COLUMNS + record_fields
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise")
            writer.writeheader()
            for record in records:
                row = asdict(record)
                if row.get("status") not in TERMINAL_STATUSES:
                    raise ValueError(f"result status is not terminal: {row.get('status')!r}")
                metadata = row.get("metadata") or {}
                output = {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "logical_run_id": f"{row['task_id']}_{row['configuration']}",
                    "attempt_id": metadata.get("attempt_id"),
                }
                for key, value in row.items():
                    output[key] = (json.dumps(value, sort_keys=True, default=str)
                                   if isinstance(value, (dict, list)) else value)
                writer.writerow(output)
            stream.flush()
            os.fsync(stream.fileno())
        with tmp.open(newline="", encoding="utf-8") as stream:
            parsed = list(csv.reader(stream))
        if not parsed or any(len(row) != len(columns) for row in parsed):
            raise ValueError("serialized CSV has inconsistent row width")
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()
    return str(path)
