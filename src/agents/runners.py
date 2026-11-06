"""The four agents.

Each is a thin runner over src/agents/base.py. Keeping them thin is the point:
the behaviour lives in the prompt files (which are hashed into the run log) and
in the canonical tools, not in bespoke Python per agent. Swapping a model, or
replacing an agent with a different implementation, changes nothing else.

Roles and the information each one sees:

  Planner  question                      -> structure + clinical descriptions
  Concept  ONE concept set + question    -> concept items, via tool calls
  Builder  spec summary + validator text -> minimal repairs
  Critic   spec summary + warnings +
           execution aggregates          -> accept, or targeted revision

No agent ever sees reference data, benchmark metadata, or patient rows.
"""

from __future__ import annotations

import json
from typing import Optional

from src.agents.base import AgentError, run_json_agent
from src.llm.base import ActionParseError, parse_action
from src.pipelines.budget import Budget, BudgetExceeded, BudgetTracker
from src.schema.spec import (
    CohortSpec, ConceptItem, ConceptSet, Criterion, CriticOutput, PlannerOutput,
)
from src.tools import vocab
from src.tools.validator import ValidationResult

MAX_OBSERVATION_CHARS = 1500
TOOL_ACTIONS = set(vocab.HEADERS)
CONCEPT_ALLOWED = TOOL_ACTIONS | {"final"}


class _Null:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


# --- Planner ----------------------------------------------------------------

def plan(client, model: str, question: str, tracker: Optional[BudgetTracker] = None,
         log=None) -> CohortSpec:
    """Question -> structure and clinical descriptions. No concept IDs."""
    if tracker:
        tracker.check_llm_call()

    def build(payload: dict) -> CohortSpec:
        return PlannerOutput(**payload).to_spec(question=question)

    spec = run_json_agent(
        client=client, model=model, prompt_name="planner",
        user_message=f"Study question:\n{question}",
        build=build, allowed_actions={"final"}, log=log, actor="planner",
    )
    if tracker:
        tracker.llm_calls += 1
    return spec


# --- Concept Agent ----------------------------------------------------------

def fill_concept_set(client, model: str, vocab_con, concept_set: ConceptSet,
                     question: str, budget: Optional[Budget] = None,
                     tracker: Optional[BudgetTracker] = None,
                     feedback: Optional[str] = None,
                     log=None) -> list[ConceptItem]:
    """Fill ONE concept set using a bounded tool loop.

    Returns whatever items the agent produced. An exhausted tool budget is not
    fatal: the partial result is kept and the cap is recorded, because a
    half-filled set still scores better than a failed run and the cap rate is
    itself a reported metric.
    """
    budget = budget or Budget()
    tracker = tracker or BudgetTracker(budget)
    system_name = "concept"

    task = (f"Study question (for context only):\n{question}\n\n"
            f"Concept set to fill:\n"
            f"  name: {concept_set.name}\n"
            f"  domain: {concept_set.domain}\n"
            f"  description: {concept_set.description}")
    if feedback:
        task += f"\n\nThe critic asked for a revision:\n{feedback}"

    messages: list[dict] = [{"role": "user", "content": task}]
    tool_calls_here = 0
    parse_errors = 0
    executed_tool_calls: set[tuple[str, str]] = set()
    duplicate_tool_retries: dict[tuple[str, str], int] = {}
    tool_cap_retries = 0

    from src.agents.base import load_prompt
    system, _ = load_prompt(system_name)

    while True:
        try:
            tracker.check_llm_call()
        except BudgetExceeded as e:
            if log:
                log.note("concept", concept_set=concept_set.name,
                         budget_exceeded=str(e))
            raise

        step = (log.step("llm", "concept", model=model,
                         concept_set=concept_set.name) if log else _Null())
        with step as ev:
            result = client.complete(system=system, messages=messages,
                                     model=model, max_tokens=1200)
            if ev is not None:
                ev.input_tokens = result.input_tokens
                ev.output_tokens = result.output_tokens
                ev.detail["raw_text"] = result.text
        tracker.record_llm_call(result.input_tokens, result.output_tokens)
        messages.append({"role": "assistant", "content": result.text[:2000]})

        try:
            action, payload = parse_action(result.text, CONCEPT_ALLOWED)
        except ActionParseError as e:
            parse_errors += 1
            if parse_errors > 2:
                raise AgentError(f"concept agent unparseable: {e}")
            messages.append({"role": "user", "content": (
                f"Your reply could not be parsed: {e}. Reply with a single "
                "JSON object and nothing else.")})
            continue

        if action in TOOL_ACTIONS:
            signature = (action, json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str))
            if signature in executed_tool_calls:
                duplicate_tool_retries[signature] = duplicate_tool_retries.get(signature, 0) + 1
                repeated = duplicate_tool_retries[signature]
                if log:
                    log.note("concept", concept_set=concept_set.name,
                             duplicate_tool_call=action,
                             duplicate_retries=repeated)
                if repeated >= 2:
                    raise AgentError(
                        f"repeated identical vocabulary tool call for {concept_set.name}"
                    )
                messages.append({"role": "user", "content": (
                    "You repeated an identical vocabulary-tool call. Use its "
                    "previous result, choose a different justified query, or "
                    "return the final concept items."
                )})
                continue

            if tool_calls_here >= budget.concept_agent_tool_calls:
                tool_cap_retries += 1
                if log:
                    log.note("concept", concept_set=concept_set.name,
                             tool_cap_reached=True,
                             tool_cap_retries=tool_cap_retries)
                if tool_cap_retries >= 2:
                    raise AgentError(
                        f"kept requesting tools after budget exhaustion for {concept_set.name}"
                    )
                messages.append({"role": "user", "content": (
                    "Tool budget exhausted for this concept set. Reply now "
                    'with {"action": "final", "result": {"items": [...]}} '
                    "using the concepts you have already found.")})
                continue

            tstep = (log.step("tool", action, args=payload,
                              concept_set=concept_set.name) if log else _Null())
            with tstep as tev:
                observation = vocab.call_tool(vocab_con, action, payload)
                if tev is not None:
                    tev.detail["rows"] = observation.count("\n")
                    tev.detail["output"] = observation
            tool_calls_here += 1
            executed_tool_calls.add(signature)
            tracker.record_tool_call()
            obs = observation[:MAX_OBSERVATION_CHARS]
            messages.append({"role": "user", "content": obs})
            continue

        # final
        raw_items = payload.get("items", [])
        items: list[ConceptItem] = []
        for it in raw_items:
            try:
                items.append(ConceptItem(**it))
            except Exception as e:                       # noqa: BLE001
                if log:
                    log.note("concept", concept_set=concept_set.name,
                             rejected_item=str(it)[:200], error=str(e)[:200])
        if log:
            log.note("concept", concept_set=concept_set.name,
                     items=len(items), tool_calls=tool_calls_here)
        return items


# --- Builder ----------------------------------------------------------------

def repair(client, model: str, spec: CohortSpec, validation: ValidationResult,
           tracker: Optional[BudgetTracker] = None, log=None
           ) -> tuple[CohortSpec, list[str]]:
    """Apply minimal repairs for validator errors.

    Merge semantics, enforced here rather than trusted to the model:
      * a concept set named in the reply REPLACES that set's items;
      * a set not named is left untouched;
      * "criteria" replaces the criteria list only if present;
      * nothing else in the specification can be changed by the Builder.
    """
    if tracker:
        tracker.check_llm_call()

    message = (f"Current specification:\n{spec.summary()}\n\n"
               f"Validator output:\n{validation.to_text()}")

    def build(payload: dict) -> dict:
        return payload                      # validated during the merge below

    payload = run_json_agent(
        client=client, model=model, prompt_name="builder",
        user_message=message, build=build, allowed_actions={"final"},
        log=log, actor="builder",
    )
    if tracker:
        tracker.llm_calls += 1

    data = spec.model_dump()
    for name, patch in (payload.get("concept_sets") or {}).items():
        if name not in data["concept_sets"]:
            if log:
                log.note("builder", ignored_unknown_set=name)
            continue
        items = patch.get("items")
        if items is None:
            continue
        clean = []
        for it in items:
            try:
                clean.append(ConceptItem(**it).model_dump())
            except Exception as e:                       # noqa: BLE001
                if log:
                    log.note("builder", rejected_item=str(it)[:200],
                             error=str(e)[:200])
        data["concept_sets"][name]["items"] = clean

    if "criteria" in payload and isinstance(payload["criteria"], list):
        clean_crit = []
        for c in payload["criteria"]:
            try:
                clean_crit.append(Criterion(**c).model_dump())
            except Exception:                            # noqa: BLE001
                pass
        data["criteria"] = clean_crit

    unresolved = [str(u) for u in (payload.get("unresolved") or [])]

    try:
        repaired = CohortSpec(**data)
    except Exception as e:                               # noqa: BLE001
        raise AgentError(f"builder produced an invalid specification: {e}")
    return repaired, unresolved


# --- Critic -----------------------------------------------------------------

def critique(client, model: str, spec: CohortSpec, validation: ValidationResult,
             execution_summary: Optional[str] = None,
             tracker: Optional[BudgetTracker] = None, log=None) -> CriticOutput:
    """Clinical plausibility review. Returns accept, or targeted issues."""
    if tracker:
        tracker.check_llm_call()

    parts = [f"Specification:\n{spec.summary()}"]
    warnings = validation.warnings
    parts.append("Mechanical check warnings:\n" +
                 ("\n".join(f"- {w.code}: {w.message}" for w in warnings)
                  if warnings else "none"))
    if execution_summary:
        parts.append(f"Cohort statistics on the test dataset:\n{execution_summary}")
    if spec.question:
        parts.insert(0, f"Study question:\n{spec.question}")

    def build(payload: dict) -> CriticOutput:
        return CriticOutput(**payload)

    out = run_json_agent(
        client=client, model=model, prompt_name="critic",
        user_message="\n\n".join(parts), build=build,
        allowed_actions={"final"}, log=log, actor="critic",
    )
    if tracker:
        tracker.llm_calls += 1

    # Drop issues naming a concept set that does not exist: they cannot be acted
    # on and would waste a revision round.
    valid_targets = set(spec.concept_sets) | {"builder"}
    kept = [i for i in out.issues if i.target in valid_targets]
    if log and len(kept) != len(out.issues):
        log.note("critic", dropped_unroutable_issues=len(out.issues) - len(kept))
    if out.verdict == "revise" and not kept:
        raise AgentError(
            "critic returned revise, but none of its issues targeted an "
            "existing concept set or the builder"
        )
    return CriticOutput(verdict=out.verdict, issues=kept)
