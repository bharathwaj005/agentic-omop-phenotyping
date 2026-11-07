"""Regression checks for unsupported demographic filters and prompt coverage."""

from src.agents.base import PROMPT_DIR
from src.schema.spec import CohortSpec, ConceptItem, ConceptSet
from src.tools.validator import validate


def _spec(question: str, *, age_min=None, age_max=None) -> CohortSpec:
    return CohortSpec(
        question=question,
        entry_concept_set="condition",
        age_min=age_min,
        age_max=age_max,
        concept_sets={
            "condition": ConceptSet(
                name="condition",
                domain="Condition",
                description="The target condition",
                items=[ConceptItem(concept_id=1, rationale="Target condition")],
            )
        },
    )


def test_validator_blocks_age_filter_without_explicit_population_scope():
    result = validate(_spec("Identify patients with asthma", age_min=18))
    assert any(issue.code == "age_filter_not_in_question" for issue in result.errors)


def test_validator_allows_age_filter_when_question_states_adult_population():
    result = validate(_spec("Identify adults with asthma", age_min=18))
    assert not any(issue.code == "age_filter_not_in_question" for issue in result.issues)


def test_validator_does_not_require_age_filter_when_question_has_no_age_scope():
    result = validate(_spec("Identify patients with asthma"))
    assert not any(issue.code == "age_filter_not_in_question" for issue in result.issues)


def test_single_agent_prompt_audits_disjunctions_and_age_scope():
    prompt = (PROMPT_DIR / "single_agent.md").read_text(encoding="utf-8")
    assert "preserve its AND/OR relationship" in prompt
    assert "clinically distinct branch joined by \"or\"" in prompt
    assert "Do not infer adulthood" in prompt
