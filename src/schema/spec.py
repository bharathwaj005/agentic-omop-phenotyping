"""The executable cohort specification.

This is the paper's core artifact: the structured, versioned representation that
every agent reads and writes, and that the compiler turns into SQL. Keeping it
small and explicit is deliberate -- an agent cannot drift into vague prose, and
a human can audit every field.

Versioned so later work can extend it (nested criteria, temporal logic,
measurement domains) without breaking this reference implementation.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SPEC_VERSION = "1.1"

# Vocabulary domains describe OMOP concept metadata.
VocabularyDomain = Literal[
    "Condition", "Drug", "Procedure", "Measurement",
    "Observation", "Visit", "Device", "Demographic",
    "Metadata", "Specimen", "Episode", "Provider", "Location",
]

# Event domains select the OMOP table used to find cohort entry events.
EventDomain = Literal[
    "Condition", "Drug", "Procedure", "Measurement",
    "Observation", "Visit", "Device",
]

# ConceptSet.domain selects a compiler-supported OMOP event table.
# Keep Domain as an alias for compatibility with existing imports.
Domain = EventDomain

Rule = Literal["at_least_one", "none"]


class ConceptItem(BaseModel):
    """One concept in a concept set, with the agent's reason for including it."""

    concept_id: int
    include_descendants: bool = True
    is_excluded: bool = False
    rationale: str = Field(
        ...,
        min_length=3,
        description="Why this concept belongs. Required: this is the audit trail.",
    )

    @field_validator("concept_id")
    @classmethod
    def positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("concept_id must be a positive integer")
        return v


class ConceptSet(BaseModel):
    """A named set of concepts. The Planner writes name+description+domain;
    the Concept Agent fills in items."""

    name: str = Field(..., min_length=1)
    domain: Domain
    description: str = Field(
        ..., min_length=3,
        description="Clinical meaning in plain language, written by the Planner.",
    )
    items: list[ConceptItem] = Field(default_factory=list)

    def is_filled(self) -> bool:
        return any(not i.is_excluded for i in self.items)


class Criterion(BaseModel):
    """An inclusion or exclusion rule relative to the index date.

    Windows are in days relative to index: -365 to 0 means the year before.
    """

    concept_set: str
    window_start_days: int = -365
    window_end_days: int = 0
    rule: Rule = "at_least_one"

    @model_validator(mode="after")
    def window_ordered(self) -> "Criterion":
        if self.window_start_days > self.window_end_days:
            raise ValueError(
                f"window_start_days ({self.window_start_days}) must be <= "
                f"window_end_days ({self.window_end_days})"
            )
        return self


class EntryArm(BaseModel):
    """One OR arm: a concept set matched against a specific OMOP event domain."""

    concept_set: str = Field(..., min_length=1)
    event_domain: EventDomain


class CohortSpec(BaseModel):
    """A complete, executable cohort definition."""

    spec_version: str = SPEC_VERSION
    question: str = ""
    # Legacy singular field retained for existing specs and callers.
    entry_concept_set: Optional[str] = None
    # All entry sets are combined with OR semantics across their domains.
    entry_concept_sets: list[str] = Field(default_factory=list)
    # Explicit event-table arms; empty legacy specs normalize from concept-set domains.
    entry_arms: list[EntryArm] = Field(default_factory=list)
    first_occurrence_only: bool = True
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    prior_observation_days: int = 0
    criteria: list[Criterion] = Field(default_factory=list)
    concept_sets: dict[str, ConceptSet] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references_resolve(self) -> "CohortSpec":
        names = set(self.concept_sets)

        # Normalize legacy singular-entry specifications.
        if not self.entry_concept_sets and self.entry_concept_set:
            self.entry_concept_sets = [self.entry_concept_set]

        # Explicit arms may be the source of entry-set names.
        if not self.entry_concept_sets and self.entry_arms:
            self.entry_concept_sets = list(dict.fromkeys(
                arm.concept_set for arm in self.entry_arms
            ))

        if not self.entry_concept_sets:
            raise ValueError("at least one entry_concept_set(s) is required")

        unknown = [n for n in self.entry_concept_sets if n not in names]
        if unknown:
            raise ValueError(
                f"entry_concept_sets {unknown!r} are not in concept_sets "
                f"{sorted(names)}"
            )

        if len(set(self.entry_concept_sets)) != len(self.entry_concept_sets):
            raise ValueError("entry_concept_sets must not contain duplicates")

        # Legacy specs become one arm per entry set, using the set's domain.
        if not self.entry_arms:
            self.entry_arms = [
                EntryArm(concept_set=n, event_domain=self.concept_sets[n].domain)
                for n in self.entry_concept_sets
            ]

        arm_unknown = [
            arm.concept_set for arm in self.entry_arms
            if arm.concept_set not in names
        ]
        if arm_unknown:
            raise ValueError(
                f"entry arms reference unknown concept sets: {arm_unknown!r}"
            )

        arm_names = list(dict.fromkeys(arm.concept_set for arm in self.entry_arms))
        if set(arm_names) != set(self.entry_concept_sets):
            raise ValueError(
                "entry_concept_sets must exactly match the concept sets referenced "
                "by entry_arms"
            )

        arm_pairs = [(a.concept_set, a.event_domain) for a in self.entry_arms]
        if len(arm_pairs) != len(set(arm_pairs)):
            raise ValueError("duplicate (concept_set, event_domain) entry arms")

        if self.entry_concept_set is None:
            self.entry_concept_set = self.entry_concept_sets[0]
        if self.entry_concept_set not in self.entry_concept_sets:
            raise ValueError(
                "legacy entry_concept_set must match one of entry_concept_sets"
            )

        for c in self.criteria:
            if c.concept_set not in names:
                raise ValueError(
                    f"criterion references unknown concept set {c.concept_set!r}"
                )
        if self.age_min is not None and self.age_max is not None \
                and self.age_min > self.age_max:
            raise ValueError("age_min must be <= age_max")
        if self.prior_observation_days < 0:
            raise ValueError("prior_observation_days must be >= 0")
        return self

    # --- convenience -------------------------------------------------------

    @property
    def entry_sets(self) -> list[ConceptSet]:
        """Entry concept sets, in declared order; all are OR-ed by the compiler."""
        return [self.concept_sets[n] for n in self.entry_concept_sets]

    @property
    def entry_set(self) -> ConceptSet:
        """Legacy convenience: the first entry arm."""
        return self.entry_sets[0]

    @property
    def entry_domain(self) -> EventDomain:
        """Legacy convenience: event domain of the first entry arm."""
        return self.entry_arms[0].event_domain

    def unfilled_sets(self) -> list[str]:
        """Concept sets the Concept Agent still has to populate."""
        return [n for n, cs in self.concept_sets.items() if not cs.is_filled()]

    def all_concept_ids(self) -> set[int]:
        return {i.concept_id for cs in self.concept_sets.values()
                for i in cs.items if not i.is_excluded}

    def summary(self) -> str:
        """Compact human-readable form, used in Critic prompts (token-cheap)."""
        entry_summary = " OR ".join(
            f"{arm.concept_set} ({arm.event_domain})"
            for arm in self.entry_arms
        )
        lines = [
            f"entry OR arms: {entry_summary}",
            f"first_occurrence_only: {self.first_occurrence_only}",
            f"age: {self.age_min}-{self.age_max}",
            f"prior_observation_days: {self.prior_observation_days}",
        ]
        for name, cs in self.concept_sets.items():
            inc = sum(1 for i in cs.items if not i.is_excluded)
            exc = sum(1 for i in cs.items if i.is_excluded)
            lines.append(f"set {name} [{cs.domain}] include={inc} exclude={exc}"
                         f" :: {cs.description}")
        for c in self.criteria:
            lines.append(f"criterion {c.rule} {c.concept_set} "
                         f"[{c.window_start_days},{c.window_end_days}]")
        return "\n".join(lines)


# --- Planner output: a spec with empty concept sets -------------------------

class PlannerOutput(BaseModel):
    """What the Planner returns: structure and clinical descriptions, NO ids."""

    # New planners should return entry_concept_sets; singular remains accepted.
    entry_concept_set: Optional[str] = None
    entry_concept_sets: list[str] = Field(default_factory=list)
    # Explicit event-table mappings; legacy outputs normalize in CohortSpec.
    entry_arms: list[EntryArm] = Field(default_factory=list)
    first_occurrence_only: bool = True
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    prior_observation_days: int = 0
    criteria: list[Criterion] = Field(default_factory=list)
    concept_sets: dict[str, ConceptSet] = Field(default_factory=dict)

    def to_spec(self, question: str = "") -> CohortSpec:
        """Resolve unambiguous planner reference-name mismatches."""
        import re

        data = self.model_dump()
        keys = list(data["concept_sets"])

        def canonical(value: str) -> str:
            value = re.sub(r"[-_ ]+entry$", "", value.strip(),
                           flags=re.IGNORECASE)
            return re.sub(r"[^a-z0-9]", "", value.lower())

        def resolve_reference(value: str) -> str:
            if value in data["concept_sets"]:
                return value
            target = canonical(value)
            matches = [key for key in keys if canonical(key) == target]
            if len(matches) == 1:
                return matches[0]
            # Leave unresolved references untouched. CohortSpec will reject
            # missing references; ambiguous references must never be guessed.
            return value

        if data.get("entry_concept_set"):
            data["entry_concept_set"] = resolve_reference(
                data["entry_concept_set"]
            )

        data["entry_concept_sets"] = [
            resolve_reference(name)
            for name in data.get("entry_concept_sets", [])
        ]

        for arm in data.get("entry_arms", []):
            arm["concept_set"] = resolve_reference(arm["concept_set"])

        for criterion in data.get("criteria", []):
            criterion["concept_set"] = resolve_reference(
                criterion["concept_set"]
            )

        return CohortSpec(question=question, **data)


# --- Critic output ----------------------------------------------------------

class CriticIssue(BaseModel):
    target: str = Field(..., description="Concept set name, or 'builder'")
    problem: str
    suggestion: str

    @field_validator("target", "problem", "suggestion")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("critic issue fields must not be blank")
        return value


class CriticOutput(BaseModel):
    verdict: Literal["accept", "revise"]
    issues: list[CriticIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def revise_needs_issues(self) -> "CriticOutput":
        if self.verdict == "revise" and not self.issues:
            raise ValueError("verdict 'revise' requires at least one issue")
        return self


if __name__ == "__main__":
    demo = CohortSpec(
        question="Adults with a first diagnosis of peptic ulcer, "
                 "with one year of prior observation.",
        entry_concept_set="peptic_ulcer",
        age_min=18,
        prior_observation_days=365,
        concept_sets={
            "peptic_ulcer": ConceptSet(
                name="peptic_ulcer", domain="Condition",
                description="Peptic ulcer disease of stomach or duodenum",
                items=[ConceptItem(concept_id=4027663, include_descendants=True,
                                   rationale="Peptic ulcer, covers subtypes")],
            )
        },
    )
    print(demo.summary())
    print("\nunfilled:", demo.unfilled_sets())
    print("concept ids:", demo.all_concept_ids())
