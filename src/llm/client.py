"""The real LLM client.

Provider-agnostic on purpose. Two wire formats cover essentially every hosted
model: the OpenAI-compatible /chat/completions shape (used by OpenAI, Groq,
Together, OpenRouter, DeepSeek, Mistral, and local vLLM or Ollama servers) and
the Anthropic /v1/messages shape. Switching model family for the C1-B / C2-B
experiments is then a config edit, not a code change -- which is exactly the
claim the paper makes about architecture outliving any one model.

Uses urllib from the standard library: no extra dependency, one less thing to
install on a borrowed machine.

Configure in .env:
    A_BASE_URL=https://api.example.com/v1
    A_API_KEY=sk-...
    A_STYLE=openai            # or: anthropic
    A_MODEL_SMALL=...
    A_MODEL_STRONG=...
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from src.llm.base import LLMResult, estimate_tokens
from src.pipelines.deadline import RunDeadlineExceeded


def _local_ollama_context() -> int:
    """Read a bounded per-request Ollama context size."""
    raw = os.environ.get("A_OLLAMA_NUM_CTX", "8192")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise APIError("A_OLLAMA_NUM_CTX must be an integer from 2048 to 32768") from exc
    if value < 2048 or value > 32768:
        raise APIError("A_OLLAMA_NUM_CTX must be an integer from 2048 to 32768")
    return value

RETRY_STATUS = {408, 409, 425, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
BASE_BACKOFF = 2.0
TIMEOUT_S = float(os.environ.get("JBI_HTTP_TIMEOUT_S", "600"))


class APIError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _post(url: str, headers: dict[str, str], payload: dict,
          timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """One HTTP POST. Isolated so tests can replace it without a network."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:400]
        except Exception:                                # noqa: BLE001
            pass
        raise APIError(f"HTTP {e.code}: {detail}", status=e.code) from e
    except urllib.error.URLError as e:
        raise APIError(f"network error: {e.reason}") from e
    except TimeoutError as e:
        raise APIError("request timed out", status=408) from e


class HTTPClient:
    """Calls one provider. One instance per model family."""

    def __init__(self, provider: str = "A", temperature: float = 0.0,
                 seed: Optional[int] = 12345):
        p = provider.upper()
        self.provider = p
        self.base_url = (os.environ.get(f"{p}_BASE_URL") or "").rstrip("/")
        self.api_key = os.environ.get(f"{p}_API_KEY") or ""
        self.style = (os.environ.get(f"{p}_STYLE") or "openai").lower()
        self.temperature = temperature
        self.seed = seed
        self.calls = 0

        if not self.base_url or not self.api_key:
            raise APIError(
                f"provider {p} is not configured. Set {p}_BASE_URL and "
                f"{p}_API_KEY in .env"
            )
        if self.style not in ("openai", "anthropic"):
            raise APIError(f"unknown {p}_STYLE {self.style!r}")

    # --- request shaping ---------------------------------------------------

    def _build(self, system: str, messages: list[dict], model: str,
               max_tokens: int) -> tuple[str, dict, dict]:
        if self.style == "anthropic":
            url = f"{self.base_url}/messages"
            headers = {
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": model,
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": self.temperature,
            }
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            }
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system}] + messages,
                "max_tokens": max_tokens,
                "temperature": self.temperature,
            }
            # Configure a larger context only for the local Ollama endpoint.
            if "127.0.0.1:11434" in self.base_url or "localhost:11434" in self.base_url:
                payload["options"] = {"num_ctx": _local_ollama_context()}

            # Gemini's OpenAI-compatible endpoint rejects the OpenAI seed field.
            # Keep seed as a client attribute for other providers, but do not send it.
        return url, headers, payload

    @staticmethod
    def _parse(data: dict, style: str, fallback_text: str
               ) -> tuple[str, int, int, Optional[str], Optional[str]]:
        """Return (text, input_tokens, output_tokens, raw_id, finish_reason)."""
        if not isinstance(data, dict):
            raise APIError(f"unexpected response type {type(data).__name__}",
                           status=422)
        if style == "anthropic":
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks
                           if b.get("type") == "text")
            usage = data.get("usage") or {}
            return (text,
                    int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                    data.get("id"),
                    data.get("stop_reason"))

        if not isinstance(data, dict):
            raise APIError(f"unexpected response type {type(data).__name__}",
                           status=422)
        choices = data.get("choices") or []
        if not choices:
            # 422: a malformed body will not improve on retry
            raise APIError(f"no choices in response: {str(data)[:200]}",
                           status=422)
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        if not in_tok:
            in_tok = estimate_tokens(fallback_text)
        if not out_tok:
            out_tok = estimate_tokens(text)
        return text, in_tok, out_tok, data.get("id"), choices[0].get("finish_reason")

    # --- public ------------------------------------------------------------

    def complete(self, system: str, messages: list[dict], model: str,
                 max_tokens: int = 1500) -> LLMResult:
        url, headers, payload = self._build(system, messages, model, max_tokens)
        fallback = system + "".join(m.get("content", "") for m in messages)
        is_local_ollama = (
            "127.0.0.1:11434" in self.base_url
            or "localhost:11434" in self.base_url
        )
        # Local inference has no hosted rate-limit behavior; bound repeated
        # read timeouts so one slow generation cannot hold a queue row for ten
        # minutes. One retry covers transient local-server stalls.
        max_attempts = 2 if is_local_ollama else MAX_ATTEMPTS
        deadline_at = getattr(self, "run_deadline_at", None)

        def check_deadline() -> float | None:
            if deadline_at is None:
                return None
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise RunDeadlineExceeded("JBI_RUN_DEADLINE_S exceeded")
            return remaining

        last: Optional[APIError] = None
        for attempt in range(1, max_attempts + 1):
            remaining = check_deadline()
            request_timeout = min(TIMEOUT_S, remaining) if remaining is not None else TIMEOUT_S
            t0 = time.time()
            try:
                if deadline_at is None:
                    data = _post(url, headers, payload)
                else:
                    data = _post(url, headers, payload, timeout=request_timeout)
                check_deadline()
                text, in_tok, out_tok, raw_id, finish = self._parse(
                    data, self.style, fallback)
                self.calls += 1
                return LLMResult(
                    text=text, input_tokens=in_tok, output_tokens=out_tok,
                    latency_s=round(time.time() - t0, 3), model=model,
                    raw_id=raw_id, finish_reason=finish,
                )
            except APIError as e:
                remaining = check_deadline()
                last = e
                retryable = e.status is None or e.status in RETRY_STATUS
                # Fail fast on local Ollama HTTP 500s; repeated retries can
                # waste minutes and obscure the server's actual error.
                if is_local_ollama and e.status == 500:
                    retryable = False
                if not retryable or attempt == max_attempts:
                    raise
                # exponential backoff with jitter; rate limits are the common case
                delay = BASE_BACKOFF ** attempt + random.uniform(0, 1)
                if remaining is not None:
                    delay = min(delay, remaining)
                time.sleep(delay)
        raise last or APIError("unreachable")


# --- model registry ---------------------------------------------------------

def model_for(provider: str, tier: str) -> str:
    """Resolve a tier ('small' or 'strong') to a model name from .env."""
    normalized_tier = str(tier).strip().lower()
    if normalized_tier not in {"small", "strong"}:
        raise APIError(
            f"unknown model tier {tier!r}; expected 'small' or 'strong'. "
            "Pass explicit model IDs directly to the runner."
        )
    key = f"{provider.upper()}_MODEL_{normalized_tier.upper()}"
    name = os.environ.get(key)
    if not name:
        raise APIError(f"{key} is not set in .env")
    return name


def make_client(provider: str = "A", fake: bool = False):
    """Factory. fake=True returns the zero-cost stand-in."""
    if fake or os.environ.get("USE_FAKE_LLM") == "1":
        from src.llm.fake_client import FakeClient
        return FakeClient()
    return HTTPClient(provider=provider)


def smoke_test(provider: str = "A") -> None:
    """Confirm the provider works and report tokens. Costs a few cents."""
    client = HTTPClient(provider=provider)
    for tier in ("small", "strong"):
        try:
            model = model_for(provider, tier)
        except APIError as e:
            print(f"  {tier:<7} SKIP: {e}")
            continue
        try:
            r = client.complete(
                system="You reply with JSON only, no prose.",
                messages=[{"role": "user",
                           "content": 'Reply exactly: {"ok": true}'}],
                model=model, max_tokens=50)
            print(f"  {tier:<7} {model}")
            print(f"          reply={r.text.strip()[:60]!r}")
            print(f"          tokens in={r.input_tokens} out={r.output_tokens} "
                  f"latency={r.latency_s}s")
        except APIError as e:
            print(f"  {tier:<7} FAIL: {e}")


if __name__ == "__main__":
    import sys
    prov = sys.argv[1] if len(sys.argv) > 1 else "A"
    print(f"Smoke test for provider {prov.upper()}")
    smoke_test(prov)
