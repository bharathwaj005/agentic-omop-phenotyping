"""End-to-end smoke test: one blinded task through every configuration.

Verifies the complete path

    blinded task -> pipeline -> CohortSpec -> provenance record

for C0-plus, C2, C3, C4 and C1, using the FakeClient. No API tokens are spent
and the benchmark is not touched. Run this before any real run, and again after
any change to the pipelines.

Usage:
    python -m scripts.smoke_run
    python -m scripts.smoke_run --task T01       # a specific blinded task
    python -m scripts.smoke_run --keep           # leave the run logs on disk
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import Optional

from src import paths
from src.llm.fake_client import FakeClient
from src.logging.provenance import RunLog
from src.pipelines.budget import Budget
from src.pipelines.lexical import run_lexical
from src.pipelines.multi_agent import run_multi_agent
from src.pipelines.single_agent import run_single_agent
from src.tools import vocab

SMOKE_CONFIG = "SMOKE"

# The ONLY keys a pipeline may see. Anything else -- cohort_id, complexity,
# execution_class, expected_* -- is audit material and must never reach a
# prompt. Enforced here rather than trusted to discipline.
ALLOWED_TASK_KEYS = {"task_id", "question", "entry_domain_hint", "target_term"}

FALLBACK_TASK = {
    "task_id": "SMOKE01",
    "question": ("Identify adults with a first recorded diagnosis of peptic "
                 "ulcer who have at least one year of prior observation."),
    "entry_domain_hint": "Condition",
    "target_term": "peptic ulcer",
}

MODELS = {"planner": "fake-strong", "concept": "fake-small",
          "builder": "fake-small", "critic": "fake-strong"}


class BlindingError(RuntimeError):
    pass


def assert_blinded(task: dict) -> None:
    """Refuse to run on a task carrying anything a pipeline must not see."""
    extra = set(task) - ALLOWED_TASK_KEYS
    if extra:
        raise BlindingError(
            f"task {task.get('task_id')} carries non-blinded keys: "
            f"{sorted(extra)}. Audit fields belong in the audit sheet, not in "
            "the benchmark questions file.")
    if not str(task.get("question", "")).strip():
        raise BlindingError("task has no question")


def load_task(task_id: Optional[str]) -> dict:
    """Load one blinded task, falling back to a built-in example."""
    # V5.3 smoke tests must use the repository-local blinded task package.
    # The global TASKS_DIR intentionally points to the HDD bulk-storage tree.
    path = paths.PROJECT_ROOT / "tasks" / "benchmark_questions.jsonl"
    if not path.exists():
        print(f"note: {path} not found, using the built-in example task\n")
        return dict(FALLBACK_TASK)

    tasks = [json.loads(line) for line in path.read_text().splitlines()
             if line.strip()]
    if not tasks:
        raise RuntimeError(f"{path} is empty")
    if task_id:
        for t in tasks:
            if t.get("task_id") == task_id:
                return t
        raise RuntimeError(f"task {task_id} not found in {path}")
    return tasks[0]


def summarise(name: str, status: str, reason, spec, resolved, usage) -> dict:
    entry = None
    if spec is not None:
        entry = len(resolved.get(spec.entry_concept_set, set()))
    return {"config": name, "status": status,
            "entry_concepts": entry,
            "llm_calls": usage.get("llm_calls", 0),
            "tool_calls": usage.get("tool_calls", 0),
            "tokens": usage.get("tokens", 0),
            "reason": (reason or "")[:60]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None)
    ap.add_argument("--keep", action="store_true",
                    help="keep the smoke run logs instead of deleting them")
    args = ap.parse_args()

    paths.ensure_dirs()
    task = load_task(args.task)

    try:
        assert_blinded(task)
    except BlindingError as e:
        print(f"BLINDING CHECK FAILED\n  {e}")
        return 1

    print(f"task     : {task['task_id']}")
    print(f"question : {task['question']}\n")

    rows = []
    with vocab.open_source() as (vocab_con, label):
        print(f"vocabulary source: {label}\n")

        # --- C0-plus: deterministic, no LLM --------------------------------
        r = run_lexical(task["question"], vocab_con,
                        domain_hint=task.get("entry_domain_hint"))
        rows.append(summarise("C0-plus", r.status, r.reason, r.spec,
                              r.resolved, {}))
        if r.unresolved:
            print(f"C0-plus unresolved terms: {r.unresolved}")

        # --- LLM configurations --------------------------------------------
        budget = Budget()

        def record(name: str, fn):
            log = RunLog(run_id=f"{name}_{task['task_id']}_rep1",
                         config=SMOKE_CONFIG, task_id=f"{name}_{task['task_id']}",
                         repeat=1, models=MODELS, caps=budget.to_dict())
            try:
                res = fn(log)
                spec = res.spec
                log.finish("success" if res.status == "success" else "failed",
                           final_spec=spec.model_dump() if spec else None,
                           error=res.reason)
                rows.append(summarise(name, res.status, res.reason, spec,
                                      res.resolved, res.tracker.to_dict()))
            except Exception as e:                       # noqa: BLE001
                log.finish("failed", error=f"{type(e).__name__}: {e}")
                rows.append({"config": name, "status": "crashed",
                             "entry_concepts": None, "llm_calls": 0,
                             "tool_calls": 0, "tokens": 0,
                             "reason": f"{type(e).__name__}: {e}"[:60]})

        record("C2", lambda log: run_single_agent(
            FakeClient(), "fake-strong", task["question"], vocab_con,
            budget=budget, log=log))

        record("C3", lambda log: run_multi_agent(
            FakeClient(), MODELS, task["question"], vocab_con,
            budget=budget, use_critic=False, use_validator=True, log=log))

        record("C4", lambda log: run_multi_agent(
            FakeClient(), MODELS, task["question"], vocab_con,
            budget=budget, use_critic=True, use_validator=False, log=log))

        record("C1", lambda log: run_multi_agent(
            FakeClient(), MODELS, task["question"], vocab_con,
            budget=budget, use_critic=True, use_validator=True, log=log))

    # --- report ------------------------------------------------------------
    print()
    header = f"{'config':<9}{'status':<10}{'entry':>6}{'llm':>5}{'tool':>6}" \
             f"{'tokens':>8}  reason"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['config']:<9}{r['status']:<10}"
              f"{str(r['entry_concepts']):>6}{r['llm_calls']:>5}"
              f"{r['tool_calls']:>6}{r['tokens']:>8}  {r['reason']}")

    run_dir = paths.RUNS_DIR / SMOKE_CONFIG
    logs = sorted(run_dir.rglob("rep1.json")) if run_dir.exists() else []
    print(f"\nprovenance records written: {len(logs)}")
    if logs:
        sample = json.loads(logs[0].read_text())
        print(f"sample record: {logs[0].name} "
              f"events={len(sample['events'])} "
              f"auditability={sample['auditability']}")

    ok = all(r["status"] in ("success",) for r in rows)
    if not args.keep and run_dir.exists():
        shutil.rmtree(run_dir)
        print("smoke run logs removed (use --keep to retain them)")

    print("\nSMOKE TEST PASSED" if ok else
          "\nSMOKE TEST: some configurations did not succeed (see table)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
