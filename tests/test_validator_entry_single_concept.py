from src.schema.spec import CohortSpec, ConceptItem, ConceptSet
from src.tools.validator import validate


def _spec(items, entry=True):
    if not entry:
        return CohortSpec(
            question="synthetic question",
            concept_sets={
                "entry": ConceptSet(name="entry", domain="Condition", description="entry",
                                    items=[ConceptItem(concept_id=9, rationale="entry")]),
                "set": ConceptSet(name="set", domain="Condition", description="test", items=items),
            },
            entry_concept_sets=["entry"],
        )
    return CohortSpec(
        question="synthetic question",
        concept_sets={"set": ConceptSet(name="set", domain="Condition", description="test", items=items)},
        entry_concept_sets=["set"] if entry else [],
    )


def _warning(spec, resolved):
    return [i for i in validate(spec, resolved=resolved).warnings
            if i.code == "entry_single_concept_no_descendants"]


def test_warns_for_single_concept_entry_without_descendants():
    assert len(_warning(_spec([ConceptItem(concept_id=1, rationale="test", include_descendants=False)]), {"set": {1}})) == 1


def test_does_not_warn_when_descendants_requested():
    assert not _warning(_spec([ConceptItem(concept_id=1, rationale="test", include_descendants=True)]),
                        {"set": {1}})


def test_does_not_warn_for_multiple_resolved_concepts():
    assert not _warning(_spec([ConceptItem(concept_id=1, rationale="test", include_descendants=False)]), {"set": {1, 2}})


def test_does_not_warn_for_non_entry_set():
    assert not _warning(_spec([ConceptItem(concept_id=1, rationale="test", include_descendants=False)], entry=False),
                        {"entry": {9}, "set": {1}})
