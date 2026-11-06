"""Shared LLM types and the JSON action protocol.

Deliberately provider-agnostic: agents emit JSON actions rather than using any
vendor's function-calling API, so the same agent code runs against any model
family. That is what makes the second-family experiment (C1-B, C2-B) a config
change rather than a rewrite.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str
    raw_id: Optional[str] = None
    finish_reason: Optional[str] = None


class LLMClient(Protocol):
    """Minimal interface every client implements (real or fake)."""

    def complete(self, system: str, messages: list[dict], model: str,
                 max_tokens: int = 1500) -> LLMResult: ...


# --- JSON action protocol ---------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ActionParseError(ValueError):
    """Raised when a model's reply is not a usable JSON action."""


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model reply.

    Tolerates code fences and surrounding prose, because models add them even
    when told not to. Raises ActionParseError with a message that is fed back to
    the model for exactly one retry.
    """
    if not text or not text.strip():
        raise ActionParseError("empty response")

    candidates: list[str] = []
    fenced = _FENCE.findall(text)
    candidates.extend(f.strip() for f in fenced)
    candidates.append(text.strip())

    # last resort: the outermost {...}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ActionParseError(
        "response is not a JSON object; reply with JSON only, no prose"
    )


def parse_action(text: str, allowed: set[str]) -> tuple[str, dict[str, Any]]:
    """Parse {"action": ..., "args": {...}} or {"action": "final", ...}."""
    obj = extract_json(text)
    action = obj.get("action")
    if not isinstance(action, str):
        raise ActionParseError('missing "action" field')
    if action not in allowed:
        raise ActionParseError(
            f'unknown action {action!r}; allowed: {sorted(allowed)}'
        )
    args = obj.get("args", {})
    if action == "final":
        # final payload may sit under "result" or inline
        args = obj.get("result", {k: v for k, v in obj.items()
                                   if k not in ("action", "args")})
    if not isinstance(args, dict):
        raise ActionParseError('"args" must be an object')
    return action, args


def rows_to_tsv(rows: list[tuple], header: list[str], max_rows: int = 15) -> str:
    """Compact tool output for prompts. TSV costs far fewer tokens than JSON."""
    out = ["\t".join(header)]
    for r in rows[:max_rows]:
        out.append("\t".join("" if v is None else str(v) for v in r))
    if len(rows) > max_rows:
        out.append(f"... {len(rows) - max_rows} more rows omitted")
    return "\n".join(out)


def estimate_tokens(text: str) -> int:
    """Rough fallback when a provider does not return usage counts."""
    return max(1, len(text) // 4)
