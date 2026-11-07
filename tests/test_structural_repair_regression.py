"""Regression tests for structural cohort-specification repair.

These tests intentionally establish the desired repair contract before the
Builder implementation is changed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schema.spec import CohortSpec


def base_spec_data():
    return {
        "question": "Adults with osteoarthritis",
        "entry_concept_set": "osteoarthritis",
        "entry_concept_sets": ["osteoarthritis"],
        "entry_arms": [
            {"concept_set": "osteoarthritis", "event_domain": "Condition"}
        ],
        "concept_sets": {
            "osteoarthritis": {
                "name": "osteoarthritis",
                "domain": "Condition",
                "description": "Osteoarthritis diagnoses",
                "items": [],
            },
            "nsaid": {
                "name": "nsaid",
                "domain": "Drug",
                "description": "NSAID exposure",
                "items": [],
            },
        },
        "criteria": [
            {
                "concept_set": "nsaid",
                "window_start_days": -365,
                "window_end_days": 0,
                "rule": "at_least_one",
            }
        ],
    }


def test_valid_multi_entry_spec_preserves_all_references():
    spec = CohortSpec(**base_spec_data())

    assert spec.entry_concept_set == "osteoarthritis"
    assert spec.entry_concept_sets == ["osteoarthritis"]
    assert spec.entry_arms[0].concept_set == "osteoarthritis"
    assert spec.criteria[0].concept_set == "nsaid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("entry_concept_sets", ["osteoarthritis_entry"]),
        ("entry_arms", [
            {"concept_set": "osteoarthritis_entry", "event_domain": "Condition"}
        ]),
        ("criteria", [
            {
                "concept_set": "missing_set",
                "window_start_days": -365,
                "window_end_days": 0,
                "rule": "at_least_one",
            }
        ]),
    ],
)
def test_spec_rejects_unresolved_structural_references(field, value):
    data = base_spec_data()
    data[field] = value

    with pytest.raises(ValidationError):
        CohortSpec(**data)


def test_valid_multi_arm_spec_accepts_distinct_event_domains():
    data = base_spec_data()
    data["concept_sets"]["osteoarthritis_drug"] = {
        "name": "osteoarthritis_drug",
        "domain": "Drug",
        "description": "Medication used for osteoarthritis",
        "items": [],
    }
    data["entry_concept_sets"] = [
        "osteoarthritis",
        "osteoarthritis_drug",
    ]
    data["entry_arms"] = [
        {"concept_set": "osteoarthritis", "event_domain": "Condition"},
        {"concept_set": "osteoarthritis_drug", "event_domain": "Drug"},
    ]

    spec = CohortSpec(**data)

    assert {
        (arm.concept_set, arm.event_domain) for arm in spec.entry_arms
    } == {
        ("osteoarthritis", "Condition"),
        ("osteoarthritis_drug", "Drug"),
    }


def test_planner_normalizes_unambiguous_entry_suffixes():
    from src.schema.spec import PlannerOutput

    data = base_spec_data()
    data["entry_concept_set"] = "osteoarthritis_entry"
    data["entry_concept_sets"] = ["osteoarthritis_entry"]
    data["entry_arms"] = [
        {"concept_set": "osteoarthritis_entry", "event_domain": "Condition"}
    ]
    data["criteria"][0]["concept_set"] = "nsaid_entry"

    spec = PlannerOutput(**data).to_spec()

    assert spec.entry_concept_set == "osteoarthritis"
    assert spec.entry_concept_sets == ["osteoarthritis"]
    assert spec.entry_arms[0].concept_set == "osteoarthritis"
    assert spec.criteria[0].concept_set == "nsaid"


def test_planner_preserves_exact_names_and_rejects_missing_references():
    from pydantic import ValidationError
    from src.schema.spec import PlannerOutput

    data = base_spec_data()
    data["entry_concept_set"] = "osteoarthritis"
    data["entry_concept_sets"] = ["osteoarthritis"]
    data["entry_arms"] = [
        {"concept_set": "osteoarthritis", "event_domain": "Condition"}
    ]
    data["criteria"][0]["concept_set"] = "genuinely_missing_set"

    with pytest.raises(ValidationError):
        PlannerOutput(**data).to_spec()


def test_planner_does_not_guess_ambiguous_names():
    from pydantic import ValidationError
    from src.schema.spec import PlannerOutput

    data = base_spec_data()
    data["concept_sets"]["osteoarthritis_entry"] = {
        "name": "osteoarthritis_entry",
        "domain": "Condition",
        "description": "A distinct entry concept set",
        "items": [],
    }
    data["entry_concept_set"] = "osteoarthritis-entry"
    data["entry_concept_sets"] = ["osteoarthritis-entry"]
    data["entry_arms"] = [
        {"concept_set": "osteoarthritis-entry", "event_domain": "Condition"}
    ]

    with pytest.raises(ValidationError):
        PlannerOutput(**data).to_spec()
