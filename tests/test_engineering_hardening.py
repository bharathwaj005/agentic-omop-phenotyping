from types import SimpleNamespace

import json

import pytest

from scripts import run_benchmark
from scripts.recover_v53_failed import (
    append_attempt_journal,
    load_attempt_journal,
    load_checkpoint,
    recovery_status,
    validate_run_id_selection,
)
from src.llm.client import APIError, model_for
from src.pipelines.budget import Budget
from src.runner.experiment import C1, C2, _resolve_model_aliases


def test_multi_agent_model_tiers_resolve_and_explicit_ids_pass_through(monkeypatch):
    resolved = {
        "small": "configured-small",
        "strong": "configured-strong",
    }
    monkeypatch.setattr(
        "src.runner.experiment.model_for",
        lambda provider, tier: resolved[tier],
    )

    models = _resolve_model_aliases(
        {"planner": "qwen3:4b", "concept": "small"}, C1
    )

    assert models == {
        "planner": "qwen3:4b",
        "concept": "configured-small",
        "builder": "configured-small",
        "critic": "configured-strong",
    }


def test_single_agent_model_tier_resolves_and_explicit_id_passes_through(monkeypatch):
    monkeypatch.setattr(
        "src.runner.experiment.model_for",
        lambda provider, tier: f"configured-{tier}",
    )

    assert _resolve_model_aliases(None, C2)["single_agent"] == "configured-strong"
    assert _resolve_model_aliases({"single_agent": "jbi-qwen:3b"}, C2)[
        "single_agent"
    ] == "jbi-qwen:3b"


def test_missing_model_tier_fails_before_pipeline_start(monkeypatch):
    def missing(provider, tier):
        raise RuntimeError(f"{provider}_{tier} is not configured")

    monkeypatch.setattr("src.runner.experiment.model_for", missing)
    with pytest.raises(RuntimeError, match="A_strong is not configured"):
        _resolve_model_aliases(None, C1)


def test_explicit_recovery_run_id_must_match_one_failed_queue_row():
    queue = [
        {"run_id": "T01_C1", "status": "FAILED"},
        {"run_id": "T01_C2", "status": "SUCCESS"},
    ]

    validate_run_id_selection(queue, "T01_C1")
    with pytest.raises(ValueError, match="unknown queue run ID"):
        validate_run_id_selection(queue, "T99_C1")
    with pytest.raises(ValueError, match="not failed"):
        validate_run_id_selection(queue, "T01_C2")


def test_duplicate_recovery_run_id_is_rejected():
    queue = [
        {"run_id": "T01_C1", "status": "FAILED"},
        {"run_id": "T01_C1", "status": "FAILED"},
    ]
    with pytest.raises(ValueError, match="not unique"):
        validate_run_id_selection(queue, "T01_C1")


def test_missing_recovery_checkpoint_is_empty_state(tmp_path):
    assert load_checkpoint(tmp_path / "missing.json") == {}


def test_append_after_truncated_jsonl_preserves_next_record(tmp_path):
    journal = tmp_path / "attempts.jsonl"
    journal.write_bytes(b'{"run_id":"partial"')

    append_attempt_journal(journal, {"run_id": "T01_C1", "status": "failed"})
    rows, issues = load_attempt_journal(journal)

    assert len(issues) == 1
    assert rows == [{"run_id": "T01_C1", "status": "failed"}]
    assert journal.read_bytes().startswith(b'{"run_id":"partial"\n')


def test_recovery_preserves_timeout_as_terminal_status():
    assert recovery_status("timeout") == "timeout"
    assert recovery_status("success") == "success"
    assert recovery_status("unexpected") == "failed"


def test_model_registry_rejects_explicit_ids_as_tier_names(monkeypatch):
    monkeypatch.setenv("A_MODEL_QWEN3:4B", "must-not-be-used")
    with pytest.raises(APIError, match="unknown model tier"):
        model_for("A", "qwen3:4b")


def test_endpoint_preflight_does_not_accept_a_different_model_tag(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"models":[{"name":"qwen2.5:3b"}]}'

    monkeypatch.setattr(run_benchmark.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="requested model is not present"):
        run_benchmark._endpoint_preflight(
            "http://127.0.0.1:11434/v1", "qwen2.5"
        )


def test_endpoint_preflight_accepts_only_requested_tag_or_implicit_latest(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"models":[{"name":"qwen2.5:latest","digest":"abc123","size":42}]}'

    monkeypatch.setattr(run_benchmark.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response())
    identity = run_benchmark._endpoint_preflight(
        "http://127.0.0.1:11434/v1", "qwen2.5"
    )
    assert identity["resolved_tag"] == "qwen2.5:latest"
    assert identity["digest"] == "abc123"


@pytest.mark.parametrize("spec", [None, {}])
def test_benchmark_runner_downgrades_success_without_valid_spec(
    tmp_path, monkeypatch, spec
):
    monkeypatch.setattr(
        run_benchmark, "_reference",
        lambda *args: {"all_concept_ids": [], "entry_concept_ids": []},
    )
    monkeypatch.setattr(
        run_benchmark, "run_single_agent",
        lambda *args, **kwargs: SimpleNamespace(
            status="success", reason=None, spec=spec, resolved={}, tracker=None,
            execution=None,
        ),
    )

    report = run_benchmark._run_one(
        {"task_id": "T01", "question": "synthetic"}, "C2", "134", "v53",
        "synthetic-model", tmp_path / "T01_C2", object(), object(), Budget(),
    )

    assert report["status"] == "failed"
    assert "specification" in report["reason"]
    trace = json.loads((tmp_path / "T01_C2/trace.json").read_text())
    assert trace["status"] == "failed"


def test_preflight_enforces_memory_and_disk_limits():
    minimum_memory = run_benchmark.MIN_AVAILABLE_MEMORY_BYTES
    minimum_disk = run_benchmark.MIN_FREE_DISK_BYTES
    run_benchmark._check_resource_limits(minimum_memory, minimum_disk + 1)

    with pytest.raises(RuntimeError, match="available memory"):
        run_benchmark._check_resource_limits(minimum_memory - 1, minimum_disk + 1)
    with pytest.raises(RuntimeError, match="free disk"):
        run_benchmark._check_resource_limits(minimum_memory, minimum_disk)


@pytest.mark.parametrize("deadline", [None, "nan", "0", "3601"])
def test_preflight_requires_a_positive_bounded_total_deadline(
    tmp_path, monkeypatch, deadline
):
    if deadline is None:
        monkeypatch.delenv("JBI_RUN_DEADLINE_S", raising=False)
    else:
        monkeypatch.setenv("JBI_RUN_DEADLINE_S", deadline)

    with pytest.raises(RuntimeError, match="JBI_RUN_DEADLINE_S"):
        run_benchmark._preflight(
            SimpleNamespace(track="v53", model="exact-model"),
            tmp_path / "new-run", tmp_path / "freeze_manifest.json",
        )


def test_live_preflight_refuses_fake_client_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("JBI_RUN_DEADLINE_S", "1800")
    monkeypatch.setenv("USE_FAKE_LLM", "1")
    monkeypatch.setattr(
        run_benchmark.urllib.request, "urlopen",
        lambda *args, **kwargs: pytest.fail("preflight must stop before network access"),
    )

    with pytest.raises(RuntimeError, match="USE_FAKE_LLM=1"):
        run_benchmark._preflight(
            SimpleNamespace(track="v53", model="exact-model"),
            tmp_path / "new-run", tmp_path / "freeze_manifest.json",
        )


def test_question_selection_rejects_partial_match_of_explicit_task_ids(tmp_path):
    question_file = tmp_path / "questions.jsonl"
    question_file.write_text(
        '{"task_id":"T01","question":"one"}\n'
        '{"task_id":"T02","question":"two"}\n'
    )

    with pytest.raises(ValueError, match="T99"):
        run_benchmark._load_questions(
            question_file, "v53", {"T01", "T99"}
        )
    with pytest.raises(ValueError, match="no v53 questions selected"):
        run_benchmark._load_questions(question_file, "v53", set())

    selected = run_benchmark._load_questions(
        question_file, "v53", {"T02"}
    )
    assert [row["task_id"] for row in selected] == ["T02"]


def test_explicit_empty_configuration_selection_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(run_benchmark, "RUNS_ROOT", tmp_path / "runs")
    question_file = tmp_path / "questions.jsonl"
    question_file.write_text('{"task_id":"T01","question":"synthetic"}\n')

    with pytest.raises(ValueError, match="configs must be selected"):
        run_benchmark.run_benchmark(
            "v53", question_file, "model", tmp_path / "runs/empty-configs",
            configs=[], tasks={"T01"}, preflight=False,
        )


def test_benchmark_checkpoint_replace_failure_preserves_previous_file(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text('{"status":"success"}\n')

    def fail_replace(source, destination):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(run_benchmark.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        run_benchmark._atomic_json(checkpoint, {"status": "failed"})

    assert json.loads(checkpoint.read_text()) == {"status": "success"}
    assert list(tmp_path.glob(".checkpoint.json.*.tmp")) == []
