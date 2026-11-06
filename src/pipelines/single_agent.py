"""C2 — the single-agent baseline.

One LLM, the SAME canonical tools the multi-agent system uses, and a matched
call budget. This is the comparator that makes RQ1 answerable: does role
specialisation and critique add anything beyond giving one capable model the
same instruments?

Everything it touches -- src/tools/vocab.py, src/tools/resolver.py,
src/tools/validator.py, src/schema/spec.py -- is the canonical implementation.
No parallel tool stack.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.agents.base import load_prompt
from src.llm.base import ActionParseError, parse_action
from src.pipelines.budget import Budget, BudgetExceeded, BudgetTracker
from src.schema.spec import CohortSpec
from src.tools import vocab
from src.tools.resolver import resolve_items, restrict_to_standard
from src.tools.validator import validate

PROMPT = "single_agent"
TOOL_ACTIONS = set(vocab.HEADERS)
ALLOWED = TOOL_ACTIONS | {"final"}

MAX_OBSERVATION_CHARS = 1800
MAX_DUPLICATE_TOOL_RETRIES = 2


class SingleAgentResult:
    def __init__(self, spec: Optional[CohortSpec], resolved: dict[str, set[int]],
                 status: str, reason: Optional[str], tracker: BudgetTracker,
                 parse_errors: int, validation: Any = None):
        self.spec = spec
        self.resolved = resolved
        self.status = status            # "success" | "failed"
        self.reason = reason
        self.tracker = tracker
        self.parse_errors = parse_errors
        self.validation = validation

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "parse_errors": self.parse_errors,
            "usage": self.tracker.to_dict(),
            "resolved_sizes": {k: len(v) for k, v in self.resolved.items()},
        }


def _observation(text: str) -> str:
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    return text[:MAX_OBSERVATION_CHARS] + "\n... (truncated)"


def run_single_agent(client, model: str, question: str, vocab_con,
                     budget: Optional[Budget] = None, log=None
                     ) -> SingleAgentResult:
    """Run C2 on one question. Never raises: failures are returned."""
    budget = budget or Budget()
    tracker = BudgetTracker(budget)
    system, _ = load_prompt(PROMPT)
    messages: list[dict] = [{"role": "user", "content": question}]
    parse_errors = 0
    executed_tool_calls: set[tuple[str, str]] = set()
    duplicate_tool_retries: dict[tuple[str, str], int] = {}
    finalization_requested = False

    while True:
        # --- budget gate ---------------------------------------------------
        try:
            tracker.check_llm_call()
        except BudgetExceeded as e:
            if log:
                log.note("single_agent", budget_exceeded=str(e))
            return SingleAgentResult(None, {}, "failed", str(e), tracker,
                                     parse_errors)

        # --- model call ----------------------------------------------------
        step = log.step("llm", "single_agent", model=model) if log else _Null()
        with step as ev:
            result = client.complete(system=system, messages=messages,
                                     model=model, max_tokens=2000)
            if ev is not None:
                ev.input_tokens = result.input_tokens
                ev.output_tokens = result.output_tokens
                ev.detail["raw_text"] = result.text
        tracker.record_llm_call(result.input_tokens, result.output_tokens)
        messages.append({"role": "assistant", "content": result.text[:4000]})

        # --- parse ---------------------------------------------------------
        try:
            action, payload = parse_action(result.text, ALLOWED)
        except ActionParseError as e:
            parse_errors += 1
            if finalization_requested:
                # Some local models return the complete specification object
                # but omit the required {action: final, result: ...} wrapper.
                # Accept only this narrow, deterministic shape during the one
                # finalization turn; normal replies still require parse_action.
                try:
                    candidate = json.loads(result.text)
                except (TypeError, json.JSONDecodeError):
                    candidate = None
                required = {"entry_concept_set", "entry_concept_sets",
                            "entry_arms", "concept_sets", "criteria"}
                if isinstance(candidate, dict) and required.issubset(candidate):
                    action, payload = "final", candidate
                    if log:
                        log.note("single_agent", accepted_unwrapped_final_spec=True)
                else:
                    reason = f"bounded finalization returned an unparseable response: {e}"
                    if log:
                        log.note("single_agent", failed=reason)
                    return SingleAgentResult(None, {}, "failed", reason, tracker,
                                             parse_errors)
            else:
                if log:
                    log.note("single_agent", parse_error=str(e))
                messages.append({
                    "role": "user",
                    "content": (f"Your reply could not be parsed: {e}. Reply with a "
                                "single JSON object and nothing else.")})
                continue

        # --- tool call -----------------------------------------------------
        if action in TOOL_ACTIONS:
            if finalization_requested:
                reason = "repeated identical vocabulary tool call requested after bounded finalization"
                if log:
                    log.note("single_agent", failed=reason, blocked_tool=action)
                return SingleAgentResult(None, {}, "failed", reason, tracker,
                                         parse_errors)
            # Avoid executing the exact same action with identical arguments
            # more than once. Different arguments remain eligible.
            signature = (action, json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str))
            if signature in executed_tool_calls:
                duplicate_tool_retries[signature] = duplicate_tool_retries.get(signature, 0) + 1
                repeated = duplicate_tool_retries[signature]
                if log:
                    log.note("single_agent", duplicate_tool_call=action,
                             duplicate_retries=repeated)
                if repeated >= MAX_DUPLICATE_TOOL_RETRIES:
                    if log:
                        log.note("single_agent", finalization_requested=True,
                                 duplicate_retries=repeated)
                    finalization_requested = True
                    messages.append({
                        "role": "user",
                        "content": (
                            "FINALIZATION REQUIRED: make no more tool calls. "
                            "Use only the question and observations already in "
                            "this conversation. Return one complete final "
                            "specification now. Leave unsupported or unresolved "
                            "criteria out; do not guess concept IDs."
                        ),
                    })
                    continue
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

            try:
                tracker.check_tool_call(budget.single_agent_tool_calls)
            except BudgetExceeded as e:
                messages.append({
                    "role": "user",
                    "content": ("Tool budget exhausted. Reply now with your "
                                'final specification using {"action": "final", '
                                '"result": {...}}.')})
                if log:
                    log.note("single_agent", tool_budget_exhausted=str(e))
                continue

            tstep = log.step("tool", action, args=payload) if log else _Null()
            with tstep as tev:
                observation = vocab.call_tool(vocab_con, action, payload)
                if tev is not None:
                    tev.detail["rows"] = observation.count("\n")
                    tev.detail["output"] = observation
            tracker.record_tool_call()
            executed_tool_calls.add(signature)
            messages.append({"role": "user",
                             "content": _observation(observation)})
            continue

        # --- final ---------------------------------------------------------
        try:
            spec = CohortSpec(question=question, **payload)
        except Exception as e:                           # noqa: BLE001
            parse_errors += 1
            if finalization_requested:
                reason = f"bounded finalization returned an invalid specification: {e}"
                if log:
                    log.note("single_agent", failed=reason)
                return SingleAgentResult(None, {}, "failed", reason, tracker,
                                         parse_errors)
            if log:
                log.note("single_agent", spec_invalid=str(e)[:400])
            messages.append({
                "role": "user",
                "content": (f"That specification was rejected: {e}. "
                            "Correct it and reply with the full JSON object "
                            "again.")})
            continue

        resolved = {name: restrict_to_standard(
                        vocab_con, resolve_items(vocab_con,
                                                 [i.model_dump() for i in cs.items]))
                    for name, cs in spec.concept_sets.items()}
        validation = validate(spec, vocab_con=vocab_con, resolved=resolved)
        if log:
            log.note("validator", passed=validation.passed,
                     issues=validation.to_list())

        # C2 has no Builder: the agent is told its own errors and may retry,
        # which is the single-agent analogue of the validate->build loop.
        if not validation.passed:
            if finalization_requested:
                reason = "bounded finalization failed validation: " + validation.to_text()
                if log:
                    log.note("single_agent", failed=reason)
                return SingleAgentResult(None, {}, "failed", reason, tracker,
                                         parse_errors, validation)
            messages.append({
                "role": "user",
                "content": ("Validation failed:\n" + validation.to_text() +
                            "\nFix these problems and reply with the full "
                            "specification again.")})
            continue

        return SingleAgentResult(spec, resolved, "success", None, tracker,
                                 parse_errors, validation)


class _Null:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
