"""A fake LLM client for testing the whole pipeline at zero API cost.

Returns canned, deterministic replies keyed by the agent's role. Use it to
exercise orchestration, caps, logging, error handling and the runner before
spending anything on real calls. It can also be told to fail on demand, so the
retry and cap logic gets tested too.

Usage:
    from src.llm.fake_client import FakeClient
    client = FakeClient()
    result = client.complete(system="...", messages=[...], model="fake-strong")
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from src.llm.base import LLMResult, estimate_tokens

# Canned replies. Keys are matched against the system prompt, so the fake client
# needs no special wiring into the agents.
CANNED: dict[str, dict[str, Any]] = {
    "planner": {
        "action": "final",
        "result": {
            "entry_concept_set": "primary_condition",
            "first_occurrence_only": True,
            "age_min": 18,
            "age_max": None,
            "prior_observation_days": 365,
            "criteria": [],
            "concept_sets": {
                "primary_condition": {
                    "name": "primary_condition",
                    "domain": "Condition",
                    "description": "The condition named in the question",
                    "items": [],
                }
            },
        },
    },
    "concept": {
        "action": "final",
        "result": {
            "items": [
                {"concept_id": 4027663, "include_descendants": True,
                 "is_excluded": False,
                 "rationale": "fake client: stand-in concept for testing"}
            ]
        },
    },
    "builder": {
        "action": "final",
        "result": {"ok": True},
    },
    "critic": {
        "action": "final",
        "result": {"verdict": "accept", "issues": []},
    },
    "single_agent": {
        "action": "final",
        "result": {
            "entry_concept_set": "primary_condition",
            "first_occurrence_only": True,
            "age_min": 18,
            "prior_observation_days": 365,
            "criteria": [],
            "concept_sets": {
                "primary_condition": {
                    "name": "primary_condition",
                    "domain": "Condition",
                    "description": "The condition named in the question",
                    "items": [
                        {"concept_id": 4027663, "include_descendants": True,
                         "is_excluded": False,
                         "rationale": "fake client: single-agent stand-in"}
                    ],
                }
            },
        },
    },
}

# A reply that is deliberately unparseable, for testing the retry path.
GARBAGE = "Sure! Here is the answer: it depends on the clinical context."


class FakeClient:
    """Deterministic stand-in for a real LLM client.

    Parameters
    ----------
    fail_first : if True, the first call for each role returns garbage, so the
                 one-retry parse-error path is exercised.
    raise_after : raise a RuntimeError after this many calls, to test that the
                  runner records failures rather than crashing.
    latency_s  : simulated latency per call.
    """

    def __init__(self, fail_first: bool = False, raise_after: Optional[int] = None,
                 latency_s: float = 0.01):
        self.fail_first = fail_first
        self.raise_after = raise_after
        self.latency_s = latency_s
        self.calls = 0
        self._seen_roles: set[str] = set()

    @staticmethod
    def _role_from(system: str) -> str:
        s = (system or "").lower()

        # Prefer explicit agent declarations. Prompts legitimately mention
        # other agents (e.g. the Concept prompt discusses the Planner), so
        # generic substring matching must not let those references hijack the
        # fake role.
        explicit = (
            ("single_agent", "you are the single_agent agent"),
            ("concept", "you are the concept agent"),
            ("builder", "you are the builder agent"),
            ("critic", "you are the critic agent"),
            ("planner", "you are the planner agent"),
        )
        for role, marker in explicit:
            if marker in s:
                return role

        # The production single-agent prompt intentionally does not contain
        # an artificial role marker. Identify it from its actual contract.
        if (
            "working alone" in s
            and "produce an executable omop cohort specification" in s
            and "clinical informatics agent" in s
        ):
            return "single_agent"

        # Do not infer roles from generic words such as "concept", because
        # ordinary prompts legitimately contain those words.
        return "planner"

    def complete(self, system: str, messages: list[dict], model: str,
                 max_tokens: int = 1500) -> LLMResult:
        self.calls += 1
        if self.raise_after is not None and self.calls > self.raise_after:
            raise RuntimeError("FakeClient: simulated provider failure")

        time.sleep(self.latency_s)
        role = self._role_from(system)

        if self.fail_first and role not in self._seen_roles:
            self._seen_roles.add(role)
            text = GARBAGE
        else:
            text = json.dumps(CANNED.get(role, CANNED["planner"]))

        prompt_text = system + "".join(m.get("content", "") for m in messages)
        return LLMResult(
            text=text,
            input_tokens=estimate_tokens(prompt_text),
            output_tokens=estimate_tokens(text),
            latency_s=self.latency_s,
            model=model,
            raw_id=f"fake-{self.calls}",
            finish_reason="stop",
        )


if __name__ == "__main__":
    c = FakeClient(fail_first=True)
    for role in ("planner", "concept", "critic"):
        r1 = c.complete(system=f"You are the {role} agent.", messages=[],
                        model="fake-strong")
        r2 = c.complete(system=f"You are the {role} agent.", messages=[],
                        model="fake-strong")
        print(f"{role:<8} first={r1.text[:40]!r}")
        print(f"{'':<8} then ={r2.text[:60]!r}\n")
    print("total calls:", c.calls)
