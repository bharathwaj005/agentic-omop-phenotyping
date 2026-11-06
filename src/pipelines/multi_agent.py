"""C1 and C3 — multi-agent orchestration.

C1 and C3 are the SAME code path with use_critic toggled. That is deliberate:
an ablation whose two arms share no code is not an ablation, because any
difference could come from the reimplementation rather than the removed
component. Likewise use_validator toggles C4.

State machine:

    Plan -> Concepts -> Resolve -> Validate --errors (max 3)--> Build -> Resolve
                                           --pass--> Execute -> Critique
    Critique --revise (max 2)--> Concepts (only the named sets)
    Critique --accept--> Done

Information flow is restricted by construction:
  * the Planner sees only the blinded question;
  * the Concept Agent sees one concept set description plus the question;
  * the Critic sees the specification summary, mechanical warnings and
    AGGREGATE cohort statistics -- never patient rows;
  * nothing anywhere reads reference data.
"""

from __future__ import annotations

from typing import Any, Optional

from src.agents.base import AgentError
from src.agents.runners import critique, fill_concept_set, plan, repair
from src.pipelines.budget import Budget, BudgetExceeded, BudgetTracker
from src.schema.spec import CohortSpec
from src.tools.executor import try_execute
from src.tools.resolver import resolve_items, restrict_to_standard
from src.tools.validator import validate

DEFAULT_MODELS = {"planner": "strong", "concept": "small",
                  "builder": "small", "critic": "strong"}


class MultiAgentResult:
    def __init__(self, spec: Optional[CohortSpec], resolved: dict[str, set[int]],
                 status: str, reason: Optional[str], tracker: BudgetTracker,
                 validation: Any = None, execution: Any = None,
                 critic_rounds: int = 0, validator_retries: int = 0,
                 unresolved: Optional[list[str]] = None):
        self.spec = spec
        self.resolved = resolved
        self.status = status
        self.reason = reason
        self.tracker = tracker
        self.validation = validation
        self.execution = execution
        self.critic_rounds = critic_rounds
        self.validator_retries = validator_retries
        self.unresolved = unresolved or []

    def to_dict(self) -> dict:
        return {
            "status": self.status, "reason": self.reason,
            "critic_rounds": self.critic_rounds,
            "validator_retries": self.validator_retries,
            "unresolved": self.unresolved,
            "usage": self.tracker.to_dict(),
            "resolved_sizes": {k: len(v) for k, v in self.resolved.items()},
        }


def _resolve_all(vocab_con, spec: CohortSpec) -> dict[str, set[int]]:
    return {
        name: restrict_to_standard(
            vocab_con,
            resolve_items(vocab_con, [i.model_dump() for i in cs.items]))
        for name, cs in spec.concept_sets.items()
    }


def run_multi_agent(client, models: dict[str, str], question: str, vocab_con,
                    cdm_con=None, budget: Optional[Budget] = None,
                    use_critic: bool = True, use_validator: bool = True,
                    log=None) -> MultiAgentResult:
    """Run C1 (use_critic=True) or C3 (use_critic=False). Never raises."""
    budget = budget or Budget()
    tracker = BudgetTracker(budget)
    validator_retries = 0
    critic_rounds = 0
    unresolved: list[str] = []
    validation = None
    execution = None

    def fail(reason: str, spec=None, resolved=None) -> MultiAgentResult:
        if log:
            log.note("orchestrator", failed=reason)
        return MultiAgentResult(spec, resolved or {}, "failed", reason, tracker,
                                validation, execution, critic_rounds,
                                validator_retries, unresolved)

    # --- 1. plan -----------------------------------------------------------
    try:
        spec = plan(client, models["planner"], question, tracker, log)
    except BudgetExceeded as e:
        return fail(str(e))
    except AgentError as e:
        return fail(f"planner failed: {e}")

    # --- 2. fill every concept set ----------------------------------------
    targets = list(spec.concept_sets)
    feedback: dict[str, str] = {}

    while True:
        try:
            for name in targets:
                cs = spec.concept_sets[name]
                items = fill_concept_set(
                    client, models["concept"], vocab_con, cs, question,
                    budget=budget, tracker=tracker,
                    feedback=feedback.get(name), log=log)
                cs.items = items
        except BudgetExceeded as e:
            return fail(str(e), spec)
        except AgentError as e:
            return fail(f"concept agent failed: {e}", spec)

        resolved = _resolve_all(vocab_con, spec)

        # --- 3. validate, repair, revalidate -------------------------------
        if use_validator:
            while True:
                validation = validate(spec, vocab_con=vocab_con,
                                      resolved=resolved)
                if log:
                    log.note("validator", passed=validation.passed,
                             issues=validation.to_list())
                if validation.passed:
                    break
                if validator_retries >= budget.validator_retries:
                    return fail("validator errors persisted after "
                                f"{validator_retries} repairs", spec, resolved)
                validator_retries += 1
                try:
                    spec, more = repair(client, models["builder"], spec,
                                        validation, tracker, log)
                except BudgetExceeded as e:
                    return fail(str(e), spec, resolved)
                except AgentError as e:
                    return fail(f"builder failed: {e}", spec, resolved)
                unresolved.extend(more)
                resolved = _resolve_all(vocab_con, spec)
        else:
            # C4: no mechanical checking. Structural validity is still required,
            # because an unexecutable specification cannot be scored at all.
            validation = validate(spec, vocab_con=None, resolved=None)

        # --- 4. execute (aggregates only) ----------------------------------
        if cdm_con is not None:
            execution, exec_error = try_execute(cdm_con, spec, resolved)
            if log:
                log.note("executor",
                         cohort_size=(execution.size if execution else None),
                         error=exec_error)
        else:
            execution, exec_error = None, None

        # --- 5. critique ---------------------------------------------------
        if not use_critic:
            break

        if critic_rounds >= budget.critic_rounds:
            if log:
                log.note("orchestrator", critic_rounds_exhausted=True)
            break

        try:
            verdict = critique(client, models["critic"], spec, validation,
                               execution.to_text() if execution else None,
                               tracker, log)
        except BudgetExceeded as e:
            return fail(str(e), spec, resolved)
        except AgentError as e:
            # A critic that cannot be parsed must not sink an otherwise valid
            # run: accept what we have and record it.
            if log:
                log.note("critic", unusable=str(e)[:200])
            break

        if verdict.verdict == "accept":
            break

        critic_rounds += 1
        feedback = {}
        for issue in verdict.issues:
            if issue.target == "builder":
                continue
            feedback[issue.target] = f"{issue.problem} Suggestion: {issue.suggestion}"
        targets = [t for t in feedback] or []
        if not targets:
            break
        if log:
            log.note("orchestrator", revising=targets, round=critic_rounds)

    return MultiAgentResult(spec, resolved, "success", None, tracker,
                            validation, execution, critic_rounds,
                            validator_retries, unresolved)
