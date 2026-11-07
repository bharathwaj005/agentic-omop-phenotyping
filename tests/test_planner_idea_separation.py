"""Deterministic contracts for preserving distinct planner ideas."""

from src.agents.base import load_prompt
from src.pipelines import multi_agent
from src.schema.spec import ConceptItem, PlannerOutput


def test_planner_prompt_separates_alternative_evidence_routes():
    prompt, _ = load_prompt("planner")

    assert "Alternative eligibility routes are distinct ideas" in prompt
    assert "diagnosis OR medication treatment" in prompt
    assert "separate diagnosis and medication" in prompt


def test_planner_output_keeps_diagnosis_and_treatment_sets_separate():
    # Fixed planner payload: this exercises deterministic parsing/conversion,
    # not a claim about what a live model will return.
    payload = {
        "entry_concept_set": "diagnosis",
        "entry_concept_sets": ["diagnosis", "medication_treatment"],
        "entry_arms": [
            {"concept_set": "diagnosis", "event_domain": "Condition"},
            {"concept_set": "medication_treatment", "event_domain": "Drug"},
        ],
        "concept_sets": {
            "diagnosis": {
                "name": "diagnosis",
                "domain": "Condition",
                "description": "Diagnosis evidence for the target condition",
                "items": [],
            },
            "medication_treatment": {
                "name": "medication_treatment",
                "domain": "Drug",
                "description": "Medication treatment evidence for the target condition",
                "items": [],
            },
        },
    }

    spec = PlannerOutput(**payload).to_spec(
        question="Diagnosis or medication treatment for a target condition"
    )

    assert list(spec.concept_sets) == ["diagnosis", "medication_treatment"]
    assert spec.entry_concept_sets == ["diagnosis", "medication_treatment"]
    assert [(arm.concept_set, arm.event_domain) for arm in spec.entry_arms] == [
        ("diagnosis", "Condition"),
        ("medication_treatment", "Drug"),
    ]


def test_multi_agent_pipeline_fills_both_fixed_planner_sets(monkeypatch):
    payload = {
        "entry_concept_set": "diagnosis",
        "entry_concept_sets": ["diagnosis", "medication_treatment"],
        "entry_arms": [
            {"concept_set": "diagnosis", "event_domain": "Condition"},
            {"concept_set": "medication_treatment", "event_domain": "Drug"},
        ],
        "concept_sets": {
            "diagnosis": {
                "name": "diagnosis",
                "domain": "Condition",
                "description": "Diagnosis evidence for the target condition",
                "items": [],
            },
            "medication_treatment": {
                "name": "medication_treatment",
                "domain": "Drug",
                "description": "Medication treatment evidence for the target condition",
                "items": [],
            },
        },
    }
    fixed_spec = PlannerOutput(**payload).to_spec()
    filled = []

    monkeypatch.setattr(multi_agent, "plan", lambda *_args, **_kwargs: fixed_spec)

    def fixed_fill(_client, _model, _vocab, concept_set, *_args, **_kwargs):
        filled.append(concept_set.name)
        concept_id = 11 if concept_set.name == "diagnosis" else 22
        return [ConceptItem(
            concept_id=concept_id,
            rationale=f"Fixed mocked item for {concept_set.name}",
        )]

    monkeypatch.setattr(multi_agent, "fill_concept_set", fixed_fill)
    monkeypatch.setattr(
        multi_agent,
        "_resolve_all",
        lambda _vocab, _spec: {
            "diagnosis": {11},
            "medication_treatment": {22},
        },
    )

    result = multi_agent.run_multi_agent(
        client=object(),
        models={"planner": "fixed", "concept": "fixed",
                "builder": "fixed", "critic": "fixed"},
        question="Diagnosis or medication treatment for a target condition",
        vocab_con=object(),
        use_critic=False,
        use_validator=False,
    )

    assert result.status == "success"
    assert filled == ["diagnosis", "medication_treatment"]
    assert result.resolved == {"diagnosis": {11}, "medication_treatment": {22}}
