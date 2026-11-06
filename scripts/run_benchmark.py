"""Sequential, checkpointed benchmark runner for the frozen JBI tracks.

This module is an execution entry point. Do not import it to launch runs; use
the CLI after reviewing preflight output and the supplied freeze manifest.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from src import paths
from src.agents.base import prompt_hashes
from src.llm.client import make_client
from src.logging.provenance import RunLog
from src.metrics.evaluation import set_metrics
from src.result_serialization import RESULT_SCHEMA_VERSION, write_result_report
from src.pipelines.budget import Budget
from src.pipelines.deadline import RunDeadlineExceeded
from src.pipelines.multi_agent import run_multi_agent
from src.pipelines.single_agent import run_single_agent
from src.runner.experiment import C1, C3, C4, _DeadlineClient
from src.schema.spec import CohortSpec
from src.tools.resolver import open_vocab

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "results/codex_20261025/runs"
MIN_AVAILABLE_MEMORY_BYTES = 3 * 1024**3
MIN_FREE_DISK_BYTES = 1 * 1024**3
MAX_RUN_DEADLINE_S = 3600
REFERENCE_V2_SHA256 = "4f807ba055ed1a71d5ded423fab5bd27041efdb1cd27ea4f32ccaf6afaf688bb"
FROZEN_HASHES = {
    "results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv": "205e4f69c4d43b89719c4291446d11b760b939b2610999e43c2a11dc4377e0f2",
    "results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FINAL_ENTRY_JACCARD_190_PAIRS.csv": "0dcdd9b3c99eda1c92dde3fec8914a8cf2280416147cfcab9f974fe7cb78c1b1",
    "results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FINAL_REDUNDANCY_AUDIT.txt": "095e4b3fce262f29ab926e3e5a12dc60898dacfd73363b7cf5ed83581db83c67",
    "results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FREEZE_MANIFEST.json": "77a26b5178d0ed36c33f2bb3a8c42791ddc123794c9ca3a4ad2eec1465134f06",
    "tasks/reference/134.json": "a9ded2583ada1e552702595e3a80b132ce5a1d4dbebaf3ceef972492a4248c2c",
    "/media/bharathwaj/HDD_Storage/project_jbi/results/benchmark_runs/V5_3_REAL_RUN/RUN_QUEUE.csv": "ac668c67c85ad69d061476c071f17c55ef24b0b4c913cebd42184687ddea6a66",
}
V53 = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967, 1048, 1064,
       1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]
CONFIGS = {"C1": C1, "C2": "C2", "C3": C3, "C4": C4}
COMPLETE_STATUSES = {"success", "failed", "timeout", "budget_exhausted",
                     "validator_exhausted", "completed"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _endpoint_preflight(base_url: str, model: str, fake: bool = False) -> dict | None:
    if fake:
        return None
    if not base_url:
        raise RuntimeError("A_BASE_URL is missing; configure the model endpoint before running")
    local_ollama = "11434" in base_url
    if local_ollama:
        url = base_url.split("/v1", 1)[0].rstrip("/") + "/api/tags"
    else:
        url = base_url.rstrip("/") + "/models"
    headers = {}
    key = os.environ.get("A_API_KEY", "")
    if key and not local_ollama:
        headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("model endpoint is unreachable; check A_BASE_URL and server status") from exc
    models = payload.get("models", payload.get("data", [])) if isinstance(payload, dict) else []
    named_models = [(item, str(item.get("name", item.get("id", ""))))
                    for item in models if isinstance(item, dict)]
    names = {name for _, name in named_models}
    accepted_names = {model}
    if local_ollama and ":" not in model:
        # Ollama interprets an untagged request as the :latest tag. Do not
        # accept another tag (for example qwen:3b for requested qwen:latest).
        accepted_names.add(f"{model}:latest")
    if not names.intersection(accepted_names):
        raise RuntimeError("requested model is not present on the configured endpoint")
    matched = next(item for item, name in named_models if name in accepted_names)
    return {
        "endpoint_kind": "local_ollama" if local_ollama else "remote_openai_compatible",
        "requested_model": model,
        "resolved_tag": matched.get("name", matched.get("id")),
        "digest": matched.get("digest"),
        "modified_at": matched.get("modified_at"),
        "size_bytes": matched.get("size"),
    }


def _verify_frozen() -> None:
    errors = []
    for raw, expected in FROZEN_HASHES.items():
        path = Path(raw) if raw.startswith("/") else ROOT / raw
        if not path.is_file() or sha256(path) != expected:
            errors.append(raw)
    if errors:
        raise RuntimeError("frozen-file checksum preflight failed: " + ", ".join(errors))
    ref_manifest = ROOT / "tasks/reference_v2/MANIFEST.json"
    if not ref_manifest.is_file() or sha256(ref_manifest) != REFERENCE_V2_SHA256:
        raise RuntimeError("tasks/reference_v2/MANIFEST.json checksum changed")


def _load_questions(path: Path, track: str, task_filter: set[str] | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    expected = "T" if track == "v53" else "N"
    rows = [r for r in rows if str(r.get("task_id", "")).startswith(expected)]
    if len({str(r.get("task_id")) for r in rows}) != len(rows):
        raise ValueError("question file contains duplicate task_id values")
    if task_filter is not None:
        requested = {str(task_id) for task_id in task_filter}
        available = {str(row.get("task_id")) for row in rows}
        missing = sorted(requested - available)
        if missing:
            raise ValueError(f"requested task IDs are not in the {track} question file: {missing}")
        rows = [r for r in rows if str(r["task_id"]) in requested]
    if not rows:
        raise ValueError(f"no {track} questions selected")
    for row in rows:
        if not row.get("task_id") or not row.get("question"):
            raise ValueError("each question row needs task_id and question")
    return rows


def _cohort_map(track: str) -> dict[str, str]:
    if track == "v53":
        return {f"T{i:02d}": str(cid) for i, cid in enumerate(V53, 1)}
    path = ROOT / "results/benchmark_design/NEURO_FREEZE/task_list.csv"
    if not path.is_file():
        raise FileNotFoundError("Neuro freeze task_list.csv is missing")
    with path.open(newline="") as stream:
        return {r["task_id"]: r["cohort_id"] for r in csv.DictReader(stream)}


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with tmp.open(encoding="utf-8") as stream:
            parsed = json.load(stream)
        if not isinstance(parsed, dict):
            raise ValueError("checkpoint JSON must be an object")
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _write_queue(path: Path, rows: list[dict]) -> None:
    fields = ["task_id", "configuration", "status", "attempts", "reason",
              "retry_log", "wall_seconds", "started_at", "finished_at", "report_path"]
    fields += ["report_sha256", "trace_sha256"]
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "retry_log": json.dumps(row.get("retry_log", []))})
    tmp.replace(path)


def _write_run_manifest(out: Path, *, track: str, questions: Path,
                        model: str, configs: list[str], queue_path: Path,
                        freeze_manifest: Path | None, model_identity: dict | None,
                        question_rows: list[dict], cohort_map: dict[str, str],
                        vocabulary_source: dict | None) -> None:
    """Write explicit, versioned input/queue provenance for a new run."""
    design_path = (ROOT / "results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv"
                   if track == "v53" else None)
    ollama_num_ctx = int(os.environ.get("A_OLLAMA_NUM_CTX", "8192"))
    config_payload = json.dumps({"track": track, "model_requested": model,
                                 "configurations": configs,
                                 "ollama_num_ctx": ollama_num_ctx}, sort_keys=True)
    reference_inputs = []
    v1_folder = "reference" if track == "v53" else "reference_neuro"
    for task in question_rows:
        task_id = str(task["task_id"])
        cohort = cohort_map[task_id]
        for version, folder in (("v1", v1_folder), ("v2", "reference_v2")):
            path = ROOT / "tasks" / folder / f"{cohort}.json"
            reference_inputs.append({"task_id": task_id, "cohort_id": cohort,
                                     "version": version, "path": str(path.resolve()),
                                     "sha256": sha256(path)})
    manifest = {
        "schema_version": 1,
        "experiment_id": out.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "track": track,
        "model_requested": model,
        "ollama_num_ctx": ollama_num_ctx,
        "model_identity": model_identity,
        "vocabulary_source": vocabulary_source,
        "configurations": configs,
        "design_freeze_input": {
            "path": str(design_path.resolve()) if design_path else None,
            "sha256": sha256(design_path) if design_path and design_path.is_file() else None,
        },
        "runtime_queue_initial": {
            "path": str(queue_path.resolve()), "sha256": sha256(queue_path),
        },
        "task_file": {"path": str(questions.resolve()), "sha256": sha256(questions)},
        "reference_inputs": reference_inputs,
        "configuration_sha256": hashlib.sha256(config_payload.encode("utf-8")).hexdigest(),
        "freeze_manifest": ({"path": str(freeze_manifest.resolve()),
                              "sha256": sha256(freeze_manifest)}
                             if freeze_manifest is not None else None),
        "semantics": {
            "design_freeze_input": "design CSV hash; never interpreted as runtime queue hash",
            "runtime_queue_initial": "exact initial runtime queue bytes; queue changes as statuses are checkpointed",
        },
    }
    _atomic_json(out / "run_manifest.v1.json", manifest)


def _classify_infrastructure(reason: str) -> bool:
    text = reason.lower()
    return ("connection refused" in text or "connection reset" in text
            or "unreachable" in text or "name or service not known" in text
            or "temporary failure in name resolution" in text
            or any(f"http {code}" in text for code in range(500, 600))
            or "process killed" in text)


def _reference(track: str, cohort: str, version: str) -> dict:
    if version == "v2":
        folder = "reference_v2"
    else:
        folder = "reference" if track == "v53" else "reference_neuro"
    path = ROOT / "tasks" / folder / f"{cohort}.json"
    if not path.is_file():
        raise FileNotFoundError(f"reference file missing: {path.relative_to(ROOT)}")
    return json.loads(path.read_text())


def _run_one(task: dict, config: str, cohort: str, track: str, model: str,
             run_dir: Path, client, vocab_con, budget: Budget) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    attempt_number = 2 if run_dir.name.endswith("_retry1") else 1
    experiment_id = run_dir.parent.name
    attempt_id = (f"{experiment_id}_{track}_{task['task_id']}_{config}"
                  f"_attempt{attempt_number}")
    prompt_names = (["single_agent"] if config == "C2" else
                    ["planner", "concept", "builder"] +
                    (["critic"] if CONFIGS[config].use_critic else []))
    hashes = prompt_hashes(prompt_names)
    log = RunLog(attempt_id, config, task["task_id"], attempt_number,
                 models={"model": model}, prompt_hashes=hashes,
                 caps=budget.to_dict())
    log.path = lambda: run_dir / "trace.json"
    start = time.monotonic()
    deadline_s = os.environ.get("JBI_RUN_DEADLINE_S")
    deadline_at = None
    if deadline_s:
        seconds = float(deadline_s)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("JBI_RUN_DEADLINE_S must be a positive finite number")
        deadline_at = start + seconds
        client = _DeadlineClient(client, deadline_at)
    result = None
    status, reason = "failed", None
    try:
        if config == "C2":
            result = run_single_agent(client, model, task["question"], vocab_con,
                                      budget=budget, log=log)
        else:
            cfg = CONFIGS[config]
            models = {role: model for role in ("planner", "concept", "builder", "critic")}
            result = run_multi_agent(client, models, task["question"], vocab_con,
                                     budget=budget, use_critic=cfg.use_critic,
                                     use_validator=cfg.use_validator, log=log)
        if deadline_at is not None and time.monotonic() >= deadline_at:
            raise RunDeadlineExceeded("JBI_RUN_DEADLINE_S exceeded")
        status, reason = result.status, result.reason
    except RunDeadlineExceeded as exc:
        status, reason = "timeout", str(exc)
    except KeyboardInterrupt:
        status, reason = "interrupted", "Ctrl+C received"
    except Exception as exc:  # noqa: BLE001
        status, reason = "failed", f"{type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - start
    spec_obj = getattr(result, "spec", None)
    if status == "success":
        if spec_obj is None:
            status = "failed"
            reason = "pipeline reported success without a specification"
        else:
            try:
                spec_obj = CohortSpec.model_validate(spec_obj.model_dump())
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                reason = f"successful pipeline returned an invalid specification: {exc}"
                spec_obj = None
    spec = spec_obj.model_dump() if spec_obj is not None else None
    resolved = getattr(result, "resolved", {}) or {}
    full = set().union(*resolved.values()) if resolved else set()
    entry_names = getattr(spec_obj, "entry_concept_sets", []) if spec_obj is not None else []
    entry = set().union(*(resolved.get(name, set()) for name in entry_names)) if entry_names else set()
    refs = {v: _reference(track, cohort, v) for v in ("v1", "v2")}
    per_set = {}
    if spec:
        for name, cs in spec.get("concept_sets", {}).items():
            per_set[name] = {"domain": cs.get("domain"), "items": cs.get("items", []),
                             "include_descendants": [bool(i.get("include_descendants")) for i in cs.get("items", [])],
                             "resolved_count": len(resolved.get(name, set()))}
    totals = log.totals()
    report = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "logical_run_id": f"{track}_{task['task_id']}_{config}",
        "track": track, "task_id": task["task_id"], "cohort_id": cohort,
        "configuration": config, "attempt_number": attempt_number,
        "attempt_id": attempt_id, "model_requested": model,
        "question_text_sha256": hashlib.sha256(
            task["question"].encode("utf-8")
        ).hexdigest(),
        "ollama_num_ctx": (int(os.environ.get("A_OLLAMA_NUM_CTX", "8192"))
                            if "127.0.0.1:11434" in os.environ.get("A_BASE_URL", "")
                            or "localhost:11434" in os.environ.get("A_BASE_URL", "")
                            else None),
        "trace_path": str((run_dir / "trace.json").resolve()),
        "raw_replies_path": str((run_dir / "raw_replies.json").resolve()),
        "model_names_used": sorted({e.model for e in log.events if e.model}),
        "prompt_hashes": hashes,
        "status": status, "reason": reason,
        "timings": {"wall_seconds": elapsed, **totals}, "wall_seconds": elapsed,
        "llm_calls": totals["llm_calls"], "tool_calls": totals["tool_calls"],
        "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
        "final_spec": spec, "entry_arms": (spec or {}).get("entry_arms", []),
        "per_set": per_set,
        "ordered_tool_calls": [{"step": e.step, "tool": e.actor, "args": e.detail}
                               for e in log.events if e.kind == "tool"],
        "metrics": {v: {"full": ({k: getattr(set_metrics(full, set(refs[v].get("all_concept_ids", []))), k)
                                          for k in ("precision", "recall", "f1", "jaccard")} if spec is not None else None),
                        "entry": ({k: getattr(set_metrics(entry, set(refs[v].get("entry_concept_ids", []))), k)
                                           for k in ("precision", "recall", "f1", "jaccard")} if spec is not None else None)}
                   for v in ("v1", "v2")},
    }
    log.finish(status, final_spec=spec, error=reason)
    trace = json.loads((run_dir / "trace.json").read_text())
    raw_replies = [{"step": e["step"], "actor": e["actor"], "model": e.get("model"),
                    "text": (e.get("detail") or {}).get("raw_text")}
                   for e in trace.get("events", [])
                   if (e.get("detail") or {}).get("raw_text") is not None]
    (run_dir / "raw_replies.json").write_text(json.dumps(raw_replies, indent=2) + "\n")
    write_result_report(run_dir / "report.json", report)
    return report


def _preflight(args, out: Path, freeze_arg: Path | None) -> tuple[Path, dict | None]:
    raw_deadline = os.environ.get("JBI_RUN_DEADLINE_S")
    if not raw_deadline:
        raise RuntimeError("JBI_RUN_DEADLINE_S must be set for bounded execution")
    try:
        seconds = float(raw_deadline)
    except ValueError as exc:
        raise RuntimeError("JBI_RUN_DEADLINE_S must be a positive finite number") from exc
    if (not math.isfinite(seconds) or seconds <= 0
            or seconds > MAX_RUN_DEADLINE_S):
        raise RuntimeError("JBI_RUN_DEADLINE_S must be positive and no more than 3600 seconds")
    fake = os.environ.get("USE_FAKE_LLM") == "1"
    if fake:
        raise RuntimeError(
            "refusing live benchmark preflight while USE_FAKE_LLM=1"
        )
    model_identity = _endpoint_preflight(os.environ.get("A_BASE_URL", ""), args.model)
    _verify_frozen()
    _cohort_map(args.track)
    manifest = freeze_arg if freeze_arg is not None else (out / "freeze_manifest.json")
    if not manifest.is_file():
        raise RuntimeError("freeze manifest missing; pass --freeze-manifest <file>")
    _check_resource_limits(psutil.virtual_memory().available,
                           shutil.disk_usage(
                               out.parent if out.parent.exists() else ROOT
                           ).free)
    return manifest.resolve(), model_identity


def _check_resource_limits(available_memory_bytes: int,
                           free_disk_bytes: int) -> None:
    if available_memory_bytes < MIN_AVAILABLE_MEMORY_BYTES:
        raise RuntimeError(
            "preflight requires at least 3 GiB available memory for the local model"
        )
    if free_disk_bytes <= MIN_FREE_DISK_BYTES:
        raise RuntimeError("preflight requires more than 1 GiB free disk space")


def run_benchmark(track: str, questions: Path, model: str, out: Path,
                  configs: list[str] | None = None, tasks: set[str] | None = None,
                  resume: bool = False, freeze_manifest: Path | None = None,
                  *, client=None, vocab_con=None, preflight=True) -> int:
    out = out.expanduser().resolve()
    allowed = RUNS_ROOT.resolve()
    if out != allowed and allowed not in out.parents:
        raise ValueError("--out must be inside results/codex_20261025/runs/")
    if resume:
        if not out.is_dir():
            raise FileNotFoundError("--resume requires an existing run directory")
    elif out.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {out}")
    if configs is None:
        configs = ["C1", "C2", "C3", "C4"]
    if not configs or any(c not in CONFIGS for c in configs):
        raise ValueError("configs must be selected from C1,C2,C3,C4")
    question_rows = _load_questions(questions, track, tasks)
    question_sha = sha256(questions)
    cohort_map = _cohort_map(track)
    if any(row["task_id"] not in cohort_map for row in question_rows):
        raise ValueError("selected questions include task IDs missing from the track map")
    for row in question_rows:
        cohort = cohort_map[row["task_id"]]
        _reference(track, cohort, "v1")
        _reference(track, cohort, "v2")
    if preflight:
        manifest_path, model_identity = _preflight(
            argparse.Namespace(track=track, model=model), out, freeze_manifest)
    else:
        manifest_path = freeze_manifest
        model_identity = None
    queue_path, checkpoint_path = out / "RUN_QUEUE.csv", out / "checkpoint.json"
    if resume:
        if not checkpoint_path.is_file() or not queue_path.is_file():
            raise FileNotFoundError("resume requires checkpoint.json and RUN_QUEUE.csv")
        checkpoint = json.loads(checkpoint_path.read_text())
        if (checkpoint.get("track") != track or checkpoint.get("model") != model
                or checkpoint.get("configs") != configs
                or checkpoint.get("question_sha256") != question_sha
                or checkpoint.get("task_ids") != [r["task_id"] for r in question_rows]):
            raise ValueError("resume arguments do not match the saved checkpoint")
        rows = checkpoint["runs"]
        if manifest_path is not None and sha256(manifest_path) != checkpoint.get("freeze_manifest_sha256"):
            raise ValueError("freeze manifest differs from the checkpoint")
    else:
        out.mkdir(parents=True)
        if manifest_path is not None and manifest_path != out / "freeze_manifest.json":
            shutil.copyfile(manifest_path, out / "freeze_manifest.json")
            manifest_path = out / "freeze_manifest.json"
        rows = []
        for task in question_rows:
            for config in configs:
                run_dir = out / f"{task['task_id']}_{config}"
                rows.append({"task_id": task["task_id"], "configuration": config,
                             "status": "pending", "attempts": 0, "reason": "",
                             "retry_log": [], "wall_seconds": "", "started_at": "",
                             "finished_at": "",
                             "report_path": str((run_dir / "report.json").relative_to(ROOT))})
        checkpoint = {"track": track, "model": model, "configs": configs,
                      "question_sha256": question_sha,
                      "task_ids": [r["task_id"] for r in question_rows],
                      "freeze_manifest_sha256": sha256(manifest_path) if manifest_path else None,
                      "runs": rows}
        _atomic_json(checkpoint_path, checkpoint)
        _write_queue(queue_path, rows)
        _write_run_manifest(out, track=track, questions=questions, model=model,
                            configs=configs, queue_path=queue_path,
                            freeze_manifest=manifest_path,
                            model_identity=model_identity,
                            question_rows=question_rows, cohort_map=cohort_map,
                            vocabulary_source=(
                                {"path": str(paths.VOCAB_DB.resolve()),
                                 "sha256": sha256(paths.VOCAB_DB)}
                                if preflight and paths.VOCAB_DB.is_file() else None))

    client = client or make_client("A")
    own_con = vocab_con is None
    ctx = open_vocab(read_only=True) if own_con else None
    try:
        if own_con:
            vocab_con = ctx.__enter__()
        task_by_id = {r["task_id"]: r for r in question_rows}
        for row in rows:
            status = row.get("status")
            if status in COMPLETE_STATUSES:
                continue
            if status in {"running", "interrupted"}:
                if row.get("attempts", 0) >= 2:
                    row["status"] = "interrupted"
                    row["reason"] = "resume found an interrupted run after its retry allowance"
                    _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
                    _write_queue(queue_path, rows)
                    continue
                retry_reason = "process killed or interrupted before checkpointed completion"
                row.setdefault("retry_log", []).append(retry_reason)
            retrying = status in {"running", "interrupted", "retry_pending"}
            row["status"] = "running"
            row["attempts"] = int(row.get("attempts", 0)) + 1
            row["started_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
            _write_queue(queue_path, rows)
            task = task_by_id[row["task_id"]]
            run_suffix = "_retry1" if retrying else ""
            run_dir = out / f"{row['task_id']}_{row['configuration']}{run_suffix}"
            try:
                report = _run_one(task, row["configuration"], cohort_map[row["task_id"]],
                                  track, model, run_dir, client, vocab_con, Budget())
            except Exception as exc:  # noqa: BLE001
                report = {"task_id": row["task_id"], "configuration": row["configuration"],
                          "status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                          "wall_seconds": None}
            row.update({"status": report["status"], "reason": report.get("reason") or "",
                        "wall_seconds": report.get("wall_seconds") or "",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "report_sha256": (sha256(ROOT / row["report_path"])
                                          if (ROOT / row["report_path"]).is_file() else None),
                        "trace_sha256": (sha256((ROOT / row["report_path"]).parent / "trace.json")
                                         if ((ROOT / row["report_path"]).parent / "trace.json").is_file()
                                         else None)})
            _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
            _write_queue(queue_path, rows)

            if row["status"] == "interrupted":
                _write_queue(queue_path, rows)
                if own_con and ctx is not None:
                    ctx.__exit__(None, None, None)
                    ctx = None
                return 130

            if (row["status"] == "failed" and row["attempts"] == 1
                    and _classify_infrastructure(str(row["reason"]))):
                retry_reason = f"infrastructure retry: {row['reason']}"
                row.setdefault("retry_log", []).append(retry_reason)
                row["status"] = "retry_pending"
                _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
                _write_queue(queue_path, rows)
                row["status"] = "running"
                row["attempts"] = 2
                row["started_at"] = datetime.now(timezone.utc).isoformat()
                _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
                _write_queue(queue_path, rows)
                second_dir = out / f"{row['task_id']}_{row['configuration']}_retry1"
                try:
                    retry_report = _run_one(task, row["configuration"], cohort_map[row["task_id"]],
                                            track, model, second_dir, client, vocab_con, Budget())
                except Exception as exc:  # noqa: BLE001
                    retry_report = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                                    "wall_seconds": None}
                row.update({"status": retry_report["status"],
                            "reason": retry_report.get("reason") or "",
                            "wall_seconds": retry_report.get("wall_seconds") or "",
                            "finished_at": datetime.now(timezone.utc).isoformat()})
                row["report_path"] = str((second_dir / "report.json").relative_to(ROOT))
                row["report_sha256"] = (sha256(ROOT / row["report_path"])
                                        if (ROOT / row["report_path"]).is_file() else None)
                retry_trace = ROOT / row["report_path"].replace("report.json", "trace.json")
                row["trace_sha256"] = sha256(retry_trace) if retry_trace.is_file() else None
                _atomic_json(checkpoint_path, {**checkpoint, "runs": rows})
                _write_queue(queue_path, rows)
        return 0
    finally:
        if own_con and ctx is not None:
            ctx.__exit__(None, None, None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", required=True, choices=["v53", "neuro"])
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--configs", default="C1,C2,C3,C4")
    parser.add_argument("--tasks", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--freeze-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        return run_benchmark(
            args.track, args.questions, args.model, args.out,
            [c.strip() for c in args.configs.split(",") if c.strip()],
            set(args.tasks.split(",")) if args.tasks else None,
            args.resume, args.freeze_manifest)
    except KeyboardInterrupt:
        print("Interrupted; checkpoint is saved. Re-run with --resume.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Preflight/run stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
