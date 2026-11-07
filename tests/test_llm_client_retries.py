import pytest

from src.llm import client as llm_client


def test_local_ollama_timeout_has_one_bounded_retry(monkeypatch):
    monkeypatch.setenv("A_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("A_API_KEY", "local")
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise llm_client.APIError("request timed out", status=408)

    monkeypatch.setattr(llm_client, "_post", timeout)
    client = llm_client.HTTPClient("A")

    with pytest.raises(llm_client.APIError, match="request timed out"):
        client.complete("system", [{"role": "user", "content": "hi"}], "local")

    assert len(calls) == 2


def test_hosted_retry_policy_remains_five_attempts(monkeypatch):
    monkeypatch.setenv("A_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("A_API_KEY", "test")
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise llm_client.APIError("request timed out", status=408)

    monkeypatch.setattr(llm_client, "_post", timeout)
    client = llm_client.HTTPClient("A")

    with pytest.raises(llm_client.APIError, match="request timed out"):
        client.complete("system", [{"role": "user", "content": "hi"}], "remote")

    assert len(calls) == 5


def test_local_ollama_context_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("A_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("A_API_KEY", "local")
    monkeypatch.setenv("A_OLLAMA_NUM_CTX", "4096")
    client = llm_client.HTTPClient("A")
    _, _, payload = client._build("system", [], "local", 100)
    assert payload["options"]["num_ctx"] == 4096
    monkeypatch.setenv("A_OLLAMA_NUM_CTX", "100000")
    with pytest.raises(llm_client.APIError, match="A_OLLAMA_NUM_CTX"):
        client._build("system", [], "local", 100)
