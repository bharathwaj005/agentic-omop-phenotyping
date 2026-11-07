from types import SimpleNamespace

from src.runner import experiment
from src.runner.experiment import C1, run_experiment


def test_reference_payload_is_not_passed_to_generation_pipeline(monkeypatch):
    class Task:
        task_id = "T01"
        question = "Find patients with the blinded phenotype."

    sentinel = {"private_gold_concept_ids": [123, 456]}
    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            status="success", reason=None, resolved={}, spec=None, tracker=None,
            execution=None, critic_rounds=0, validator_retries=0, unresolved=[],
        )

    monkeypatch.setattr(experiment, "run_multi_agent", fake_pipeline)
    result = run_experiment(
        [Task()], [C1], client=object(), vocab_con=object(),
        reference_loader=lambda _task_id: sentinel,
    )

    assert "reference" not in captured
    assert sentinel not in captured.values()
    assert result.records[0].metadata["reference_supplied"] is True
