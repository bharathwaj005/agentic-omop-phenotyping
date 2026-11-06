#!/usr/bin/env python3
"""Export descriptive summaries for the preserved five-run recovery batch.

This is exploratory only. It reads existing records and references, never the
frozen queue, and does not reconstruct missing predicted concept IDs or traces.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from src.metrics.evaluation import RunRecord, summarize_runs


DEFAULT_INPUT = Path(
    "/media/bharathwaj/HDD_Storage/project_jbi/results/benchmark_runs/"
    "V5_3_REAL_RUN/RECOVERY_QWEN3B_BATCH5_20261022/recovery_records.json"
)

CSV_FIELDS = [
    "run_id", "task_id", "cohort_id", "configuration", "status", "model",
    "elapsed_seconds", "llm_calls", "tool_calls", "input_tokens",
    "output_tokens", "full_precision", "full_recall", "full_f1",
    "full_jaccard", "entry_precision", "entry_recall", "entry_f1",
    "entry_jaccard", "cohort_jaccard", "failure_reason",
]


def load_rows(path: Path) -> list[dict]:
    source = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for run_id, run in source.items():
        record = run.get("record", {})
        rows.append({
            "run_id": run_id,
            "task_id": run.get("task_id"),
            "cohort_id": run.get("cohort_id"),
            "configuration": run.get("configuration"),
            "status": run.get("status"),
            "model": run.get("model"),
            "elapsed_seconds": run.get("elapsed_seconds"),
            "llm_calls": record.get("llm_calls"),
            "tool_calls": record.get("tool_calls"),
            "input_tokens": record.get("input_tokens"),
            "output_tokens": record.get("output_tokens"),
            "full_precision": record.get("concept_precision_full"),
            "full_recall": record.get("concept_recall_full"),
            "full_f1": record.get("concept_f1_full"),
            "full_jaccard": record.get("concept_jaccard_full"),
            "entry_precision": record.get("concept_precision_entry"),
            "entry_recall": record.get("concept_recall_entry"),
            "entry_f1": record.get("concept_f1_entry"),
            "entry_jaccard": record.get("concept_jaccard_entry"),
            "cohort_jaccard": record.get("cohort_jaccard"),
            "failure_reason": run.get("error") or record.get("reason"),
            "_record": record,
            "_metadata": record.get("metadata", {}),
        })
    return rows


def write_outputs(source: Path, out: Path) -> dict:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(source)

    with (out / "exploratory_run_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in CSV_FIELDS})

    # Use the repository's metric aggregation implementation on recorded
    # values. Predicted ID sets are absent, so metrics are not reconstructed.
    records = []
    for config in sorted({r["configuration"] for r in rows}):
        for r in (row for row in rows if row["configuration"] == config):
            records.append(RunRecord(
            task_id=r["task_id"], configuration=config, status=r["status"],
            concept_precision_full=r["full_precision"],
            concept_recall_full=r["full_recall"], concept_f1_full=r["full_f1"],
            concept_jaccard_full=r["full_jaccard"],
            concept_precision_entry=r["entry_precision"],
            concept_recall_entry=r["entry_recall"], concept_f1_entry=r["entry_f1"],
            concept_jaccard_entry=r["entry_jaccard"],
            cohort_jaccard=r["cohort_jaccard"], llm_calls=r["llm_calls"],
            tool_calls=r["tool_calls"], input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"], wall_seconds=r["elapsed_seconds"],
            ))

    summary_all = summarize_runs(records)

    task_config_counts = Counter((r["task_id"], r["configuration"]) for r in rows)
    failure_rows = [{
        "run_id": r["run_id"], "task_id": r["task_id"],
        "configuration": r["configuration"], "status": r["status"],
        "failure_reason": r["failure_reason"],
        "validator_retries": r["_metadata"].get("validator_retries"),
        "llm_calls": r["llm_calls"],
        "resolved_sizes": r["_metadata"].get("resolved_sizes"),
    } for r in rows if r["status"] != "success"]
    per_task_configuration = {}
    for row in rows:
        key = f"{row['task_id']}::{row['configuration']}"
        item = per_task_configuration.setdefault(key, {
            "task_id": row["task_id"], "configuration": row["configuration"],
            "n_runs": 0, "n_success": 0, "n_failed": 0,
        })
        item["n_runs"] += 1
        if row["status"] == "success":
            item["n_success"] += 1
        else:
            item["n_failed"] += 1

    summary = {
        "analysis_scope": "exploratory_existing_recovery_batch_only",
        "source_file": str(source),
        "n_runs": len(rows),
        "n_success": sum(r["status"] == "success" for r in rows),
        "n_failed": sum(r["status"] != "success" for r in rows),
        "per_configuration": summary_all["by_configuration"],
        "per_task_configuration": per_task_configuration,
        "task_configuration_duplicates": [
            {"task_id": t, "configuration": c, "count": n}
            for (t, c), n in task_config_counts.items() if n > 1
        ],
        "failure_rows": failure_rows,
        "limitations": [
            "This five-run batch is not a complete benchmark sample.",
            "The saved records do not contain predicted concept IDs or full traces.",
            "Concept metrics are reported as recorded and are not independently recomputed.",
            "Input/output token counts and cost are unavailable in these records.",
            "Cohort patient sets are unavailable; cohort Jaccard remains null.",
            "No inferential comparison or uncertainty interval is justified by this batch.",
        ],
    }
    (out / "exploratory_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failure_fields = ["run_id", "task_id", "configuration", "status",
                      "failure_reason", "validator_retries", "llm_calls",
                      "resolved_sizes"]
    with (out / "failure_taxonomy.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=failure_fields)
        writer.writeheader()
        writer.writerows(failure_rows)

    def display(value):
        return "—" if value is None else str(value)

    table_lines = [
        "| Run | Task/config | Status | Elapsed (s) | LLM calls | Tool calls | Full recall | Entry recall |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table_lines.append(
            f"| {row['run_id']} | {row['task_id']}/{row['configuration']} | "
            f"{row['status']} | {display(row['elapsed_seconds'])} | "
            f"{display(row['llm_calls'])} | {display(row['tool_calls'])} | "
            f"{display(row['full_recall'])} | {display(row['entry_recall'])} |"
        )
    (out / "table_1_run_metrics.md").write_text(
        "\n".join(table_lines) + "\n", encoding="utf-8")

    status_lines = [
        "| Status | Runs | Fraction |",
        "|---|---:|---:|",
        f"| Success | {summary['n_success']} | {summary['n_success'] / len(rows):.3f} |",
        f"| Failed | {summary['n_failed']} | {summary['n_failed'] / len(rows):.3f} |",
    ]
    (out / "table_2_completion.md").write_text(
        "\n".join(status_lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = write_outputs(args.input, args.out)
    print(json.dumps({k: summary[k] for k in ("n_runs", "n_success", "n_failed")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
