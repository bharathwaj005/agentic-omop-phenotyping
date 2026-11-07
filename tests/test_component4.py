"""Component 4 tests: the LLM client.

The HTTP layer is stubbed, so these run offline and cost nothing. What is being
tested is the part that actually breaks in practice: retry behaviour on rate
limits, token accounting, and correct parsing of both wire formats.

Run:  python -m tests.test_component4
"""

from __future__ import annotations

import os
import sys

from src.llm import client as client_mod
from src.llm.client import APIError, HTTPClient, make_client, model_for

passed = failed = 0


def check(name: str, fn):
    global passed, failed
    try:
        fn()
        print(f"  [pass] {name}")
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        failed += 1
    except Exception as e:                               # noqa: BLE001
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        failed += 1


OPENAI_RESPONSE = {
    "id": "chatcmpl-123",
    "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 8},
}

ANTHROPIC_RESPONSE = {
    "id": "msg_123",
    "content": [{"type": "text", "text": '{"ok": true}'}],
    "usage": {"input_tokens": 130, "output_tokens": 9},
    "stop_reason": "end_turn",
}


class Stub:
    """Replaces _post. Records calls and replays a scripted sequence."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []

    def __call__(self, url, headers, payload, timeout=None):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        if not self.sequence:
            raise AssertionError("stub called more times than scripted")
        item = self.sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def with_env(**kw):
    """Set provider env vars for a test."""
    for k, v in kw.items():
        os.environ[k] = v


def setup_openai():
    with_env(T_BASE_URL="https://api.test/v1", T_API_KEY="k-test",
             T_STYLE="openai", T_MODEL_SMALL="small-1",
             T_MODEL_STRONG="strong-1")


def setup_anthropic():
    with_env(U_BASE_URL="https://api.test", U_API_KEY="k-test",
             U_STYLE="anthropic", U_MODEL_STRONG="claude-x")


def patch(stub, fn):
    original = client_mod._post
    client_mod._post = stub
    try:
        return fn()
    finally:
        client_mod._post = original


# --- configuration ----------------------------------------------------------

def t_missing_config():
    for k in ("Z_BASE_URL", "Z_API_KEY"):
        os.environ.pop(k, None)
    try:
        HTTPClient("Z")
    except APIError as e:
        assert "not configured" in str(e)
        return
    raise AssertionError("must refuse to start without base url and key")


def t_bad_style():
    with_env(Y_BASE_URL="https://x", Y_API_KEY="k", Y_STYLE="carrier-pigeon")
    try:
        HTTPClient("Y")
    except APIError as e:
        assert "Y_STYLE" in str(e)
        return
    raise AssertionError("must reject an unknown wire format")


def t_model_lookup():
    setup_openai()
    assert model_for("T", "small") == "small-1"
    assert model_for("T", "strong") == "strong-1"
    try:
        model_for("T", "giant")
    except APIError:
        return
    raise AssertionError("missing tier must raise")


# --- request shaping --------------------------------------------------------

def t_openai_request_shape():
    setup_openai()
    stub = Stub([OPENAI_RESPONSE])
    c = HTTPClient("T")
    patch(stub, lambda: c.complete("SYS", [{"role": "user", "content": "hi"}],
                                   "small-1"))
    call = stub.calls[0]
    assert call["url"].endswith("/chat/completions"), call["url"]
    assert call["headers"]["authorization"] == "Bearer k-test"
    msgs = call["payload"]["messages"]
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert call["payload"]["temperature"] == 0.0
    assert call["payload"]["seed"] == 12345, "seed aids reproducibility"


def t_anthropic_request_shape():
    setup_anthropic()
    stub = Stub([ANTHROPIC_RESPONSE])
    c = HTTPClient("U")
    patch(stub, lambda: c.complete("SYS", [{"role": "user", "content": "hi"}],
                                   "claude-x"))
    call = stub.calls[0]
    assert call["url"].endswith("/messages"), call["url"]
    assert call["headers"]["x-api-key"] == "k-test"
    assert call["payload"]["system"] == "SYS", "system is a top-level field"
    assert all(m["role"] != "system" for m in call["payload"]["messages"])


# --- response parsing -------------------------------------------------------

def t_openai_parse():
    setup_openai()
    c = HTTPClient("T")
    r = patch(Stub([OPENAI_RESPONSE]),
              lambda: c.complete("SYS", [{"role": "user", "content": "hi"}],
                                 "small-1"))
    assert r.text == '{"ok": true}'
    assert r.input_tokens == 120 and r.output_tokens == 8
    assert r.model == "small-1" and r.raw_id == "chatcmpl-123"
    assert r.finish_reason == "stop"
    assert r.latency_s >= 0


def t_anthropic_parse():
    setup_anthropic()
    c = HTTPClient("U")
    r = patch(Stub([ANTHROPIC_RESPONSE]),
              lambda: c.complete("SYS", [{"role": "user", "content": "hi"}],
                                 "claude-x"))
    assert r.text == '{"ok": true}'
    assert r.input_tokens == 130 and r.output_tokens == 9
    assert r.finish_reason == "end_turn"


def t_token_fallback():
    """Some providers omit usage; tokens must still be counted, or the cost
    numbers in the paper would be wrong."""
    setup_openai()
    no_usage = {"choices": [{"message": {"content": "hello there"},
                             "finish_reason": "stop"}]}
    c = HTTPClient("T")
    r = patch(Stub([no_usage]),
              lambda: c.complete("SYSTEM PROMPT", [{"role": "user",
                                                    "content": "hi"}],
                                 "small-1"))
    assert r.input_tokens > 0 and r.output_tokens > 0


def t_empty_choices():
    setup_openai()
    c = HTTPClient("T")
    try:
        patch(Stub([{"choices": []}]),
              lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                 "small-1"))
    except APIError as e:
        assert "no choices" in str(e)
        return
    raise AssertionError("empty choices must raise")


# --- retries ----------------------------------------------------------------

def t_retries_on_rate_limit():
    setup_openai()
    client_mod.BASE_BACKOFF = 1.0          # keep the test quick
    stub = Stub([APIError("HTTP 429: slow down", status=429), OPENAI_RESPONSE])
    c = HTTPClient("T")
    r = patch(stub, lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                       "small-1"))
    assert r.text == '{"ok": true}'
    assert len(stub.calls) == 2, "should have retried once"


def t_retries_on_server_error():
    setup_openai()
    stub = Stub([APIError("HTTP 503", status=503),
                 APIError("HTTP 502", status=502), OPENAI_RESPONSE])
    c = HTTPClient("T")
    r = patch(stub, lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                       "small-1"))
    assert r.text == '{"ok": true}' and len(stub.calls) == 3


def t_no_retry_on_auth_error():
    """A bad key must fail immediately -- retrying wastes minutes per run."""
    setup_openai()
    stub = Stub([APIError("HTTP 401: bad key", status=401), OPENAI_RESPONSE])
    c = HTTPClient("T")
    try:
        patch(stub, lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                       "small-1"))
    except APIError as e:
        assert e.status == 401
        assert len(stub.calls) == 1, "401 must not be retried"
        return
    raise AssertionError("401 should propagate")


def t_gives_up_eventually():
    setup_openai()
    client_mod.MAX_ATTEMPTS = 3
    stub = Stub([APIError("HTTP 429", status=429)] * 5)
    c = HTTPClient("T")
    try:
        patch(stub, lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                       "small-1"))
    except APIError:
        assert len(stub.calls) == 3, f"expected 3 attempts, got {len(stub.calls)}"
        client_mod.MAX_ATTEMPTS = 5
        return
    client_mod.MAX_ATTEMPTS = 5
    raise AssertionError("should give up after MAX_ATTEMPTS")


def t_network_error_retried():
    setup_openai()
    stub = Stub([APIError("network error: timed out"), OPENAI_RESPONSE])
    c = HTTPClient("T")
    r = patch(stub, lambda: c.complete("S", [{"role": "user", "content": "x"}],
                                       "small-1"))
    assert r.text == '{"ok": true}' and len(stub.calls) == 2


# --- factory ----------------------------------------------------------------

def t_factory_fake():
    c = make_client(fake=True)
    r = c.complete("You are the planner agent.", [], "fake")
    assert "action" in r.text


def t_factory_env_switch():
    os.environ["USE_FAKE_LLM"] = "1"
    try:
        c = make_client("T")
        assert type(c).__name__ == "FakeClient"
    finally:
        os.environ.pop("USE_FAKE_LLM")


def t_call_counter():
    setup_openai()
    c = HTTPClient("T")
    patch(Stub([OPENAI_RESPONSE, OPENAI_RESPONSE]),
          lambda: [c.complete("S", [{"role": "user", "content": "x"}], "small-1")
                   for _ in range(2)])
    assert c.calls == 2


def main() -> int:
    print("CONFIGURATION")
    for name, fn in [
        ("refuses unconfigured provider", t_missing_config),
        ("rejects unknown wire format", t_bad_style),
        ("model tier lookup", t_model_lookup),
    ]:
        check(name, fn)

    print("\nREQUEST SHAPE")
    check("openai-compatible request", t_openai_request_shape)
    check("anthropic request", t_anthropic_request_shape)

    print("\nRESPONSE PARSING")
    for name, fn in [
        ("openai response", t_openai_parse),
        ("anthropic response", t_anthropic_parse),
        ("token fallback when usage missing", t_token_fallback),
        ("empty choices raises", t_empty_choices),
    ]:
        check(name, fn)

    print("\nRETRIES")
    for name, fn in [
        ("retries on 429", t_retries_on_rate_limit),
        ("retries on 5xx", t_retries_on_server_error),
        ("does not retry on 401", t_no_retry_on_auth_error),
        ("gives up after max attempts", t_gives_up_eventually),
        ("retries network errors", t_network_error_retried),
    ]:
        check(name, fn)

    print("\nFACTORY")
    for name, fn in [
        ("fake client", t_factory_fake),
        ("USE_FAKE_LLM switch", t_factory_env_switch),
        ("call counter", t_call_counter),
    ]:
        check(name, fn)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

def test_extract_structure_handles_first_occurrence_phrasings():
    from src.pipelines.lexical import extract_structure

    variants = [
        "Identify patients with asthma at their first qualifying occurrence",
        "Identify patients with newly diagnosed asthma",
        "Identify the earliest occurrence of asthma in each patient",
        "Identify incident asthma cases",
    ]

    for question in variants:
        residual, structure, trace = extract_structure(question)

        assert "asthma" in residual.lower()
        assert structure["first_occurrence"] is True
        assert any(
            item["step"] == "structural_extraction"
            and item["field"] == "first_occurrence"
            for item in trace
        )

