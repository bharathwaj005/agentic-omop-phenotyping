"""Rule-based validation.

Runs BEFORE the Critic, and that ordering is a deliberate design choice: cheap
deterministic checks catch the mechanical errors (non-existent concept, wrong
domain, empty set), so the expensive model is only asked about things that need
judgement. Configuration C4 removes this module to measure what it contributes.

Every issue has a level:
    error   -> blocks execution; the Builder must fix it
    warning -> passed to the Critic as context, does not block
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

from src.schema.spec import CohortSpec
from src.tools.compiler import DOMAIN_TABLES

# A concept set resolving to more than this is probably too broad.
BROAD_THRESHOLD = 2000

# A lightweight guard against demographic restrictions that were not stated by
# the task. It deliberately recognizes only explicit ages or common age-group
# words; it does not attempt to infer a clinically correct age threshold.
_AGE_SCOPE_CUE = re.compile(
    r"\b(?:age|aged)\s*(?:of\s*)?\d{1,3}\b"
    r"|\b\d{1,3}\s*(?:years?\s*old|yo)\b"
    r"|\b(?:adult|adults|child|children|pediatric|paediatric|"
    r"adolescent|adolescents|teenager|teenagers|infant|infants|"
    r"neonate|neonates|elderly|older\s+adults?)\b",
    re.IGNORECASE,
)


@dataclass
class Issue:
    level: str          # "error" | "warning"
    code: str
    message: str
    concept_set: Optional[str] = None
    concept_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ValidationResult:
    def __init__(self, issues: list[Issue]):
        self.issues = issues

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_text(self, limit: int = 20) -> str:
        """Compact form for a prompt."""
        if not self.issues:
            return "all checks passed"
        lines = []
        for i in self.issues[:limit]:
            where = f" [{i.concept_set}]" if i.concept_set else ""
            cid = f" concept {i.concept_id}" if i.concept_id else ""
            lines.append(f"{i.level.upper()} {i.code}{where}{cid}: {i.message}")
        if len(self.issues) > limit:
            lines.append(f"... {len(self.issues) - limit} more")
        return "\n".join(lines)

    def to_list(self) -> list[dict]:
        return [i.to_dict() for i in self.issues]


def validate(spec: CohortSpec, vocab_con=None,
             resolved: Optional[dict[str, set[int]]] = None) -> ValidationResult:
    """Check a specification.

    vocab_con : optional DuckDB connection for concept-level checks
    resolved  : optional {set name -> resolved concept ids} for size checks
    """
    issues: list[Issue] = []

    # Unsupported demographic filters can materially change cohort membership.
    # This check only detects an absent textual age cue; it does not validate
    # whether a stated age group maps to the selected numeric cutoff.
    if (spec.age_min is not None or spec.age_max is not None) and not _AGE_SCOPE_CUE.search(
        spec.question or ""
    ):
        issues.append(Issue(
            "error", "age_filter_not_in_question",
            "age_min/age_max is set but the question states no age or age-group restriction; remove it or use an explicitly supported population scope",
        ))

    # --- structural ---------------------------------------------------------
    for name, cs in spec.concept_sets.items():
        if cs.domain not in DOMAIN_TABLES:
            issues.append(Issue("error", "unsupported_domain",
                                f"domain {cs.domain!r} cannot be compiled",
                                concept_set=name))
        if not cs.items:
            level = "error" if name in spec.entry_concept_sets else "warning"
            issues.append(Issue(level, "empty_concept_set",
                                "concept set has no concepts", concept_set=name))
        elif not any(not i.is_excluded for i in cs.items):
            issues.append(Issue("error", "only_exclusions",
                                "concept set contains only excluded concepts",
                                concept_set=name))

        seen: set[int] = set()
        for item in cs.items:
            if item.concept_id in seen:
                issues.append(Issue("warning", "duplicate_concept",
                                    "concept listed more than once",
                                    concept_set=name, concept_id=item.concept_id))
            seen.add(item.concept_id)

    for name in spec.unfilled_sets():
        if name not in spec.entry_concept_sets:
            issues.append(Issue("warning", "unfilled_set",
                                "concept set was never populated",
                                concept_set=name))

    # --- vocabulary checks --------------------------------------------------
    if vocab_con is not None:
        ids = sorted({i.concept_id for cs in spec.concept_sets.values()
                      for i in cs.items})
        if ids:
            ph = ",".join("?" * len(ids))
            rows = vocab_con.execute(
                f"""SELECT concept_id, domain_id, standard_concept, invalid_reason
                    FROM concept WHERE concept_id IN ({ph})""", ids
            ).fetchall()
            found = {r[0]: r for r in rows}

            for name, cs in spec.concept_sets.items():
                for item in cs.items:
                    row = found.get(item.concept_id)
                    if row is None:
                        issues.append(Issue(
                            "error", "concept_not_found",
                            "concept id does not exist in the vocabulary",
                            concept_set=name, concept_id=item.concept_id))
                        continue
                    _, domain, standard, invalid = row
                    if invalid is not None:
                        issues.append(Issue(
                            "error", "concept_invalid",
                            "concept is deprecated or invalid",
                            concept_set=name, concept_id=item.concept_id))
                    if standard != "S":
                        issues.append(Issue(
                            "error", "concept_not_standard",
                            "concept is not standard; map it first",
                            concept_set=name, concept_id=item.concept_id))
                    if domain and domain != cs.domain:
                        issues.append(Issue(
                            "error", "domain_mismatch",
                            f"concept is in domain {domain!r} but the set "
                            f"declares {cs.domain!r}",
                            concept_set=name, concept_id=item.concept_id))

    # --- size checks --------------------------------------------------------
    if resolved is not None:
        for name, ids in resolved.items():
            if name in spec.entry_concept_sets and not ids:
                issues.append(Issue("error", "entry_set_resolves_empty",
                                    "entry concept set resolves to no concepts",
                                    concept_set=name))
            elif not ids:
                issues.append(Issue("warning", "set_resolves_empty",
                                    "concept set resolves to no concepts",
                                    concept_set=name))
            elif len(ids) > BROAD_THRESHOLD:
                issues.append(Issue(
                    "warning", "very_broad_set",
                    f"resolves to {len(ids):,} concepts; check that including "
                    "descendants is intended", concept_set=name))

        for entry_name in spec.entry_concept_sets:
            cs = spec.concept_sets.get(entry_name)
            if cs and len(resolved.get(entry_name, set())) == 1:
                descendants_requested = any(
                    i.include_descendants for i in cs.items
                    if not i.is_excluded
                )
                if descendants_requested:
                    message = (
                        "descendants requested but only one concept resolved"
                    )
                else:
                    message = (
                        "only one concept resolved and descendants were not "
                        "requested; check whether the entry set is too narrow"
                    )
                issues.append(Issue(
                    "warning", "possibly_too_narrow", message,
                    concept_set=entry_name))
                if not descendants_requested:
                    issues.append(Issue(
                        "warning", "entry_single_concept_no_descendants",
                        "entry set resolves to one concept without descendants; "
                        "check get_descendants to confirm whether broader coverage "
                        "is intended",
                        concept_set=entry_name))

    return ValidationResult(issues)


def validate_execution(cohort_size: int) -> ValidationResult:
    """Post-execution check, kept separate because it needs a result."""
    if cohort_size == 0:
        return ValidationResult([Issue(
            "warning", "empty_cohort",
            "the cohort matched no patients in this dataset; this may be "
            "correct if the condition is absent from the data")])
    return ValidationResult([])
