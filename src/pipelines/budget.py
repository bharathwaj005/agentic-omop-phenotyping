"""Run budgets.

Budget parity is what makes the C1 vs C2 comparison defensible. If the
multi-agent system were allowed more model calls than the single agent, any
accuracy advantage could simply be bought compute. The same Budget object is
therefore passed to every LLM pipeline, and the limits live in one place.

Exceeding a budget is not an error in the usual sense: the run is marked failed
and KEPT in the analysis with accuracy 0. Dropping exhausted runs would flatter
whichever configuration runs longest.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Budget:
    """Hard caps for one run. Identical across C1, C2, C3, C4, C5."""

    max_llm_calls: int = 30
    max_tokens: int = 150_000
    concept_agent_tool_calls: int = 6      # per concept set (C1 family)
    single_agent_tool_calls: int = 18      # total (C2) -- see note below
    validator_retries: int = 3
    critic_rounds: int = 2

    def to_dict(self) -> dict:
        return asdict(self)


# Note on single_agent_tool_calls: a C1 run may invoke the Concept Agent once
# per concept set, each with its own tool budget. A typical task has 1-3 concept
# sets, so 6 x 3 = 18 is the matched allowance for the single agent. This is
# stated in Methods; it is the first thing a reviewer will check.


class BudgetExceeded(RuntimeError):
    def __init__(self, what: str, limit: int, used: int):
        super().__init__(f"budget exceeded: {what} limit={limit} used={used}")
        self.what, self.limit, self.used = what, limit, used


class BudgetTracker:
    """Counts consumption and refuses the call that would breach a cap."""

    def __init__(self, budget: Budget):
        self.budget = budget
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens = 0

    def check_llm_call(self) -> None:
        if self.llm_calls >= self.budget.max_llm_calls:
            raise BudgetExceeded("llm_calls", self.budget.max_llm_calls,
                                 self.llm_calls)
        if self.tokens >= self.budget.max_tokens:
            raise BudgetExceeded("tokens", self.budget.max_tokens, self.tokens)

    def record_llm_call(self, input_tokens: int, output_tokens: int) -> None:
        self.llm_calls += 1
        self.tokens += input_tokens + output_tokens

    def check_tool_call(self, limit: int) -> None:
        if self.tool_calls >= limit:
            raise BudgetExceeded("tool_calls", limit, self.tool_calls)

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def to_dict(self) -> dict:
        return {"llm_calls": self.llm_calls, "tool_calls": self.tool_calls,
                "tokens": self.tokens}
