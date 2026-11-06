from pathlib import Path
from datetime import datetime
from dataclasses import asdict
import csv
import json
import sys
import time

import duckdb

from src import paths
from src.llm.client import make_client, model_for
from src.runner.experiment import run_experiment, benchmark_configurations
from src.pipelines.budget import Budget


# ----- Unique output directory: never overwrite previous runs -----
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_dir = paths.RESULTS_DIR / "local_ollama_autosave" / stamp
output_dir.mkdir(parents=True, exist_ok=False)

log_handle = (output_dir / "terminal.log").open(
    "a", encoding="utf-8", buffering=1
)


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


sys.stdout = Tee(sys.__stdout__, log_handle)
sys.stderr = Tee(sys.__stderr__, log_handle)


def atomic_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def save_checkpoint(records, state, current_config=None, error=None):
    rows = [asdict(record) for record in records]

    # Complete structured records
    atomic_json(output_dir / "results.json", rows)

    # Spreadsheet-friendly copy
    csv_path = output_dir / "results.csv"
    csv_temp = csv_path.with_suffix(".csv.tmp")
    columns = list(rows[0].keys()) if rows else []

    with csv_temp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if columns:
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    key: (
                        json.dumps(value, default=str)
                        if isinstance(value, (dict, list, tuple))
                        else value
                    )
                    for key, value in row.items()
                })
    csv_temp.replace(csv_path)

    # Progress checkpoint, updated after every configuration
    atomic_json(output_dir / "progress.json", {
        "run_timestamp": stamp,
        "state": state,
        "current_configuration": current_config,
        "completed_records": len(rows),
        "completed_configurations": [
            row.get("configuration") for row in rows
        ],
        "error": error,
        "output_directory": str(output_dir),
    })

    # Human-readable summary
    lines = [
        "JBI LOCAL OLLAMA BENCHMARK",
        f"Timestamp: {stamp}",
        f"State: {state}",
        f"Output directory: {output_dir}",
        "",
    ]
    for row in rows:
        lines.append(
            f"{row.get('configuration')} | "
            f"{row.get('status')} | "
            f"LLM calls={row.get('llm_calls')} | "
            f"Tool calls={row.get('tool_calls')} | "
            f"Seconds={row.get('wall_seconds')} | "
            f"Reason={row.get('reason') or ''}"
        )
    if error:
        lines.extend(["", f"ERROR: {error}"])

    summary_tmp = output_dir / "summary.txt.tmp"
    summary_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary_tmp.replace(output_dir / "summary.txt")


# ----- Load T01 only -----
task_file = Path("tasks/benchmark_questions.jsonl")
task = None

for line in task_file.read_text(encoding="utf-8").splitlines():
    if line.strip():
        row = json.loads(line)
        if str(row.get("task_id")) == "T01":
            task = {
                "task_id": "T01",
                "question": str(row["question"]),
            }
            break

if task is None:
    raise RuntimeError("T01 not found in benchmark questions.")

# Frozen reference: evaluator-side only; never inserted into the question.
reference_path = paths.REFERENCE_DIR / "134.json"
if not reference_path.exists():
    raise RuntimeError(f"Reference not found: {reference_path}")

reference = json.loads(reference_path.read_text(encoding="utf-8"))
if int(reference.get("cohort_id", -1)) != 134:
    raise RuntimeError("Reference validation failed: expected cohort 134.")

# Vocabulary remains read-only.
if not paths.VOCAB_DB.exists():
    raise RuntimeError(f"Vocabulary database missing: {paths.VOCAB_DB}")

vocab_con = None
records = []
started_all = time.perf_counter()

# Pass actual Ollama model IDs to every pipeline agent.
local_model = model_for("A", "small")
models = {
    "planner": local_model,
    "concept": local_model,
    "builder": local_model,
    "critic": local_model,
    "single_agent": local_model,
}

try:
    vocab_con = duckdb.connect(str(paths.VOCAB_DB), read_only=True)
    paths.configure(vocab_con)
    client = make_client("A", fake=False)
    budget = Budget()
    # Retry only configurations that failed due to the model-name mapping.
    configurations = [
        c for c in benchmark_configurations()
        if c.name in {"C3", "C1", "C4"}
    ]

    print("=" * 72)
    print("JBI LOCAL OLLAMA BENCHMARK — AUTOSAVE ENABLED")
    print("Task: T01")
    print("Reference cohort: 134 (evaluator-side only)")
    print("Model small:", model_for("A", "small"))
    print("Model strong:", model_for("A", "strong"))
    print("Configurations:", ", ".join(c.name for c in configurations))
    print("Output directory:", output_dir)
    print("Frozen RUN_QUEUE.csv will not be modified.")
    print("=" * 72)

    for config in configurations:
        print(f"\n===== STARTING {config.name} =====")
        started = time.perf_counter()

        try:
            result = run_experiment(
                tasks=[type("Task", (), task)()],
                configurations=[config],
                client=client,
                vocab_con=vocab_con,
                models=models,
                budget=budget,
                reference_loader=lambda _task_id: reference,
            )

            records.extend(result.records)
            elapsed = round(time.perf_counter() - started, 2)

            # Persist immediately after each configuration.
            save_checkpoint(
                records,
                state="running",
                current_config=config.name,
            )

            for record in result.records:
                print(
                    f"{record.configuration} | "
                    f"status={record.status} | "
                    f"LLM={record.llm_calls} | "
                    f"tools={record.tool_calls} | "
                    f"seconds={record.wall_seconds}"
                )
                if record.reason:
                    print("Reason:", record.reason)

            print(f"{config.name} finished in {elapsed}s.")
            print("Checkpoint saved:", output_dir)

        except BaseException as exc:
            save_checkpoint(
                records,
                state="interrupted",
                current_config=config.name,
                error=f"{type(exc).__name__}: {exc}",
            )
            print(f"ERROR during {config.name}: {exc}")
            print("Previous checkpoints have been preserved.")
            raise

    save_checkpoint(records, state="completed")

    print("\n" + "=" * 72)
    print("ALL CONFIGURATIONS FINISHED")
    print("Successful records:", sum(r.status == "success" for r in records))
    print("Total records:", len(records))
    print("Elapsed seconds:", round(time.perf_counter() - started_all, 2))
    print("Saved results:", output_dir / "results.json")
    print("Saved CSV:", output_dir / "results.csv")
    print("Saved progress:", output_dir / "progress.json")
    print("Saved terminal log:", output_dir / "terminal.log")
    print("=" * 72)

finally:
    if vocab_con is not None:
        vocab_con.close()
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_handle.flush()
    log_handle.close()
