"""Experiment runner for the JBI benchmark.

C9 is the experiment harness. It calls the real C1/C2/C3/C4 pipelines rather
than maintaining a second orchestration implementation.

Reference data is evaluator-side only. The agent receives only the blinded
natural-language question.
"""

from __future__ import annotations
from src.llm.client import model_for

import time
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from src.metrics.evaluation import RunRecord, adjudication_record
from src.pipelines.budget import Budget
from src.pipelines.deadline import RunDeadlineExceeded
from src.pipelines.multi_agent import run_multi_agent
from src.pipelines.single_agent import run_single_agent


@dataclass
class ExperimentResult:
    records: list[RunRecord] = field(default_factory=list)

    @property
    def n_runs(self) -> int:
        return len(self.records)

    @property
    def n_success(self) -> int:
        return sum(r.status == "success" for r in self.records)


@dataclass(frozen=True)
class ExperimentConfig:
    name: str

    # These flags map directly onto the real multi-agent implementation.
    use_critic: bool = False
    use_validator: bool = True

    # C2 is the separate single-agent baseline.
    pipeline: str = "multi"


C2 = ExperimentConfig(
    name="C2",
    use_critic=False,
    use_validator=True,
    pipeline="single",
)

C3 = ExperimentConfig(
    name="C3",
    use_critic=False,
    use_validator=True,
    pipeline="multi",
)

C1 = ExperimentConfig(
    name="C1",
    use_critic=True,
    use_validator=True,
    pipeline="multi",
)

C4 = ExperimentConfig(
    name="C4",
    use_critic=True,
    use_validator=False,
    pipeline="multi",
)


class _DeadlineClient:
    def __init__(self, client: Any, deadline_at: float):
        self._client = client
        self._deadline_at = deadline_at
        # The repository HTTPClient uses this to bound an in-flight request
        # and retry backoff to the current run's deadline.
        try:
            client.run_deadline_at = deadline_at
        except (AttributeError, TypeError):
            pass

    def complete(self, **kwargs):
        if time.monotonic() >= self._deadline_at:
            raise RunDeadlineExceeded("JBI_RUN_DEADLINE_S exceeded")
        result = self._client.complete(**kwargs)
        if time.monotonic() >= self._deadline_at:
            raise RunDeadlineExceeded("JBI_RUN_DEADLINE_S exceeded")
        return result


def benchmark_configurations() -> list[ExperimentConfig]:
    return [C2, C3, C1, C4]


def _resolve_model_aliases(models: Optional[dict[str, str]],
                           configuration: ExperimentConfig) -> dict[str, str]:
    """Fill role defaults and resolve only the two configured tier aliases.

    Any other value is an explicit provider model ID and is passed through
    unchanged. Resolving before pipeline startup makes missing tier settings
    fail before the first model request.
    """
    if configuration.pipeline == "single":
        supplied = dict(models or {})
        model = supplied.get("single_agent", "strong")
        if model in ("small", "strong"):
            model = model_for("A", model)
        return {**supplied, "single_agent": model}

    resolved = {
        "planner": "strong",
        "concept": "small",
        "builder": "small",
        "critic": "strong",
    }
    if models is not None:
        resolved.update(models)
    return {
        role: model_for("A", model) if model in ("small", "strong") else model
        for role, model in resolved.items()
    }


def _usage(result: Any) -> dict[str, Any]:
    tracker = getattr(result, "tracker", None)

    if tracker is None:
        return {}

    data = tracker.to_dict()

    return {
        "llm_calls": data.get("llm_calls"),
        "tool_calls": data.get("tool_calls"),
        "input_tokens": data.get("input_tokens"),
        "output_tokens": data.get("output_tokens"),
    }


def _execution_size(result: Any) -> Optional[int]:
    execution = getattr(result, "execution", None)

    if execution is None:
        return None

    return getattr(execution, "size", None)


def _comparable_patient_sets(
    result: Any,
    reference: Optional[dict[str, Any]],
) -> tuple[Optional[set[int]], Optional[set[int]], list[str]]:
    """Return patient sets only when the evaluator explicitly marks the
    reference IDs as comparable with this execution's patient IDs.

    `comparable_patient_ids` is an evaluator-side contract. Ordinary reference
    concept files and cohort counts are not sufficient to establish patient
    identity or a shared ID namespace.
    """
    execution = getattr(result, "execution", None)
    predicted = getattr(execution, "persons", None)
    reasons = []
    if predicted is None:
        reasons.append("predicted_patient_set_unavailable")

    reference_ids = (
        reference.get("comparable_patient_ids")
        if reference is not None else None
    )
    if reference_ids is None:
        reasons.append("comparable_reference_patient_set_unavailable")

    if reasons:
        return None, None, reasons

    return set(predicted), set(reference_ids), []


def _run_real_pipeline(
    *,
    task: Any,
    configuration: ExperimentConfig,
    client: Any,
    vocab_con: Any,
    cdm_con: Any = None,
    models: Optional[dict[str, str]] = None,
    budget: Optional[Budget] = None,
    log: Any = None,
    reference: Optional[dict[str, Any]] = None,
    deadline_at: Optional[float] = None,
) -> RunRecord:
    """Execute exactly one real benchmark pipeline."""

    question = str(task.question)
    task_id = str(task.task_id)

    started = time.perf_counter()
    if deadline_at is not None:
        client = _DeadlineClient(client, deadline_at)

    models = _resolve_model_aliases(models, configuration)

    if configuration.pipeline == "single":
        result = run_single_agent(
            client=client,
            model=models["single_agent"],
            question=question,
            vocab_con=vocab_con,
            budget=budget,
            log=log,
        )
    elif configuration.pipeline == "multi":
        result = run_multi_agent(
            client=client,
            models=models,
            question=question,
            vocab_con=vocab_con,
            cdm_con=cdm_con,
            budget=budget,
            use_critic=configuration.use_critic,
            use_validator=configuration.use_validator,
            log=log,
        )
    else:
        raise ValueError(
            f"Unknown pipeline '{configuration.pipeline}' "
            f"for configuration '{configuration.name}'"
        )

    elapsed = time.perf_counter() - started

    usage = _usage(result)

    execution_size = _execution_size(result)
    predicted_patients, reference_patients, cohort_unavailable_reasons = \
        _comparable_patient_sets(result, reference)

    # --------------------------------------------------------
    # V5.3 evaluator-side concept scoring
    #
    # Full scope:
    #   union of all resolved concept sets
    #
    # Entry scope:
    #   union of every resolved entry concept set (OR arms)
    #
    # Reference data never enters the LLM-facing pipeline.
    # --------------------------------------------------------
    resolved = getattr(result, "resolved", {}) or {}
    spec = getattr(result, "spec", None)

    predicted_concepts_full = set()
    for concept_ids in resolved.values():
        predicted_concepts_full.update(concept_ids)

    predicted_concepts_entry = set()

    if spec is not None:
        entry_names = getattr(spec, "entry_concept_sets", None) or []
        # Backward compatibility for spec-like objects from older callers.
        if not entry_names:
            legacy_name = getattr(spec, "entry_concept_set", None)
            entry_names = [legacy_name] if legacy_name is not None else []
        for entry_name in entry_names:
            predicted_concepts_entry.update(resolved.get(entry_name, set()))

    reference_full = None
    reference_entry = None

    if reference is not None:
        reference_full = set(
            reference.get("all_concept_ids", [])
        )
        reference_entry = set(
            reference.get("entry_concept_ids", [])
        )

    metadata = {
        "pipeline": configuration.pipeline,
        "use_critic": configuration.use_critic,
        "use_validator": configuration.use_validator,
        "critic_rounds": getattr(result, "critic_rounds", 0),
        "validator_retries": getattr(result, "validator_retries", 0),
        "unresolved": getattr(result, "unresolved", []),
        "resolved_sizes": {
            k: len(v)
            for k, v in resolved.items()
        },
        "resolved_full_count": len(predicted_concepts_full),
        "resolved_entry_count": len(predicted_concepts_entry),
    }
    if cohort_unavailable_reasons:
        metadata["cohort_metric_unavailable_reasons"] = \
            cohort_unavailable_reasons

    record = adjudication_record(
        task_id=task_id,
        configuration=configuration.name,

        # Primary V5.3 scope
        predicted_concepts_full=predicted_concepts_full
        if reference_full is not None else None,
        reference_concepts_full=reference_full,

        # Secondary V5.3 scope
        predicted_concepts_entry=predicted_concepts_entry
        if reference_entry is not None else None,
        reference_concepts_entry=reference_entry,

        predicted_patients=predicted_patients,
        reference_patients=reference_patients,

        scoring_scope=(
            "full_primary_entry_secondary"
            if reference_full is not None
            and reference_entry is not None
            else None
        ),

        executable=(
            True
            if execution_size is not None
            else None
        ),

        status=getattr(result, "status", "failed"),
        reason=getattr(result, "reason", None),

        metadata=metadata,
    )
    # Keep the actual validated phenotype attached to the attempt record so
    # recovery journals and their provenance traces can be independently
    # reviewed. Metrics alone do not constitute the scientific output.
    if spec is not None:
        record.final_spec = spec.model_dump()

    # Preserve execution/usage information already produced by the
    # runner. These assignments do not alter concept scoring.
    record.llm_calls = usage.get("llm_calls")
    record.tool_calls = usage.get("tool_calls")
    record.input_tokens = usage.get("input_tokens")
    record.output_tokens = usage.get("output_tokens")
    record.wall_seconds = elapsed

    if (predicted_patients is not None and reference_patients is not None
            and not predicted_patients and not reference_patients):
        record.metadata["cohort_metric_unavailable_reasons"] = [
            "both_comparable_patient_sets_empty"
        ]

    return record


def run_experiment(
    tasks: Iterable[Any],
    configurations: Iterable[ExperimentConfig],
    run_task: Optional[Callable[..., RunRecord]] = None,
    *,
    client: Any = None,
    vocab_con: Any = None,
    cdm_con: Any = None,
    models: Optional[dict[str, str]] = None,
    budget: Optional[Budget] = None,
    reference_loader: Optional[Callable[[str], Any]] = None,
    limit: Optional[int] = None,
    log_factory: Optional[Callable[..., Any]] = None,
) -> ExperimentResult:
    """Run benchmark configurations over blinded tasks.

    Two modes are supported:

    1. `run_task` supplied:
       deterministic injection mode for unit tests and future custom
       evaluation workflows.

    2. `run_task` omitted:
       execute the actual C1/C2/C3/C4 implementations.

    `reference_loader` is evaluator-side only. Its result is never passed into
    an agent pipeline.
    """

    task_list = list(tasks)

    if limit is not None:
        task_list = task_list[:limit]

    records: list[RunRecord] = []
    raw_deadline = os.environ.get("JBI_RUN_DEADLINE_S")
    deadline_s = None
    if raw_deadline:
        deadline_s = float(raw_deadline)
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            raise ValueError("JBI_RUN_DEADLINE_S must be a positive finite number")

    for configuration in configurations:
        for task in task_list:
            task_id = str(task.task_id)

            # Gold/reference material is deliberately isolated here.
            reference = (
                reference_loader(task_id)
                if reference_loader is not None
                else None
            )

            started = time.perf_counter()
            deadline_at = (time.monotonic() + deadline_s
                           if deadline_s is not None else None)

            log = None
            try:
                if run_task is not None:
                    record = run_task(
                        task=task,
                        configuration=configuration,
                        reference=reference,
                    )
                else:
                    if client is None:
                        raise ValueError(
                            "client is required for real pipeline execution"
                        )

                    log = (
                        log_factory(
                            task_id=task_id,
                            configuration=configuration.name,
                        )
                        if log_factory is not None
                        else None
                    )

                    record = _run_real_pipeline(
                        task=task,
                        configuration=configuration,
                        client=client,
                        vocab_con=vocab_con,
                        cdm_con=cdm_con,
                        models=models,
                        budget=budget,
                        log=log,
                        reference=reference,
                        deadline_at=deadline_at,
                    )

                if deadline_at is not None and time.monotonic() >= deadline_at:
                    raise RunDeadlineExceeded("JBI_RUN_DEADLINE_S exceeded")

            except RunDeadlineExceeded as exc:
                record = RunRecord(
                    task_id=task_id, configuration=configuration.name,
                    status="timeout", reason=str(exc))
                if log is not None:
                    final_spec = getattr(log, "final_spec", None)
                    if hasattr(log, "extra"):
                        log.extra["checkpoint"] = {
                            "status": "timeout", "task_id": task_id,
                            "configuration": configuration.name,
                            "reason": str(exc),
                        }
                    if hasattr(log, "finish"):
                        log.finish("timeout", final_spec=final_spec, error=str(exc))
                    elif hasattr(log, "save"):
                        log.status = "timeout"
                        log.error = str(exc)
                        log.save()

            except Exception as exc:
                record = RunRecord(
                    task_id=task_id,
                    configuration=configuration.name,
                    status="failed",
                    reason=f"{type(exc).__name__}: {exc}",
                )

            elapsed = time.perf_counter() - started

            if record.wall_seconds is None:
                record.wall_seconds = elapsed

            # Reference is evaluator-side and therefore belongs in metadata,
            # never in the LLM-facing task.
            if reference is not None:
                record.metadata["reference_supplied"] = True
            else:
                record.metadata["reference_supplied"] = False

            records.append(record)

    return ExperimentResult(records=records)


def run_real_configuration(
    task: Any,
    configuration: ExperimentConfig,
    *,
    client: Any,
    vocab_con: Any,
    cdm_con: Any = None,
    models: Optional[dict[str, str]] = None,
    budget: Optional[Budget] = None,
) -> RunRecord:
    """Small explicit entrypoint for one real configuration."""

    return _run_real_pipeline(
        task=task,
        configuration=configuration,
        client=client,
        vocab_con=vocab_con,
        cdm_con=cdm_con,
        models=models,
        budget=budget,
    )
