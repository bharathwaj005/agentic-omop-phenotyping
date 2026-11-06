"""Provenance logging.

Every run writes one JSON file recording each agent step, tool call, token count
and timing. This file is two things at once:

  1. the AUDIT TRAIL -- a human can trace every concept back to the agent,
     prompt and tool result that produced it (a contribution of the paper);
  2. the RAW DATA for every efficiency metric reported in the Results.

Nothing else measures tokens, cost or time. If it is not logged here, it cannot
be reported.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from src import paths

try:
    import psutil
except ImportError:                                      # pragma: no cover
    psutil = None


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=paths.PROJECT_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:                                    # noqa: BLE001
        return "unknown"


@dataclass
class Event:
    step: int
    kind: str                     # "llm" | "tool" | "note"
    actor: str                    # agent name or tool name
    started_at: float
    latency_s: float = 0.0
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


class RunLog:
    """Collects the full trace of one run and writes it to disk.

    Usage:
        log = RunLog(run_id="C1_T01_rep1", config="C1", task_id="T01", repeat=1)
        with log.step("llm", "planner", model="...") as ev:
            ...
            ev.input_tokens, ev.output_tokens = 812, 430
            ev.detail["output"] = spec.model_dump()
        log.finish(status="success", final_spec=spec.model_dump())
    """

    def __init__(self, run_id: str, config: str, task_id: str, repeat: int,
                 models: Optional[dict[str, str]] = None,
                 prompt_hashes: Optional[dict[str, str]] = None,
                 caps: Optional[dict[str, Any]] = None):
        self.run_id = run_id
        self.config = config
        self.task_id = task_id
        self.repeat = repeat
        self.models = models or {}
        self.prompt_hashes = prompt_hashes or {}
        self.caps = caps or {}

        self.events: list[Event] = []
        self._step = 0
        self._t0 = time.time()
        self.status = "running"
        self.error: Optional[str] = None
        self.final_spec: Optional[dict] = None
        self.extra: dict[str, Any] = {}

        self.environment = {
            "git_sha": _git_sha(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "spec_version": None,       # filled by finish() from final_spec
        }

    # --- recording ---------------------------------------------------------

    class _StepCtx:
        def __init__(self, log: "RunLog", ev: Event):
            self.log, self.ev = log, ev

        def __enter__(self) -> Event:
            return self.ev

        def __exit__(self, exc_type, exc, tb) -> bool:
            self.ev.latency_s = round(time.time() - self.ev.started_at, 3)
            if exc is not None:
                self.ev.detail["error"] = f"{exc_type.__name__}: {exc}"
            self.log.events.append(self.ev)
            return False          # never swallow exceptions

    def step(self, kind: str, actor: str, **detail) -> "_StepCtx":
        self._step += 1
        model = detail.pop("model", None)
        ev = Event(step=self._step, kind=kind, actor=actor,
                   started_at=time.time(), model=model, detail=detail)
        return RunLog._StepCtx(self, ev)

    def note(self, actor: str, **detail) -> None:
        """Record something without timing it (a cap hit, a decision)."""
        self._step += 1
        self.events.append(Event(step=self._step, kind="note", actor=actor,
                                 started_at=time.time(), detail=detail))

    # --- totals ------------------------------------------------------------

    def totals(self) -> dict[str, Any]:
        llm = [e for e in self.events if e.kind == "llm"]
        tools = [e for e in self.events if e.kind == "tool"]
        peak_ram = None
        if psutil is not None:
            try:
                peak_ram = round(
                    psutil.Process(os.getpid()).memory_info().rss / 1e6, 1)
            except Exception:                            # noqa: BLE001
                pass
        return {
            "llm_calls": len(llm),
            "tool_calls": len(tools),
            "input_tokens": sum(e.input_tokens for e in llm),
            "output_tokens": sum(e.output_tokens for e in llm),
            "total_tokens": sum(e.input_tokens + e.output_tokens for e in llm),
            "wall_time_s": round(time.time() - self._t0, 2),
            "llm_time_s": round(sum(e.latency_s for e in llm), 2),
            "peak_ram_mb": peak_ram,
            "critic_rounds": sum(1 for e in self.events if e.actor == "critic"),
            "validator_retries": sum(
                1 for e in self.events
                if e.actor == "validator" and e.detail.get("passed") is False),
        }

    def auditability(self) -> float:
        """Share of final concept items that carry a rationale."""
        if not self.final_spec:
            return 0.0
        items = [i for cs in self.final_spec.get("concept_sets", {}).values()
                 for i in cs.get("items", [])]
        if not items:
            return 0.0
        with_reason = sum(1 for i in items if (i.get("rationale") or "").strip())
        return round(with_reason / len(items), 4)

    # --- output ------------------------------------------------------------

    def finish(self, status: str, final_spec: Optional[dict] = None,
               error: Optional[str] = None, **extra) -> Path:
        self.status = status
        self.final_spec = final_spec
        self.error = error
        self.extra.update(extra)
        if final_spec:
            self.environment["spec_version"] = final_spec.get("spec_version")
        return self.save()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config": self.config,
            "task_id": self.task_id,
            "repeat": self.repeat,
            "status": self.status,
            "error": self.error,
            "models": self.models,
            "prompt_hashes": self.prompt_hashes,
            "caps": self.caps,
            "environment": self.environment,
            "final_spec": self.final_spec,
            "totals": self.totals(),
            "auditability": self.auditability(),
            "events": [asdict(e) for e in self.events],
            **self.extra,
        }

    def path(self) -> Path:
        d = paths.RUNS_DIR / self.config / self.task_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"rep{self.repeat}.json"

    def save(self) -> Path:
        p = self.path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1, default=str))
        tmp.replace(p)            # atomic: a killed run never leaves half a file
        return p

    @staticmethod
    def exists(config: str, task_id: str, repeat: int) -> bool:
        """Used by the runner to skip completed runs (resumability)."""
        return (paths.RUNS_DIR / config / task_id / f"rep{repeat}.json").exists()


if __name__ == "__main__":
    log = RunLog(run_id="DEMO_T00_rep1", config="DEMO", task_id="T00", repeat=1,
                 models={"planner": "fake-strong"})
    with log.step("llm", "planner", model="fake-strong") as ev:
        time.sleep(0.05)
        ev.input_tokens, ev.output_tokens = 800, 400
        ev.detail["output"] = {"entry_concept_set": "demo"}
    with log.step("tool", "search_concepts", query="peptic ulcer") as ev:
        ev.detail["rows"] = 12
    log.note("validator", passed=True)
    p = log.finish("success", final_spec={
        "spec_version": "1.0",
        "concept_sets": {"demo": {"items": [{"rationale": "because"}]}},
    })
    print("wrote", p)
    print(json.dumps(log.totals(), indent=1))
