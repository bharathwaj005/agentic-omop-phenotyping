import json
import time
from types import SimpleNamespace

from src.metrics.evaluation import RunRecord
from src.runner import experiment


class Task:
    task_id = "T01"
    question = "synthetic question"


def test_deadline_marks_active_and_unstarted_slots_and_saves_trace(tmp_path, monkeypatch):
    trace_path = tmp_path / "trace.json"

    class Log:
        final_spec = None
        extra = {}

        def finish(self, status, final_spec=None, error=None):
            trace_path.write_text(json.dumps({"status": status, "error": error,
                                              "checkpoint": self.extra.get("checkpoint")}))

    calls = 0

    def slow_pipeline(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(0.03)
        return SimpleNamespace(status="success", reason=None, tracker=None,
                               execution=None, spec=None, resolved={})

    monkeypatch.setenv("JBI_RUN_DEADLINE_S", "0.01")
    monkeypatch.setattr(experiment, "run_single_agent", slow_pipeline)
    result = experiment.run_experiment(
        [Task(), SimpleNamespace(task_id="T02", question="later")],
        [experiment.C2], client=object(), vocab_con=object(),
        log_factory=lambda **kwargs: Log())

    assert [r.status for r in result.records] == ["timeout", "success"]
    assert json.loads(trace_path.read_text())["status"] == "timeout"
    assert json.loads(trace_path.read_text())["checkpoint"]["status"] == "timeout"


def test_no_deadline_preserves_injected_runner_behavior(monkeypatch):
    monkeypatch.delenv("JBI_RUN_DEADLINE_S", raising=False)

    def runner(*, task, configuration, reference):
        return RunRecord(task_id=task.task_id, configuration=configuration.name,
                         status="success")

    result = experiment.run_experiment([Task()], [experiment.C2], runner)
    assert len(result.records) == 1
    assert result.records[0].status == "success"
