import time

import pytest

from src.llm import client as llm_client
from src.pipelines.deadline import RunDeadlineExceeded


def test_http_request_timeout_is_bounded_by_run_deadline(monkeypatch):
    monkeypatch.setenv("A_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("A_API_KEY", "fake-key")
    client = llm_client.HTTPClient("A")
    client.run_deadline_at = time.monotonic() + 10
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": "ok"},
                             "finish_reason": "stop"}]}

    monkeypatch.setattr(llm_client, "_post", fake_post)
    client.complete("system", [], "test-model")
    assert 0 < seen["timeout"] <= 10


def test_expired_http_deadline_stops_before_request(monkeypatch):
    monkeypatch.setenv("A_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("A_API_KEY", "fake-key")
    client = llm_client.HTTPClient("A")
    client.run_deadline_at = time.monotonic() - 1
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(llm_client, "_post", fake_post)
    with pytest.raises(RunDeadlineExceeded):
        client.complete("system", [], "test-model")
    assert not called
