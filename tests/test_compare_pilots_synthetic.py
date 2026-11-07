from scripts.compare_pilots import compare


def test_pilot_comparison_and_deadline_suggestion_are_synthetic():
    reports = [{
        "configuration": "C2", "status": "success", "model_requested": "fake",
        "wall_seconds": 45.3, "llm_calls": 2, "tool_calls": 1,
        "input_tokens": 10, "output_tokens": 5,
        "entry_arms": [{"event_domain": "Drug"}],
        "final_spec": {"concept_sets": {"x": {"items": [
            {"include_descendants": True}]}}},
        "metrics": {"v2": {"full": {"precision": 0.8, "recall": 0.7},
                             "entry": {"precision": 0.9, "recall": 0.6}}},
    }]
    rows, suggestion = compare(reports)
    assert rows[0]["has_drug_arm"] is True
    assert rows[0]["any_include_descendants"] is True
    assert rows[0]["entry_recall_v2"] == 0.6
    assert suggestion == 180
