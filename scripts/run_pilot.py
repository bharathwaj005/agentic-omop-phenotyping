"""Run one task with C2 and save an isolated, reviewable pilot bundle."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from src.llm.client import make_client
from src.logging.provenance import RunLog
from src.metrics.evaluation import set_metrics
from src.pipelines.budget import Budget
from src.pipelines.deadline import RunDeadlineExceeded
from src.runner.experiment import _DeadlineClient
from src.pipelines.single_agent import run_single_agent
from src.pipelines.multi_agent import run_multi_agent
from src.runner.experiment import C1, C3, C4
from src.tools.resolver import open_vocab

ROOT = Path(__file__).resolve().parents[1]
V53 = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967, 1048, 1064,
       1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]
TASK_COHORT = {f"T{i:02d}": str(cid) for i, cid in enumerate(V53, 1)}


def _load_task(task_id: str) -> dict:
    for line in (ROOT / "tasks/benchmark_questions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("task_id") == task_id:
                return row
    raise ValueError(f"task not found: {task_id}")


def _safe_out(out: Path, root: Path = ROOT) -> Path:
    target = out.expanduser().resolve()
    approved = (root / "results/codex_20261024").resolve()
    if approved != target and approved not in target.parents:
        raise ValueError("--out must be inside results/codex_20261024/")
    forbidden = (root / "results/benchmark_design/V5_3_FREEZE").resolve()
    recovery = (root / "results/benchmark_runs/V5_3_REAL_RUN/RECOVERY_QWEN3B").resolve()
    if any(p == target or p in target.parents for p in (forbidden, recovery)):
        raise ValueError(f"refusing protected output path: {target}")
    if target.exists():
        raise FileExistsError(f"--out already exists: {target}")
    return target


def _metrics(predicted: set[int] | None, reference: dict, key: str) -> dict | None:
    if predicted is None:
        return None
    return asdict(set_metrics(predicted, set(reference.get(key, []))))


def run_pilot(task_id: str, model: str, out: Path, reference_version: str = "v1",
              *, configuration: str = "C2", client=None, vocab_con=None,
              root: Path = ROOT) -> dict:
    if task_id not in TASK_COHORT:
        raise ValueError(f"pilot supports V5.3 task IDs T01–T20; got {task_id}")
    if reference_version not in {"v1", "v2"}:
        raise ValueError("reference_version must be v1 or v2")
    configs = {"C1": C1, "C2": "C2", "C3": C3, "C4": C4}
    if configuration not in configs:
        raise ValueError("configuration must be C1, C2, C3, or C4")
    out = _safe_out(out, root)
    task = _load_task(task_id) if root == ROOT else json.loads(
        (root / "tasks/benchmark_questions.jsonl").read_text().splitlines()[0])
    cohort = TASK_COHORT[task_id]
    refs = {}
    for version in ("v1", "v2"):
        path = root / f"tasks/reference{'_v2' if version == 'v2' else ''}/{cohort}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        refs[version] = json.loads(path.read_text())
    out.mkdir(parents=True)
    started = time.monotonic()
    deadline_at = None
    deadline_s = os.environ.get("JBI_RUN_DEADLINE_S")
    if deadline_s:
        value = float(deadline_s)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("JBI_RUN_DEADLINE_S must be a positive finite number")
        deadline_at = started + value
    log = RunLog(f"PILOT_{task_id}_{configuration}", configuration, task_id, 1,
                 models={"single_agent": model}, caps=Budget().to_dict())
    log.path = lambda: out / "trace.json"
    own_con = vocab_con is None
    ctx = open_vocab(read_only=True) if own_con else None
    try:
        if own_con:
            vocab_con = ctx.__enter__()
        client = client or make_client("A")
        if deadline_at is not None:
            client = _DeadlineClient(client, deadline_at)
        if configuration == "C2":
            result = run_single_agent(client, model, task["question"], vocab_con,
                                      budget=Budget(), log=log)
        else:
            conf = configs[configuration]
            models = {role: model for role in ("planner", "concept", "builder", "critic")}
            result = run_multi_agent(
                client, models, task["question"], vocab_con, budget=Budget(),
                use_critic=conf.use_critic, use_validator=conf.use_validator, log=log)
    except RunDeadlineExceeded as exc:
        result = None
        status, reason = "timeout", str(exc)
    except Exception as exc:  # noqa: BLE001
        result = None
        status, reason = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        if own_con and ctx is not None:
            ctx.__exit__(None, None, None)

    elapsed = time.monotonic() - started
    if result is not None:
        status, reason = result.status, result.reason
        spec = result.spec.model_dump() if result.spec is not None else None
        resolved = result.resolved
        full = set().union(*resolved.values()) if resolved else set()
        entry_names = (result.spec.entry_concept_sets if result.spec else [])
        entry = set().union(*(resolved.get(n, set()) for n in entry_names)) if entry_names else set()
        predicted_full, predicted_entry = full, entry
        usage = result.tracker.to_dict()
    else:
        spec, resolved, predicted_full, predicted_entry, usage = None, {}, None, None, {}

    if spec is not None:
        per_set = {}
        for name, cs in spec.get("concept_sets", {}).items():
            per_set[name] = {
                "domain": cs.get("domain"),
                "items": cs.get("items", []),
                "include_descendants": [bool(i.get("include_descendants")) for i in cs.get("items", [])],
                "resolved_count": len(resolved.get(name, set())),
            }
        arms = spec.get("entry_arms", [])
    else:
        per_set, arms = {}, []

    report = {
        "task_id": task_id, "cohort_id": cohort, "configuration": configuration,
        "reference_version_selected": reference_version, "model_requested": model,
        "model_names_used": sorted({e.model for e in log.events if e.model}),
        "status": status, "reason": reason,
        "timings": {"wall_seconds": elapsed, **log.totals()},
        "llm_calls": log.totals()["llm_calls"], "tool_calls": log.totals()["tool_calls"],
        "input_tokens": log.totals()["input_tokens"], "output_tokens": log.totals()["output_tokens"],
        "final_spec": spec, "entry_arms": arms, "per_set": per_set,
        "ordered_tool_calls": [
            {"step": e.step, "tool": e.actor, "args": e.detail}
            for e in log.events if e.kind == "tool"],
        "metrics": {
            version: {"full": _metrics(predicted_full, refs[version], "all_concept_ids"),
                      "entry": _metrics(predicted_entry, refs[version], "entry_concept_ids")}
            for version in ("v1", "v2")},
    }
    log.finish(status, final_spec=spec, error=reason, report="report.json")
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "checkpoint.json").write_text(json.dumps({"status": status, "task_id": task_id,
                                                       "configuration": configuration}, indent=2) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--config", required=True, choices=["C1", "C2", "C3", "C4"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reference-version", choices=["v1", "v2"], default="v1")
    args = parser.parse_args(argv)
    try:
        report = run_pilot(args.task, args.model, args.out, args.reference_version,
                           configuration=args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "out": str(args.out.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
