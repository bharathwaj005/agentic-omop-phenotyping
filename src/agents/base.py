"""Shared agent scaffolding.

Every agent follows the same contract:
    system prompt (versioned file)  ->  LLM  ->  JSON action  ->  typed object

Two things here matter for the paper:

* PROMPT HASHING. Each prompt file is hashed and the hash goes into the run log.
  "Prompts were frozen at commit X" is then verifiable rather than asserted.
* ONE RETRY on a parse failure. Models occasionally wrap JSON in prose. One
  corrective turn recovers almost all of these; more than one wastes tokens and
  hides a real problem. The retry is logged, so the rate is reportable.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

from src.llm.base import ActionParseError, LLMClient, parse_action

PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"

RETRY_INSTRUCTION = (
    "Your previous reply could not be parsed: {error}\n"
    "Reply again with a single valid JSON object and nothing else. "
    "No prose, no code fences."
)


class AgentError(RuntimeError):
    """The agent could not produce a usable result."""


@lru_cache(maxsize=32)
def load_prompt(name: str) -> tuple[str, str]:
    """Return (text, short_hash) for a prompt file."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise AgentError(f"prompt file not found: {path}")
    text = path.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    return text, digest


def prompt_hashes(names: list[str]) -> dict[str, str]:
    """Hashes for the run log."""
    return {n: load_prompt(n)[1] for n in names}


def run_json_agent(
    client: LLMClient,
    model: str,
    prompt_name: str,
    user_message: str,
    build: Callable[[dict], Any],
    allowed_actions: Optional[set[str]] = None,
    log=None,
    actor: Optional[str] = None,
    max_tokens: int = 1500,
    history: Optional[list[dict]] = None,
) -> Any:
    """Call an agent, parse its JSON action, and build a typed object.

    `build` turns the action payload into the agent's output type, and may
    raise ValueError (pydantic validation) -- which is treated exactly like a
    parse error and gets the same single corrective retry.
    """
    system, _ = load_prompt(prompt_name)
    actor = actor or prompt_name
    allowed = allowed_actions or {"final"}
    messages = list(history or []) + [{"role": "user", "content": user_message}]

    last_error: Optional[str] = None
    for attempt in (1, 2):
        step = (log.step("llm", actor, model=model, attempt=attempt)
                if log else _NullStep())
        with step as ev:
            result = client.complete(system=system, messages=messages,
                                     model=model, max_tokens=max_tokens)
            if ev is not None:
                ev.input_tokens = result.input_tokens
                ev.output_tokens = result.output_tokens
                ev.detail["finish_reason"] = result.finish_reason
                ev.detail["raw_text"] = result.text

        try:
            _action, payload = parse_action(result.text, allowed)
            built = build(payload)
            if log and attempt == 2:
                log.note(actor, recovered_after_parse_error=True)
            return built
        except (ActionParseError, ValueError) as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt == 2:
                break
            if log:
                log.note(actor, parse_error=last_error, retrying=True)
            messages = messages + [
                {"role": "assistant", "content": result.text[:1000]},
                {"role": "user",
                 "content": RETRY_INSTRUCTION.format(error=last_error)},
            ]

    raise AgentError(f"{actor} failed after one retry: {last_error}")


class _NullStep:
    """Stand-in when no run log is supplied (unit tests, ad-hoc calls)."""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
