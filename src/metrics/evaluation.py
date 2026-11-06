"""Benchmark metrics, adjudication records, and experiment export."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass
class ConceptMetrics:
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    jaccard: Optional[float]


@dataclass
class CohortMetrics:
    jaccard: Optional[float]
    predicted_size: Optional[int] = None
    reference_size: Optional[int] = None


@dataclass
class RunRecord:
    task_id: str
    configuration: str
    status: str
    # The validated phenotype/specification is part of the scientific output,
    # not merely an execution log detail. Keep it with each new result record.
    final_spec: Optional[dict[str, Any]] = None
    concept_precision: Optional[float] = None
    concept_recall: Optional[float] = None
    concept_f1: Optional[float] = None
    concept_jaccard: Optional[float] = None

    # V5.3 primary concept metrics: full resolved definition.
    concept_precision_full: Optional[float] = None
    concept_recall_full: Optional[float] = None
    concept_f1_full: Optional[float] = None
    concept_jaccard_full: Optional[float] = None

    # V5.3 secondary concept metrics: entry concept set.
    concept_precision_entry: Optional[float] = None
    concept_recall_entry: Optional[float] = None
    concept_f1_entry: Optional[float] = None
    concept_jaccard_entry: Optional[float] = None

    scoring_scope: Optional[str] = None
    cohort_jaccard: Optional[float] = None
    predicted_patient_count: Optional[int] = None
    reference_patient_count: Optional[int] = None
    executable: Optional[bool] = None
    clinical_validity: Optional[float] = None
    reproducibility: Optional[float] = None
    llm_calls: Optional[int] = None
    tool_calls: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    wall_seconds: Optional[float] = None
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _safe_div(num: float, den: float) -> Optional[float]:
    return num / den if den else None


def set_metrics(predicted: Iterable[int], reference: Iterable[int]) -> ConceptMetrics:
    p = set(predicted)
    r = set(reference)

    inter = len(p & r)
    precision = _safe_div(inter, len(p))
    recall = _safe_div(inter, len(r))

    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    union = p | r
    jaccard = _safe_div(inter, len(union))

    return ConceptMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        jaccard=jaccard,
    )


def patient_set_jaccard(
    predicted: Iterable[int],
    reference: Iterable[int],
) -> CohortMetrics:
    p = set(predicted)
    r = set(reference)
    union = p | r

    return CohortMetrics(
        jaccard=_safe_div(len(p & r), len(union)),
        predicted_size=len(p),
        reference_size=len(r),
    )


def exact_match(predicted: Iterable[int], reference: Iterable[int]) -> bool:
    return set(predicted) == set(reference)


def aggregate(values: Iterable[Optional[float]]) -> dict[str, Optional[float]]:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]

    if not vals:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "sd": None,
            "min": None,
            "max": None,
        }

    return {
        "n": len(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "sd": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
    }


def summarize_runs(records: Iterable[RunRecord]) -> dict[str, Any]:
    rows = list(records)

    summary = {
        "n_runs": len(rows),
        "n_success": sum(r.status == "success" for r in rows),
        "n_failed": sum(r.status != "success" for r in rows),
        "concept_precision": aggregate(r.concept_precision for r in rows),
        "concept_recall": aggregate(r.concept_recall for r in rows),
        "concept_f1": aggregate(r.concept_f1 for r in rows),
        "concept_jaccard": aggregate(r.concept_jaccard for r in rows),

        "concept_precision_full": aggregate(
            r.concept_precision_full for r in rows
        ),
        "concept_recall_full": aggregate(
            r.concept_recall_full for r in rows
        ),
        "concept_f1_full": aggregate(
            r.concept_f1_full for r in rows
        ),
        "concept_jaccard_full": aggregate(
            r.concept_jaccard_full for r in rows
        ),

        "concept_precision_entry": aggregate(
            r.concept_precision_entry for r in rows
        ),
        "concept_recall_entry": aggregate(
            r.concept_recall_entry for r in rows
        ),
        "concept_f1_entry": aggregate(
            r.concept_f1_entry for r in rows
        ),
        "concept_jaccard_entry": aggregate(
            r.concept_jaccard_entry for r in rows
        ),

        "cohort_jaccard": aggregate(r.cohort_jaccard for r in rows),
        "clinical_validity": aggregate(r.clinical_validity for r in rows),
        "reproducibility": aggregate(r.reproducibility for r in rows),
        "llm_calls": aggregate(r.llm_calls for r in rows),
        "tool_calls": aggregate(r.tool_calls for r in rows),
        "input_tokens": aggregate(r.input_tokens for r in rows),
        "output_tokens": aggregate(r.output_tokens for r in rows),
        "wall_seconds": aggregate(r.wall_seconds for r in rows),
    }

    by_configuration: dict[str, Any] = {}

    for configuration in sorted({r.configuration for r in rows}):
        subset = [
            r for r in rows
            if r.configuration == configuration
        ]

        by_configuration[configuration] = {
            "n_runs": len(subset),
            "n_success": sum(r.status == "success" for r in subset),
            "n_failed": sum(r.status != "success" for r in subset),
            "concept_precision": aggregate(
                r.concept_precision for r in subset
            ),
            "concept_recall": aggregate(
                r.concept_recall for r in subset
            ),
            "concept_f1": aggregate(
                r.concept_f1 for r in subset
            ),
            "concept_jaccard": aggregate(
                r.concept_jaccard for r in subset
            ),
            "cohort_jaccard": aggregate(
                r.cohort_jaccard for r in subset
            ),
            "clinical_validity": aggregate(
                r.clinical_validity for r in subset
            ),
            "reproducibility": aggregate(
                r.reproducibility for r in subset
            ),
            "llm_calls": aggregate(
                r.llm_calls for r in subset
            ),
            "tool_calls": aggregate(
                r.tool_calls for r in subset
            ),
            "input_tokens": aggregate(
                r.input_tokens for r in subset
            ),
            "output_tokens": aggregate(
                r.output_tokens for r in subset
            ),
            "wall_seconds": aggregate(
                r.wall_seconds for r in subset
            ),
        }

    summary["by_configuration"] = by_configuration

    return summary


def adjudication_record(
    task_id: str,
    configuration: str,
    *,
    predicted_concepts: Optional[Iterable[int]] = None,
    reference_concepts: Optional[Iterable[int]] = None,
    predicted_patients: Optional[Iterable[int]] = None,
    reference_patients: Optional[Iterable[int]] = None,
    predicted_concepts_full: Optional[Iterable[int]] = None,
    reference_concepts_full: Optional[Iterable[int]] = None,
    predicted_concepts_entry: Optional[Iterable[int]] = None,
    reference_concepts_entry: Optional[Iterable[int]] = None,
    scoring_scope: Optional[str] = None,
    executable: Optional[bool] = None,
    clinical_validity: Optional[float] = None,
    reproducibility: Optional[float] = None,
    status: str = "success",
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> RunRecord:
    cm = (
        set_metrics(predicted_concepts, reference_concepts)
        if predicted_concepts is not None and reference_concepts is not None
        else None
    )

    pm = (
        patient_set_jaccard(predicted_patients, reference_patients)
        if predicted_patients is not None and reference_patients is not None
        else None
    )

    full_cm = (
        set_metrics(predicted_concepts_full, reference_concepts_full)
        if predicted_concepts_full is not None
        and reference_concepts_full is not None
        else None
    )

    entry_cm = (
        set_metrics(predicted_concepts_entry, reference_concepts_entry)
        if predicted_concepts_entry is not None
        and reference_concepts_entry is not None
        else None
    )

    return RunRecord(
        task_id=task_id,
        configuration=configuration,
        status=status,
        concept_precision=cm.precision if cm else None,
        concept_recall=cm.recall if cm else None,
        concept_f1=cm.f1 if cm else None,
        concept_jaccard=cm.jaccard if cm else None,

        concept_precision_full=full_cm.precision if full_cm else None,
        concept_recall_full=full_cm.recall if full_cm else None,
        concept_f1_full=full_cm.f1 if full_cm else None,
        concept_jaccard_full=full_cm.jaccard if full_cm else None,

        concept_precision_entry=entry_cm.precision if entry_cm else None,
        concept_recall_entry=entry_cm.recall if entry_cm else None,
        concept_f1_entry=entry_cm.f1 if entry_cm else None,
        concept_jaccard_entry=entry_cm.jaccard if entry_cm else None,

        scoring_scope=scoring_scope,

        cohort_jaccard=pm.jaccard if pm else None,
        predicted_patient_count=pm.predicted_size if pm else None,
        reference_patient_count=pm.reference_size if pm else None,
        executable=executable,
        clinical_validity=clinical_validity,
        reproducibility=reproducibility,
        reason=reason,
        metadata=metadata or {},
    )


def write_json(records: Iterable[RunRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [asdict(r) for r in records]
    path.write_text(
        json.dumps(rows, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_csv(records: Iterable[RunRecord], path: str | Path) -> None:
    from src.result_serialization import write_run_records_csv
    write_run_records_csv(records, path)


def write_summary(
    records: Iterable[RunRecord],
    path: str | Path,
) -> dict[str, Any]:
    rows = list(records)

    summary = summarize_runs(rows)

    by_config: dict[str, Any] = {}

    for config in sorted({r.configuration for r in rows}):
        subset = [r for r in rows if r.configuration == config]
        by_config[config] = summarize_runs(subset)

    summary["by_configuration"] = by_config

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return summary
