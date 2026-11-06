"""Independent, conservative diagnostics for generated cohort artifacts.

This module never supplies reference data to generation. It reports evidence
available in an already produced record/specification; absence stays unknown.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.metrics.evaluation import patient_set_jaccard, set_metrics
from src.schema.spec import CohortSpec


@dataclass
class ScientificQuality:
    grades: list[str] = field(default_factory=list)
    structural_validity: Optional[bool] = None
    concept_set_statistics: dict[str, dict[str, int]] = field(default_factory=dict)
    domain_issues: list[str] = field(default_factory=list)
    vocabulary_issues: list[str] = field(default_factory=list)
    temporal_rules: dict[str, Any] = field(default_factory=dict)
    execution_status: Optional[str] = None
    cohort_size_interpretation: Optional[str] = None
    reference_metrics: Optional[dict[str, Optional[float]]] = None
    recorded_metrics_unverified: dict[str, Any] = field(default_factory=dict)
    patient_set_jaccard: Optional[float] = None
    metric_denominators: dict[str, Optional[int]] = field(default_factory=dict)
    provenance_limitations: list[str] = field(default_factory=list)
    unresolved_semantics: list[str] = field(default_factory=list)
    evidence_grade: str = "EVIDENCE_INSUFFICIENT"
    findings: list[dict[str, Any]] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(code: str, severity: str, *, task_id: Optional[str], run_id: Optional[str],
             location: str, observed: Any, expected: Any, strength: str,
             remediation: str, blocks: tuple[str, ...] = ()) -> dict[str, Any]:
    """Stable finding contract shared by callable analysis and the CLI."""
    return {
        "code": code, "severity": severity, "task_id": task_id, "run_id": run_id,
        "source_location": location, "observed": observed, "expected": expected,
        "evidence_strength": strength, "recommended_remediation": remediation,
        "blocks": list(blocks),
    }


def _acceptance(spec_ok: Optional[bool], vocab_checked: bool, vocab_ok: Optional[bool],
                record: dict[str, Any], ref_ok: bool, metrics_complete: bool,
                provenance_complete: bool, clinical_review: bool) -> dict[str, Any]:
    """Independent evidence dimensions; no single composite quality score."""
    status = record.get("status")
    executed = (str(status).lower() == "success" and (
        str(record.get("execution_status", "")).lower() == "success"
        or record.get("executable") is True
    ))
    descriptive = bool(spec_ok is True and executed)
    return {
        "structure": ("STRUCTURALLY_VALID" if spec_ok is True else
                      "STRUCTURALLY_INVALID" if spec_ok is False else "STRUCTURALLY_UNVERIFIED"),
        "vocabulary": ("VOCABULARY_CHECKED" if vocab_checked and vocab_ok is True
                       else "VOCABULARY_INVALID" if vocab_checked and vocab_ok is False
                       else "VOCABULARY_UNVERIFIED"),
        "compilation": ("COMPILE_VERIFIED" if record.get("compiler_status") == "success"
                        else "COMPILE_FAILED" if str(record.get("compiler_status", "")).lower()
                        in {"failed", "failure", "invalid", "error"} else "COMPILE_UNVERIFIED"),
        "execution": "EXECUTION_VERIFIED" if executed else "EXECUTION_UNVERIFIED",
        "reference_comparison": "REFERENCE_COMPARABLE" if ref_ok else "COMPARISON_INCOMPARABLE",
        "metrics": "METRICS_COMPLETE" if metrics_complete else "EVALUATION_INCOMPLETE",
        "provenance": "PROVENANCE_COMPLETE" if provenance_complete else "PROVENANCE_INCOMPLETE",
        "clinical_review": ("CLINICAL_REVIEW_DOCUMENTED" if clinical_review
                            else "CLINICAL_VALIDITY_UNVERIFIED"),
        "eligibility": {
            "ELIGIBLE_FOR_DESCRIPTIVE_REPORTING": descriptive,
            # Pair eligibility is finalized at group level by analyze_records().
            "ELIGIBLE_FOR_PAIRED_COMPARISON": False,
        },
        "exclusion_reasons": ([] if descriptive else [
            reason for condition, reason in (
                (spec_ok is False, "invalid_specification"),
                (spec_ok is None, "structural_validity_unverified"),
                (not executed, "successful_execution_unverified"),
            ) if condition
        ]),
    }


def _concept_values(value: Any) -> tuple[Optional[list[int]], Optional[str]]:
    if not isinstance(value, (list, tuple, set)):
        return None, "expected list, tuple, or set of integer concept IDs"
    values = list(value)
    if any(not isinstance(item, int) or isinstance(item, bool) or item <= 0
           for item in values):
        return None, "concept IDs must be positive integers"
    return values, None


def _check_vocabulary(spec: CohortSpec, con) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    domains: list[str] = []
    for set_name, concept_set in spec.concept_sets.items():
        for item in concept_set.items:
            row = con.execute(
                "SELECT domain_id, standard_concept, invalid_reason "
                "FROM concept WHERE concept_id = ?", [item.concept_id]
            ).fetchone()
            if row is None:
                issues.append(f"{set_name}:{item.concept_id}:missing")
                continue
            domain, standard, invalid = row
            if invalid is not None:
                issues.append(f"{set_name}:{item.concept_id}:invalid")
            if standard != "S":
                issues.append(f"{set_name}:{item.concept_id}:nonstandard")
            if domain and domain != concept_set.domain:
                domains.append(f"{set_name}:{item.concept_id}:{domain}!={concept_set.domain}")
            if item.include_descendants:
                exists = con.execute(
                    "SELECT 1 FROM information_schema.tables WHERE lower(table_name)='concept_ancestor'"
                ).fetchone()
                if exists and con.execute(
                    "SELECT 1 FROM concept_ancestor WHERE ancestor_concept_id=? LIMIT 1",
                    [item.concept_id],
                ).fetchone() is None:
                    # A leaf can legitimately have no strict descendants. This is evidence,
                    # not a vocabulary error; callers must not infer broken vocabulary.
                    pass
    return issues, domains


def assess_artifact(spec: CohortSpec | dict[str, Any], record: Optional[dict[str, Any]] = None,
                    *, vocab_con=None, reference: Optional[dict[str, Any]] = None,
                    reference_version: Optional[str] = None,
                    vocabulary_version: Optional[str] = None,
                    vocabulary_sha256: Optional[str] = None,
                    task_id: Optional[str] = None, run_id: Optional[str] = None,
                    source_path: Optional[str] = None,
                    source_sha256: Optional[str] = None) -> ScientificQuality:
    """Assess an artifact without mutating it or exposing references to generation."""
    report = ScientificQuality()
    record = record if isinstance(record, dict) else {}
    task_id = str(task_id or record.get("task_id") or "") or None
    run_id = str(run_id or record.get("run_id") or "") or None
    vocabulary_check_complete = False
    if spec is None:
        report.structural_validity = None
        report.execution_status = record.get("status")
        report.recorded_metrics_unverified = {
            key: record[key] for key in (
                "concept_precision", "concept_recall", "concept_f1", "concept_jaccard",
                "concept_recall_full", "concept_precision_full", "concept_f1_full",
                "concept_jaccard_full", "cohort_jaccard",
            ) if key in record
        }
        report.unresolved_semantics.append("serialized specification unavailable")
        report.provenance = {"source_path": source_path, "source_sha256": source_sha256,
                             "task_id": task_id, "run_id": run_id,
                             "configuration": record.get("configuration"),
                             "model": record.get("model"),
                             "scorer_version": record.get("scorer_version")}
        report.findings.append(_finding(
            "SPEC_ARTIFACT_MISSING", "WARNING", task_id=task_id, run_id=run_id,
            location="spec", observed="not present in input", expected="serialized CohortSpec",
            strength="high", remediation="Preserve the generated specification with its run record.",
            blocks=("structural_validation", "vocabulary_validation", "clinical_semantics", "paired_comparison"),
        ))
        report.acceptance = _acceptance(None, vocab_con is not None, None, record,
                                        False, False, False, False)
        report.acceptance["exclusion_reasons"].append("structural_validity_unverified")
        if status := record.get("status"):
            if status not in ("success", "SUCCESS"):
                report.acceptance["exclusion_reasons"].append("run_failed_or_unresolved")
        report.acceptance["metrics"] = "EVALUATION_INCOMPLETE"
        if any(value is not None for value in report.recorded_metrics_unverified.values()):
            report.findings.append(_finding(
                "RECORDED_METRIC_NOT_RECOMPUTABLE", "WARNING", task_id=task_id,
                run_id=run_id, location="recorded_metrics_unverified",
                observed=report.recorded_metrics_unverified,
                expected="serialized prediction/reference sets, scorer version, scope, and denominators",
                strength="high", remediation="Retain recorded values as unverified observations; do not aggregate as validated scores.",
                blocks=("publication_metric_claim", "paired_comparison"),
            ))
        elif report.recorded_metrics_unverified:
            report.findings.append(_finding(
                "RECORDED_METRIC_MISSING", "WARNING", task_id=task_id,
                run_id=run_id, location="recorded_metrics_unverified",
                observed=report.recorded_metrics_unverified,
                expected="metric value, unique denominator, scorer and reference provenance",
                strength="high", remediation="Keep missing outcomes null; do not substitute zero.",
                blocks=("metric_claim", "paired_comparison"),
            ))
        report.evidence_grade = "EVIDENCE_INSUFFICIENT"
        return report
    try:
        parsed = spec if isinstance(spec, CohortSpec) else CohortSpec.model_validate(spec)
        report.structural_validity = True
        report.grades.append("STRUCTURALLY_VALID")
    except Exception as exc:
        report.structural_validity = False
        report.unresolved_semantics.append(f"specification_parse_error:{type(exc).__name__}")
        report.evidence_grade = "EVIDENCE_INSUFFICIENT"
        report.findings.append(_finding(
            "SPEC_SCHEMA_INVALID", "ERROR", task_id=task_id, run_id=run_id,
            location="spec", observed=type(exc).__name__, expected="valid CohortSpec",
            strength="high", remediation="Repair the specification against the declared schema.",
            blocks=("vocabulary", "compilation", "execution", "comparison"),
        ))
        report.acceptance = _acceptance(False, vocab_con is not None, None, record,
                                        False, False, False, False)
        return report

    for set_name, cs in parsed.concept_sets.items():
        seen: set[int] = set()
        for item in cs.items:
            if item.concept_id in seen:
                report.findings.append(_finding(
                    "CONCEPT_DUPLICATE", "WARNING", task_id=task_id, run_id=run_id,
                    location=f"spec.concept_sets.{set_name}.items",
                    observed=item.concept_id, expected="one occurrence per concept ID",
                    strength="high", remediation="Deduplicate concept items and retain the intended rationale.",
                ))
            seen.add(item.concept_id)
        if not any(not i.is_excluded for i in cs.items):
            report.findings.append(_finding(
                "CONCEPT_SET_NO_INCLUSIONS", "ERROR", task_id=task_id, run_id=run_id,
                location=f"spec.concept_sets.{set_name}.items",
                observed="zero included items", expected="at least one included concept",
                strength="high", remediation="Add justified inclusion concepts or remove the unusable set.",
                blocks=("compilation", "execution", "comparison"),
            ))

    for name, cs in parsed.concept_sets.items():
        report.concept_set_statistics[name] = {
            "items": len(cs.items),
            "included": sum(not i.is_excluded for i in cs.items),
            "excluded": sum(i.is_excluded for i in cs.items),
            "with_descendants": sum(i.include_descendants and not i.is_excluded for i in cs.items),
        }
    report.temporal_rules = {
        "prior_observation_days": parsed.prior_observation_days,
        "criteria": [{"set": c.concept_set, "rule": c.rule,
                      "window_start_days": c.window_start_days,
                      "window_end_days": c.window_end_days,
                      "boundaries_inclusive_in_current_compiler": True}
                     for c in parsed.criteria],
    }
    report.unresolved_semantics.extend([
        "question-to-criteria completeness requires independent clinical review",
        "criteria have no criterion-level source span or rationale field",
        "age uses calendar-year subtraction in current compiler",
        "criteria windows use event start dates; duration/overlap semantics are not represented",
        "exclusion semantics are per-criterion NOT EXISTS; no nested boolean groups",
        "concept scoring compares numeric IDs without standard-concept normalization",
    ])
    if vocab_con is not None:
        report.vocabulary_issues, report.domain_issues = _check_vocabulary(parsed, vocab_con)
        for issue in report.vocabulary_issues:
            report.findings.append(_finding(
                "VOCABULARY_CONCEPT_UNVERIFIED_OR_INVALID", "ERROR",
                task_id=task_id, run_id=run_id, location="spec.concept_sets.items",
                observed=issue, expected="concept exists, is valid, standard, and checked in declared vocabulary",
                strength="high" if issue.endswith((":missing", ":invalid", ":nonstandard")) else "moderate",
                remediation="Verify the concept in the declared vocabulary release and replace or justify it.",
                blocks=("vocabulary_validity", "clinical_mapping_claim"),
            ))
        for issue in report.domain_issues:
            report.findings.append(_finding(
                "VOCABULARY_DOMAIN_MISMATCH", "ERROR", task_id=task_id, run_id=run_id,
                location="spec.concept_sets.domain", observed=issue,
                expected="concept domain equals concept-set domain", strength="high",
                remediation="Correct the concept set domain or select a concept in the intended domain.",
                blocks=("vocabulary_validity", "execution_interpretation"),
            ))
        has_ancestor_table = vocab_con.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE lower(table_name)='concept_ancestor' LIMIT 1"
        ).fetchone() is not None
        if not has_ancestor_table and any(
            item.include_descendants
            for cs in parsed.concept_sets.values() for item in cs.items
        ):
            report.provenance_limitations.append(
                "concept_ancestor table unavailable; descendant expansion cannot be checked"
            )
        vocabulary_check_complete = (
            has_ancestor_table
            or not any(item.include_descendants
                       for cs in parsed.concept_sets.values() for item in cs.items)
        )
        report.provenance_limitations.append(
            "Maps to relationships are not applied by this reporter or resolver"
        )
        if vocabulary_version is None:
            report.provenance_limitations.append("vocabulary release/version not supplied")
        if (not report.vocabulary_issues and not report.domain_issues
                and vocabulary_check_complete):
            report.grades.append("VOCABULARY_VALIDATED")
    else:
        report.provenance_limitations.append("no vocabulary database/version supplied")
        report.findings.append(_finding(
            "VOCABULARY_EVIDENCE_MISSING", "WARNING", task_id=task_id, run_id=run_id,
            location="vocab_con", observed="not supplied", expected="read-only vocabulary and release identifier",
            strength="high", remediation="Supply the exact vocabulary database/release for concept checks.",
            blocks=("vocabulary_validity",),
        ))

    status = record.get("status")
    if status is not None:
        report.execution_status = str(status)
    else:
        report.provenance_limitations.append("compiler/execution status unavailable")
        report.findings.append(_finding(
            "EXECUTION_STATUS_MISSING", "WARNING", task_id=task_id, run_id=run_id,
            location="record.status", observed=None, expected="explicit execution outcome",
            strength="high", remediation="Retain the run status and execution evidence with the artifact.",
            blocks=("descriptive_reporting", "paired_comparison"),
        ))
    if record.get("compiler_status") != "success":
        report.findings.append(_finding(
            "COMPILATION_UNVERIFIED", "WARNING", task_id=task_id, run_id=run_id,
            location="record.compiler_status", observed=record.get("compiler_status"),
            expected="compiler_status=success with source/version-bound SQL evidence",
            strength="high", remediation="Record compiler outcome and generated SQL hash.",
            blocks=("compilation_claim",),
        ))
        if str(record.get("compiler_status", "")).lower() in {"failed", "failure", "invalid", "error"}:
            report.findings.append(_finding(
                "SQL_COMPILATION_FAILED", "ERROR", task_id=task_id, run_id=run_id,
                location="record.compiler_status", observed=record.get("compiler_status"),
                expected="successful SQL compilation against the declared dialect",
                strength="high", remediation="Preserve the failing SQL/error and repair compiler output before execution.",
                blocks=("compilation", "execution", "cohort_comparison"),
            ))
    if "predicted_patient_count" in record:
        report.cohort_size_interpretation = interpret_cohort_size(
            record.get("predicted_patient_count")
        )

    if reference is not None:
        pred, pred_error = _concept_values(record.get("predicted_concepts"))
        gold = reference.get("concept_ids")
        if gold is None and record.get("scoring_scope") == "full":
            gold = reference.get("all_concept_ids")
        elif gold is None and record.get("scoring_scope") == "entry":
            gold = reference.get("entry_concept_ids")
        gold, gold_error = _concept_values(gold)
        scopes_match = (
            "concept_ids" in reference
            or record.get("scoring_scope") == reference.get("scoring_scope")
            or (record.get("scoring_scope") == "full" and "all_concept_ids" in reference)
            or (record.get("scoring_scope") == "entry" and "entry_concept_ids" in reference)
        )
        same_version = bool(reference_version and reference.get("reference_version") == reference_version)
        if pred_error or gold_error:
            report.findings.append(_finding(
                "METRIC_INPUT_INVALID_OR_MISSING", "WARNING", task_id=task_id, run_id=run_id,
                location="record.predicted_concepts/reference.concept_ids",
                observed={"prediction": pred_error, "reference": gold_error},
                expected="available sequences of positive integer concept IDs",
                strength="high", remediation="Restore valid concept-ID sets and preserve missingness explicitly.",
                blocks=("concept_comparison", "paired_comparison"),
            ))
        if pred is not None and gold is not None and same_version and scopes_match:
            if len(set(pred)) != len(pred) or len(set(gold)) != len(gold):
                report.findings.append(_finding(
                    "METRIC_DUPLICATE_IDS_COLLAPSED", "INFO", task_id=task_id, run_id=run_id,
                    location="record.predicted_concepts/reference concepts",
                    observed={"predicted_rows": len(pred), "reference_rows": len(gold)},
                    expected="metric denominators count unique concept IDs",
                    strength="high", remediation="Retain unique denominators in the report.",
                ))
            m = set_metrics(pred, gold)
            report.reference_metrics = {"precision": m.precision, "recall": m.recall,
                                        "f1": m.f1, "jaccard": m.jaccard}
            report.metric_denominators = {"predicted_unique_concepts": len(set(pred)),
                                          "reference_unique_concepts": len(set(gold))}
        else:
            report.grades.append("COMPARISON_INCOMPARABLE")
            if pred is None or gold is None:
                report.grades.append("EVALUATION_INCOMPLETE")
            report.provenance_limitations.append(
                "reference comparison lacks predictions, concepts, matching explicit version, or matching scoring scope")
            if not same_version:
                report.findings.append(_finding(
                    "REFERENCE_VERSION_MISMATCH", "WARNING", task_id=task_id, run_id=run_id,
                    location="reference.reference_version", observed=reference.get("reference_version"),
                    expected=reference_version, strength="high",
                    remediation="Use a matching, hash-identified reference version or mark the comparison incomparable.",
                    blocks=("concept_comparison", "paired_comparison"),
                ))
            if not scopes_match:
                report.findings.append(_finding(
                    "SCORING_SCOPE_MISMATCH", "WARNING", task_id=task_id, run_id=run_id,
                    location="record.scoring_scope/reference concept fields",
                    observed=record.get("scoring_scope"), expected="matching explicit scoring scope",
                    strength="high", remediation="Align full/entry scope before comparing.",
                    blocks=("concept_comparison", "paired_comparison"),
                ))
        predicted_patients = record.get("predicted_patient_ids")
        reference_patients = reference.get("comparable_patient_ids")
        predicted_namespace = record.get("patient_id_namespace")
        reference_namespace = reference.get("patient_id_namespace")
        if (predicted_patients is not None and reference_patients is not None
                and predicted_namespace is not None
                and predicted_namespace == reference_namespace):
            pm = patient_set_jaccard(predicted_patients, reference_patients)
            report.patient_set_jaccard = pm.jaccard
            report.metric_denominators.update({
                "predicted_unique_patients": pm.predicted_size,
                "reference_unique_patients": pm.reference_size,
            })
        elif predicted_patients is not None or reference_patients is not None:
            report.provenance_limitations.append(
                "patient sets not compared: patient IDs or matching namespace evidence unavailable"
            )
            report.findings.append(_finding(
                "PATIENT_SET_COMPARISON_INELIGIBLE", "WARNING", task_id=task_id,
                run_id=run_id, location="record/reference patient IDs and namespace",
                observed={"predicted_ids_available": predicted_patients is not None,
                          "reference_ids_available": reference_patients is not None,
                          "namespace_match": bool(predicted_namespace and
                                                   predicted_namespace == reference_namespace)},
                expected="both patient ID sets and equal dataset/ID namespace provenance",
                strength="high", remediation="Provide comparable IDs with dataset snapshot and namespace evidence.",
                blocks=("patient_set_comparison",),
            ))
    elif any(k in record for k in ("concept_precision", "concept_recall", "concept_f1", "concept_jaccard")):
        report.grades.append("EVALUATION_INCOMPLETE")
        report.provenance_limitations.append("metric values supplied without set inputs/denominators")

    if (not report.vocabulary_issues and not report.domain_issues
            and vocabulary_check_complete):
        report.evidence_grade = "VOCABULARY_VALIDATED"
    else:
        report.evidence_grade = "SEMANTICALLY_UNVERIFIED"
    if reference is not None and report.reference_metrics is None:
        report.evidence_grade = "COMPARISON_INCOMPARABLE"
    if status not in ("success", None):
        report.grades.append("EVALUATION_INCOMPLETE")
    metrics_complete = bool(report.reference_metrics is not None and all(
        report.reference_metrics.get(key) is not None
        for key in ("precision", "recall", "f1", "jaccard")
    ))
    if report.reference_metrics is not None and not metrics_complete:
        report.findings.append(_finding(
            "METRIC_DENOMINATOR_OR_VALUE_MISSING", "WARNING", task_id=task_id,
            run_id=run_id, location="reference_metrics/metric_denominators",
            observed={"metrics": report.reference_metrics,
                      "denominators": report.metric_denominators},
            expected="all requested metric values and unique-set denominators, or explicit undefined reason",
            strength="high", remediation="Preserve undefined metrics and document the denominator convention.",
            blocks=("complete_metric_claim", "paired_comparison"),
        ))
    ref_ok = report.reference_metrics is not None
    clinical_review = bool(
        record.get("clinical_review_status") == "independently_adjudicated"
        and record.get("clinical_review_record")
        and record.get("reviewer_count", 0) >= 1
        and record.get("reviewers_independent") is True
    )
    report.provenance = {
        "source_path": source_path,
        "source_sha256": source_sha256,
        "task_id": task_id,
        "run_id": run_id,
        "configuration": record.get("configuration"),
        "model": record.get("model"),
        "scorer_version": record.get("scorer_version"),
        "reference_version": reference.get("reference_version") if reference else None,
        "reference_sha256": reference.get("reference_sha256") if reference else None,
        "vocabulary_version": vocabulary_version,
        "vocabulary_sha256": vocabulary_sha256,
    }
    required_prov = (task_id, run_id, record.get("configuration"),
                     record.get("model"), record.get("scorer_version"), source_sha256,
                     vocabulary_version if vocab_con is not None else "no_vocabulary_used",
                     vocabulary_sha256 if vocab_con is not None else "no_vocabulary_used")
    provenance_complete = all(value is not None for value in required_prov)
    if reference is not None:
        provenance_complete = provenance_complete and bool(
            reference.get("reference_version") and reference.get("reference_sha256")
        )
    if not provenance_complete:
        report.findings.append(_finding(
            "PROVENANCE_INCOMPLETE", "WARNING", task_id=task_id, run_id=run_id,
            location="record/provenance", observed={k: v for k, v in report.provenance.items()
                                                       if v is None},
            expected="task/run/configuration/model/scorer and source/reference hashes as applicable",
            strength="high", remediation="Bind the diagnostic to immutable input and evaluation provenance.",
            blocks=("reproducibility_claim", "paired_comparison"),
        ))
    report.acceptance = _acceptance(
        report.structural_validity is True, vocab_con is not None,
        not bool(report.vocabulary_issues or report.domain_issues) and vocabulary_check_complete,
        record, ref_ok, metrics_complete, provenance_complete, clinical_review,
    )
    if not clinical_review:
        report.findings.append(_finding(
            "CLINICAL_REVIEW_UNVERIFIED", "INFO", task_id=task_id, run_id=run_id,
            location="record.clinical_review_status", observed=record.get("clinical_review_status"),
            expected="independent documented clinical adjudication", strength="high",
            remediation="Obtain blinded independent phenotype review before making clinical-validity claims.",
            blocks=("clinical_validity_claim",),
        ))
    # Deliberately never infer clinical adjudication from software evidence.
    return report


def interpret_cohort_size(size: Optional[int]) -> str:
    """Zero is a data-dependent observation, not a clinical error label."""
    if size is None:
        return "UNKNOWN_SIZE"
    if size == 0:
        return "ZERO_PATIENTS_REQUIRES_DATA_AND_LOGIC_REVIEW"
    return "NONZERO_COHORT_REQUIRES_SANITY_REVIEW"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_records(rows: list[dict[str, Any]], *, vocab_con=None,
                    input_path: Optional[str] = None,
                    input_sha256: Optional[str] = None,
                    vocabulary_version: Optional[str] = None,
                    vocabulary_sha256: Optional[str] = None,
                    vocabulary_path: Optional[str] = None) -> dict[str, Any]:
    """Analyze supplied artifact rows and decide paired eligibility per original task.

    Input row contract: task_id, run_id, configuration, spec, record, optional
    reference/reference_version. Repeated task/config attempts make that task
    ineligible for pairing unless upstream reconciliation supplied one row.
    """
    reports: list[dict[str, Any]] = []
    for row in rows:
        report = assess_artifact(
            row.get("spec", {}), row.get("record", row), vocab_con=vocab_con,
            reference=row.get("reference"),
            reference_version=row.get("reference_version") or
            (row.get("reference") or {}).get("reference_version"),
            vocabulary_version=vocabulary_version,
            vocabulary_sha256=vocabulary_sha256,
            task_id=row.get("task_id"), run_id=row.get("run_id"),
            source_path=input_path, source_sha256=input_sha256,
        ).to_dict()
        report["configuration"] = row.get("configuration") or row.get("record", {}).get("configuration")
        report["scoring_scope"] = row.get("record", {}).get("scoring_scope")
        if row.get("best_supported_classification") is not None:
            report["reconciliation_evidence"] = {
                "best_supported_classification": row.get("best_supported_classification"),
                "original_queue_status": row.get("original_queue_status"),
                "attempt_statuses": row.get("attempt_statuses", []),
                "attempt_count_records": row.get("attempt_count_records"),
                "metric_provenance": row.get("metric_provenance"),
                "attempt_evidence": row.get("attempt_evidence", []),
                "individual_result_path": row.get("individual_result_path"),
                "individual_result_status": row.get("individual_result_status"),
                "models_seen": row.get("models_seen", []),
                "original_log_model_label": row.get("original_log_model_label"),
                "original_failure_reason": row.get("original_failure_reason"),
                "reference_supplied_recorded": row.get("reference_supplied_recorded"),
            }
        reports.append(report)

    by_task_config: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for report in reports:
        key = (str(report["provenance"].get("task_id") or ""),
               str(report.get("configuration") or ""))
        by_task_config.setdefault(key, []).append(report)
    duplicate_keys = {key for key, group in by_task_config.items() if key[0] and len(group) > 1}
    for key in duplicate_keys:
        for report in by_task_config[key]:
            report["acceptance"]["eligibility"]["ELIGIBLE_FOR_PAIRED_COMPARISON"] = False
            report["acceptance"]["exclusion_reasons"].append("multiple_attempts_for_task_configuration_unreconciled")
            report["findings"].append(_finding(
                "MULTIPLE_ATTEMPTS_UNRECONCILED", "WARNING", task_id=key[0],
                run_id=report["provenance"].get("run_id"),
                location="input.records", observed=len(by_task_config[key]),
                expected="one reconciled canonical attempt per original task/configuration",
                strength="high", remediation="Use the integrity workstream's reconciled canonical status; never count retries as separate tasks.",
                blocks=("paired_comparison",),
            ))

    by_task: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        task_id = str(report["provenance"].get("task_id") or "")
        if task_id:
            by_task.setdefault(task_id, []).append(report)
    paired_tasks: set[str] = set()
    for task_id, group in by_task.items():
        if any((task_id, str(r.get("configuration") or "")) in duplicate_keys for r in group):
            continue
        eligible = [r for r in group if r["acceptance"]["eligibility"][
            "ELIGIBLE_FOR_DESCRIPTIVE_REPORTING"] and r["acceptance"]["metrics"] == "METRICS_COMPLETE"]
        refs = {r["provenance"].get("reference_version") for r in eligible}
        hashes = {r["provenance"].get("reference_sha256") for r in eligible}
        vocabulary_versions = {r["provenance"].get("vocabulary_version") for r in eligible}
        vocabulary_hashes = {r["provenance"].get("vocabulary_sha256") for r in eligible}
        scopes = {r.get("scoring_scope") for r in eligible}
        scorers = {r["provenance"].get("scorer_version") for r in eligible}
        configs = {r.get("configuration") for r in eligible}
        group_ok = (len(eligible) >= 2 and len(configs) >= 2 and len(refs) == 1
                    and None not in refs and len(hashes) == 1 and None not in hashes
                    and len(vocabulary_versions) == 1 and None not in vocabulary_versions
                    and len(vocabulary_hashes) == 1 and None not in vocabulary_hashes
                    and len(scopes) == 1 and None not in scopes
                    and len(scorers) == 1 and None not in scorers)
        if group_ok:
            paired_tasks.add(task_id)
            for report in eligible:
                report["acceptance"]["eligibility"]["ELIGIBLE_FOR_PAIRED_COMPARISON"] = True
        else:
            for report in group:
                report["acceptance"]["exclusion_reasons"].append("task_pair_lacks_aligned_versions_scope_metrics_or_provenance")

    findings = [finding for report in reports for finding in report["findings"]]
    findings.sort(key=lambda f: (f.get("task_id") or "", f.get("run_id") or "",
                                f.get("code") or "", f.get("source_location") or ""))
    classifications = [r.get("reconciliation_evidence", {}).get("best_supported_classification")
                       for r in reports if r.get("reconciliation_evidence")]
    return {
        "input": {"path": input_path, "sha256": input_sha256},
        "vocabulary": {"path": vocabulary_path,
                       "version": vocabulary_version,
                       "sha256": vocabulary_sha256,
                       "read_only": vocab_con is not None},
        "counts": {
            "input_records": len(rows), "original_tasks": len(by_task),
            "descriptive_records": sum(r["acceptance"]["eligibility"][
                "ELIGIBLE_FOR_DESCRIPTIVE_REPORTING"] for r in reports),
            "paired_eligible_original_tasks": len(paired_tasks),
            "unreconciled_task_configuration_groups": len(duplicate_keys),
            "specification_missing_records": sum(
                r["acceptance"]["structure"] == "STRUCTURALLY_UNVERIFIED" for r in reports),
            "failed_or_unresolved_records": sum(
                (r.get("reconciliation_evidence", {}).get("best_supported_classification") != "VERIFIED SUCCESS")
                if r.get("reconciliation_evidence") else
                (r["acceptance"]["execution"] != "EXECUTION_VERIFIED")
                for r in reports),
            "execution_evidence_unverified_records": sum(
                r["acceptance"]["execution"] == "EXECUTION_UNVERIFIED" for r in reports),
            "verified_success_classification_records": classifications.count("VERIFIED SUCCESS"),
            "reconciled_classification_counts": dict(sorted(Counter(
                c for c in classifications if c is not None).items())),
            "records_with_recorded_metric_fields": sum(
                bool(r.get("recorded_metrics_unverified")) for r in reports),
            "records_with_nonmissing_unverified_metrics": sum(
                any(v is not None for v in r.get("recorded_metrics_unverified", {}).values())
                for r in reports),
            "records_with_only_missing_metric_values": sum(
                bool(r.get("recorded_metrics_unverified")) and not any(
                    v is not None for v in r.get("recorded_metrics_unverified", {}).values())
                for r in reports),
            "findings": len(findings),
        },
        "records": sorted(reports, key=lambda r: (
            r["provenance"].get("task_id") or "", r.get("configuration") or "",
            r["provenance"].get("run_id") or "")),
        "findings": findings,
        "claim_boundaries": [
            "schema, vocabulary lookup, compilation, and execution do not establish clinical validity",
            "zero-patient cohorts require data-coverage and logic review and are not automatically errors",
            "paired eligibility is descriptive metric comparability, not evidence of clinical superiority",
            "clinical validity requires independent documented clinical adjudication",
        ],
    }


def reconciliation_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservatively adapt Codex 2 logical-run ledger rows without upgrading status."""
    logical_runs = ledger.get("logical_runs")
    if not isinstance(logical_runs, list):
        raise ValueError("reconciliation ledger lacks logical_runs list")
    rows = []
    for item in logical_runs:
        if not isinstance(item, dict):
            continue
        status = item.get("individual_result_status") or item.get("original_queue_status")
        record = {
            "task_id": item.get("task_id"), "run_id": item.get("run_id"),
            "configuration": item.get("configuration"), "status": status,
            "model": ",".join(item.get("models_seen", [])) or None,
            "concept_recall_full": item.get("recorded_full_recall"),
            "scoring_scope": item.get("recorded_scoring_scope"),
            "reference_supplied_recorded": item.get("reference_supplied_recorded"),
            "metric_provenance": item.get("metric_provenance"),
        }
        rows.append({
            "task_id": item.get("task_id"), "run_id": item.get("run_id"),
            "configuration": item.get("configuration"), "spec": None,
            "record": record,
            "best_supported_classification": item.get("best_supported_classification"),
            "original_queue_status": item.get("original_queue_status"),
            "attempt_statuses": item.get("attempt_statuses", []),
            "attempt_count_records": item.get("attempt_count_records"),
            "metric_provenance": item.get("metric_provenance"),
            "attempt_evidence": item.get("attempt_evidence", []),
            "individual_result_path": item.get("individual_result_path"),
            "individual_result_status": item.get("individual_result_status"),
            "models_seen": item.get("models_seen", []),
            "original_log_model_label": item.get("original_log_model_label"),
            "original_failure_reason": item.get("original_failure_reason"),
            "reference_supplied_recorded": item.get("reference_supplied_recorded"),
        })
    return rows


def _markdown_report(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# Scientific validation evidence report", "",
        "## Evidence summary", "",
        f"- Input records: {counts['input_records']}",
        f"- Original tasks: {counts['original_tasks']}",
        f"- Descriptive-eligible records: {counts['descriptive_records']}",
        f"- Paired-eligible original tasks: {counts['paired_eligible_original_tasks']}",
        f"- Unreconciled task/config attempt groups: {counts['unreconciled_task_configuration_groups']}",
        f"- Findings: {counts['findings']}", "",
        "## Task-level eligibility", "",
        "| Task | Run | Config | Structure | Vocabulary | Execution | Comparison | Metrics | Descriptive | Paired | Reconciled class | Exclusion reasons |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["records"]:
        acc = row["acceptance"]
        lines.append("| " + " | ".join(str(x or "") for x in (
            row["provenance"].get("task_id"), row["provenance"].get("run_id"),
            row.get("configuration"), acc.get("structure"), acc.get("vocabulary"),
            acc.get("execution"), acc.get("reference_comparison"), acc.get("metrics"),
            acc["eligibility"].get("ELIGIBLE_FOR_DESCRIPTIVE_REPORTING"),
            acc["eligibility"].get("ELIGIBLE_FOR_PAIRED_COMPARISON"),
            row.get("reconciliation_evidence", {}).get("best_supported_classification"),
            "; ".join(acc.get("exclusion_reasons", [])))) + " |")
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("No diagnostic findings were emitted; this does not imply clinical validity.")
    else:
        lines += ["| Code | Severity | Task/Run | Location | Observed | Expected | Strength | Blocks |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for f in report["findings"]:
            lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in (
                f["code"], f["severity"], f"{f.get('task_id') or ''}/{f.get('run_id') or ''}",
                f["source_location"], json.dumps(f["observed"], sort_keys=True),
                json.dumps(f["expected"], sort_keys=True), f["evidence_strength"],
                ", ".join(f["blocks"]))) + " |")
    lines += ["", "## Unsupported claims", ""]
    lines += [f"- {claim}" for claim in report["claim_boundaries"]]
    lines.append("")
    return "\n".join(lines)


def write_release(report: dict[str, Any], output_dir: Path) -> None:
    """Write only derived report files. Deterministic and idempotent for same inputs."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scientific_findings.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = ["code", "severity", "task_id", "run_id", "source_location", "observed",
              "expected", "evidence_strength", "recommended_remediation", "blocks"]
    with (output_dir / "diagnostic_ledger.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for finding in report["findings"]:
            writer.writerow({**finding,
                             "observed": json.dumps(finding["observed"], sort_keys=True),
                             "expected": json.dumps(finding["expected"], sort_keys=True),
                             "blocks": ";".join(finding["blocks"])})
    (output_dir / "scientific_validation_report.md").write_text(
        _markdown_report(report), encoding="utf-8")


def _load_input(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("records") if isinstance(value, dict) else value
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("input must be a JSON list of record objects or an object with a records list")
    base = path.resolve().parent
    for row in rows:
        for key in ("spec_path", "reference_path"):
            if row.get(key):
                artifact = Path(row[key])
                if not artifact.is_absolute():
                    artifact = base / artifact
                row[key] = str(artifact.resolve())
                payload = json.loads(artifact.read_text(encoding="utf-8"))
                row[key.removesuffix("_path")] = payload
                row[f"{key.removesuffix('_path')}_sha256"] = sha256_file(artifact)
                if key == "reference_path":
                    payload["reference_sha256"] = row["reference_sha256"]
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only JBI scientific-quality reporter")
    parser.add_argument("input", type=Path, help="JSON records envelope (spec and record per row)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--vocab-db", type=Path)
    parser.add_argument("--vocabulary-version")
    parser.add_argument("--vocabulary-sha256")
    args = parser.parse_args(argv)
    raw_input = json.loads(args.input.read_text(encoding="utf-8"))
    reconciliation_meta = None
    if isinstance(raw_input, dict) and "logical_runs" in raw_input:
        rows = reconciliation_rows(raw_input)
        reconciliation_meta = {
            "schema_version": raw_input.get("schema_version"),
            "queue_sha256": raw_input.get("queue_sha256"),
            "attempt_source_reconciliation": raw_input.get("attempt_source_reconciliation"),
            "interpretation": raw_input.get("interpretation"),
            "reconciled_attempt_count": len(raw_input.get("attempts", [])),
        }
    else:
        rows = _load_input(args.input)
    vocab = None
    observed_vocabulary_sha256 = None
    if args.vocab_db:
        import duckdb
        observed_vocabulary_sha256 = sha256_file(args.vocab_db)
        if (args.vocabulary_sha256 is not None
                and args.vocabulary_sha256 != observed_vocabulary_sha256):
            raise ValueError("supplied vocabulary SHA-256 does not match read-only database bytes")
        vocab = duckdb.connect(args.vocab_db.as_posix(), read_only=True)
    try:
        report = analyze_records(rows, vocab_con=vocab, input_path=str(args.input.resolve()),
                                 input_sha256=sha256_file(args.input),
                                 vocabulary_version=args.vocabulary_version,
                                 vocabulary_sha256=observed_vocabulary_sha256,
                                 vocabulary_path=str(args.vocab_db.resolve()) if args.vocab_db else None)
        if reconciliation_meta is not None:
            report["reconciliation_source"] = reconciliation_meta
            report["counts"]["reconciled_attempts"] = reconciliation_meta["reconciled_attempt_count"]
            report["counts"]["original_task_denominator"] = report["counts"]["original_tasks"]
            report["counts"]["attempts_counted_as_independent_tasks"] = 0
        write_release(report, args.output_dir)
    finally:
        if vocab is not None:
            vocab.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
