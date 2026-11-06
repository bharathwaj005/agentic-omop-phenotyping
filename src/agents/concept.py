"""Concept Agent: map one Planner concept set to OMOP standard concepts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from src.agents.base import AgentError, load_prompt
from src.llm.base import ActionParseError, parse_action
from src.pipelines.budget import Budget, BudgetExceeded, BudgetTracker
from src.pipelines.deadline import RunDeadlineExceeded
from src.schema.spec import ConceptItem, ConceptSet
from src.tools import vocab


TOOL_ACTIONS = {
    "search_concepts",
    "get_concept",
    "get_descendants",
    "get_ancestors",
    "map_to_standard",
}
ALLOWED_ACTIONS = TOOL_ACTIONS | {"final"}


@dataclass
class ConceptAgentResult:
    """Result of one Concept Agent run."""

    items: list[ConceptItem]
    status: str
    reason: Optional[str]
    tool_calls: int
    llm_calls: int
    parse_errors: int = 0
    messages: list[dict] = field(default_factory=list)


def _observation(text: str) -> str:
    return "Vocabulary tool result:\n" + text


def run_concept_agent(
    client,
    model: str,
    concept_set: ConceptSet,
    vocab_con,
    question: str = "",
    budget: Optional[Budget] = None,
    tracker: Optional[BudgetTracker] = None,
    log=None,
) -> ConceptAgentResult:
    """Populate one Planner concept set using deterministic vocabulary tools.

    The run-level tracker, when supplied, accounts for global LLM/token/tool
    consumption. A local tool counter enforces the per-concept-set cap of six.
    """

    budget = budget or Budget()
    tracker = tracker or BudgetTracker(budget)
    local_tool_calls = 0
    parse_errors = 0
    executed_tool_calls: set[tuple[str, str]] = set()
    duplicate_tool_retries: dict[tuple[str, str], int] = {}

    system, _ = load_prompt("concept")

    user_message = (
        f"Question:\n{question}\n\n"
        f"Concept set name: {concept_set.name}\n"
        f"Domain: {concept_set.domain}\n"
        f"Description: {concept_set.description}\n\n"
        "Identify the best supported OMOP standard concepts for this concept set."
    )

    messages: list[dict] = [{"role": "user", "content": user_message}]

    while True:
        try:
            tracker.check_llm_call()
        except BudgetExceeded as e:
            return ConceptAgentResult(
                [], "failed", str(e), local_tool_calls,
                tracker.llm_calls, parse_errors, messages,
            )

        step = log.step("llm", "concept", model=model) if log else _Null()
        try:
            with step as ev:
                result = client.complete(
                    system=system,
                    messages=messages,
                    model=model,
                    max_tokens=1500,
                )
                if ev is not None:
                    ev.input_tokens = result.input_tokens
                    ev.output_tokens = result.output_tokens
                    ev.detail["raw_text"] = result.text

            tracker.record_llm_call(result.input_tokens, result.output_tokens)
        except Exception as e:  # noqa: BLE001
            if isinstance(e, RunDeadlineExceeded):
                raise
            return ConceptAgentResult(
                [], "failed", f"LLM error: {e}", local_tool_calls,
                tracker.llm_calls, parse_errors, messages,
            )

        messages.append({"role": "assistant", "content": result.text[:4000]})

        try:
            action, payload = parse_action(result.text, ALLOWED_ACTIONS)
        except ActionParseError as e:
            parse_errors += 1
            if log:
                log.note("concept", parse_error=str(e))

            messages.append({
                "role": "user",
                "content": (
                    f"Your reply could not be parsed: {e}. "
                    "Reply with one valid JSON object and nothing else."
                ),
            })

            # Keep the existing run-level LLM cap authoritative.
            continue

        if action in TOOL_ACTIONS:
            signature = (action, json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str))
            if signature in executed_tool_calls:
                duplicate_tool_retries[signature] = duplicate_tool_retries.get(signature, 0) + 1
                repeated = duplicate_tool_retries[signature]
                if log:
                    log.note("concept", duplicate_tool_call=action,
                             duplicate_retries=repeated)
                if repeated >= 2:
                    reason = (
                        "repeated identical vocabulary tool call after "
                        f"{repeated} corrective retries"
                    )
                    return ConceptAgentResult(
                        [], "failed", reason,
                        local_tool_calls, tracker.llm_calls, parse_errors, messages,
                    )
                messages.append({
                    "role": "user",
                    "content": (
                        "You repeated an identical tool call that was already "
                        "executed. Do not repeat it. Use the previous tool "
                        "observation and either choose a different, justified "
                        "query or return your final specification."
                    ),
                })
                continue

            if local_tool_calls >= budget.concept_agent_tool_calls:
                messages.append({
                    "role": "user",
                    "content": (
                        "The Concept Agent vocabulary-tool budget is exhausted. "
                        'Reply now with {"action":"final","result":{"items":[...]}} '
                        "using only concepts established by the evidence already "
                        "returned by the tools."
                    ),
                })
                continue

            try:
                tracker.check_tool_call(
                    budget.single_agent_tool_calls
                    if tracker is not None and tracker is not None
                    else budget.concept_agent_tool_calls
                )
            except BudgetExceeded as e:
                return ConceptAgentResult(
                    [], "failed", str(e), local_tool_calls,
                    tracker.llm_calls, parse_errors, messages,
                )

            tstep = log.step("tool", action, args=payload) if log else _Null()
            try:
                with tstep as tev:
                    observation = vocab.call_tool(vocab_con, action, payload)
                    if tev is not None:
                        tev.detail["rows"] = observation.count("\n")
                        tev.detail["output"] = observation
            except Exception as e:  # noqa: BLE001
                observation = f"tool error: {type(e).__name__}: {e}"

            tracker.record_tool_call()
            local_tool_calls += 1
            executed_tool_calls.add(signature)
            messages.append({
                "role": "user",
                "content": _observation(observation),
            })
            continue

        try:
            raw_items = payload.get("items", [])
            if not isinstance(raw_items, list):
                raise ValueError('"items" must be a list')

            items = [ConceptItem(**item) for item in raw_items]
        except Exception as e:  # noqa: BLE001
            parse_errors += 1
            messages.append({
                "role": "user",
                "content": (
                    f"The final concept list was invalid: {e}. "
                    'Reply with {"action":"final","result":{"items":[...]}}.'
                ),
            })
            continue

        return ConceptAgentResult(
            items, "success", None, local_tool_calls,
            tracker.llm_calls, parse_errors, messages,
        )


class _Null:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
