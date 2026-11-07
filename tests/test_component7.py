"""Component 7 tests: C1 and C3 multi-agent orchestration.

A RoleScriptedClient returns replies per agent role, detected from the system
prompt, so every branch is driven deterministically: the critic revise loop,
the validator-builder repair loop, each budget cap, and C3's guarantee that the
critic is never consulted.

Run:  python -m tests.test_component7
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import duckdb

from src.llm.base import LLMResult, estimate_tokens
from src.pipelines.budget import Budget
from src.pipelines.multi_agent import run_multi_agent

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


CONCEPTS = [
    (100, "Peptic ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (110, "Gastric ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (120, "Duodenal ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (300, "Ibuprofen", "Drug", "RxNorm", "Ingredient", "S", None),
    (400, "ASA source code", "Drug", "NDC", "Source Code", None, None),
]
ANCESTORS = [
    (100, 100, 0, 0), (100, 110, 1, 1), (100, 120, 1, 1),
    (110, 110, 0, 0), (120, 120, 0, 0), (300, 300, 0, 0), (400, 400, 0, 0),
]


def build_vocab(path: Path) -> None:
    con = duckdb.connect(path.as_posix())
    con.execute("""CREATE TABLE concept(concept_id BIGINT, concept_name VARCHAR,
        domain_id VARCHAR, vocabulary_id VARCHAR, concept_class_id VARCHAR,
        standard_concept VARCHAR, invalid_reason VARCHAR)""")
    con.executemany("INSERT INTO concept VALUES (?,?,?,?,?,?,?)", CONCEPTS)
    con.execute("""CREATE TABLE concept_ancestor(ancestor_concept_id BIGINT,
        descendant_concept_id BIGINT, min_levels_of_separation INT,
        max_levels_of_separation INT)""")
    con.executemany("INSERT INTO concept_ancestor VALUES (?,?,?,?)", ANCESTORS)
    con.close()


class RoleScriptedClient:
    """Replies per role, detected from the system prompt's first line."""

    def __init__(self, scripts: dict[str, list[str]]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[str] = []
        self.seen: dict[str, list] = {}

    @staticmethod
    def role_of(system: str) -> str:
        # Match the "You are the X agent" line only -- the Builder prompt also
        # mentions the Concept Agent, which a naive substring search catches.
        import re
        m = re.search(r"you are the (\w+) agent", (system or "")[:200], re.I)
        role = m.group(1).lower() if m else "unknown"
        return role if role in ("planner", "concept", "builder", "critic") \
            else "unknown"

    def complete(self, system, messages, model, max_tokens=1500) -> LLMResult:
        role = self.role_of(system)
        self.calls.append(role)
        self.seen.setdefault(role, []).append(list(messages))
        queue = self.scripts.get(role, [])
        text = queue.pop(0) if queue else '{"action":"final","result":{}}'
        return LLMResult(text=text, input_tokens=estimate_tokens(str(messages)),
                         output_tokens=estimate_tokens(text), latency_s=0.0,
                         model=model)

    def count(self, role: str) -> int:
        return self.calls.count(role)


def plan_reply(sets=None, criteria=None) -> str:
    sets = sets or {"ulcer": {"name": "ulcer", "domain": "Condition",
                              "description": "peptic ulcer disease",
                              "items": []}}
    return json.dumps({"action": "final", "result": {
        "entry_concept_set": "ulcer", "first_occurrence_only": True,
        "age_min": 18, "prior_observation_days": 365,
        "concept_sets": sets, "criteria": criteria or []}})


def concept_reply(ids_rationales) -> str:
    return json.dumps({"action": "final", "result": {"items": [
        {"concept_id": cid, "include_descendants": True, "is_excluded": False,
         "rationale": rat} for cid, rat in ids_rationales]}})


SEARCH = json.dumps({"action": "search_concepts",
                     "args": {"query": "peptic ulcer", "domain": "Condition"}})
ACCEPT = json.dumps({"action": "final",
                     "result": {"verdict": "accept", "issues": []}})


def revise(target, problem="too narrow", suggestion="search the parent") -> str:
    return json.dumps({"action": "final", "result": {
        "verdict": "revise",
        "issues": [{"target": target, "problem": problem,
                    "suggestion": suggestion}]}})


MODELS = {"planner": "strong", "concept": "small",
          "builder": "small", "critic": "strong"}
Q = "Identify adults with a first peptic ulcer and one year of prior observation."


# --- C3 ---------------------------------------------------------------------

def t_c3_happy_path(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(100, "covers gastric and duodenal")])],
    })
    r = run_multi_agent(c, MODELS, Q, con, use_critic=False)
    assert r.status == "success", r.reason
    assert r.resolved["ulcer"] == {100, 110, 120}
    assert r.spec.age_min == 18 and r.spec.prior_observation_days == 365


def t_c3_never_calls_critic(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(100, "entry concept")])],
        "critic": [revise("ulcer")],      # present but must be ignored
    })
    r = run_multi_agent(c, MODELS, Q, con, use_critic=False)
    assert r.status == "success"
    assert c.count("critic") == 0, "C3 must not consult the critic"
    assert r.critic_rounds == 0


def t_c1_and_c3_share_code_path(con):
    """Same scripts, only the flag differs -- the ablation requirement."""
    def make():
        return RoleScriptedClient({
            "planner": [plan_reply()],
            "concept": [concept_reply([(100, "entry concept")])],
            "critic": [ACCEPT]})
    a = run_multi_agent(make(), MODELS, Q, con, use_critic=False)
    b = run_multi_agent(make(), MODELS, Q, con, use_critic=True)
    assert a.spec.model_dump() == b.spec.model_dump(), \
        "with an accepting critic the two configurations must agree"


# --- C1 critic loop ---------------------------------------------------------

def t_c1_accept(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(100, "entry concept")])],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success" and r.critic_rounds == 0
    assert c.count("critic") == 1


def t_c1_revision_round(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(110, "gastric only, too narrow")]),
                    concept_reply([(100, "broadened to peptic ulcer")])],
        "critic": [revise("ulcer"), ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success"
    assert r.critic_rounds == 1
    assert r.resolved["ulcer"] == {100, 110, 120}, r.resolved
    assert c.count("concept") == 2


def t_c1_feedback_reaches_concept_agent(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(110, "gastric only")]),
                    concept_reply([(100, "broadened")])],
        "critic": [revise("ulcer", "too narrow", "use the parent concept"),
                   ACCEPT]})
    run_multi_agent(c, MODELS, Q, con, use_critic=True)
    second = c.seen["concept"][1][0]["content"]
    assert "critic asked for a revision" in second
    assert "use the parent concept" in second


def t_c1_revision_targets_named_sets_only(con):
    sets = {
        "ulcer": {"name": "ulcer", "domain": "Condition",
                  "description": "peptic ulcer disease", "items": []},
        "nsaid": {"name": "nsaid", "domain": "Drug",
                  "description": "NSAID exposure", "items": []},
    }
    crit = [{"concept_set": "nsaid", "window_start_days": -90,
             "window_end_days": 0, "rule": "at_least_one"}]
    c = RoleScriptedClient({
        "planner": [plan_reply(sets, crit)],
        "concept": [concept_reply([(100, "ulcer entry")]),
                    concept_reply([(300, "ibuprofen")]),
                    concept_reply([(100, "ulcer revised")])],
        "critic": [revise("ulcer"), ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success"
    # 2 sets filled initially + only 1 refilled on revision
    assert c.count("concept") == 3, c.calls


def t_c1_critic_rounds_capped(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(100, "entry concept")])] * 6,
        "critic": [revise("ulcer")] * 6})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True,
                        budget=Budget(critic_rounds=2))
    assert r.status == "success"
    assert r.critic_rounds == 2, r.critic_rounds
    assert c.count("critic") == 2


def t_c1_unroutable_issue_is_logged_as_unusable(con):
    class RecordingLog:
        class StepContext:
            def __init__(self, log, kind, actor, fields):
                self.log = log
                self.kind = kind
                self.actor = actor
                self.detail = dict(fields)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if exc is not None:
                    self.detail["error"] = f"{exc_type.__name__}: {exc}"
                self.log.events.append(
                    (self.actor, {"kind": self.kind, **self.detail})
                )
                return False

        def __init__(self):
            self.events = []

        def note(self, actor, **fields):
            self.events.append((actor, fields))

        def step(self, kind, actor, **fields):
            return self.StepContext(self, kind, actor, fields)

    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(100, "entry concept")])],
        "critic": [revise("a_set_that_does_not_exist")]})
    log = RecordingLog()
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True, log=log)

    assert r.status == "success", r
    assert r.critic_rounds == 0, r.critic_rounds
    assert any(
        actor == "critic" and "unusable" in fields
        for actor, fields in log.events
    ), log.events


# --- validator and builder --------------------------------------------------

def t_builder_repairs_bad_concept(con):
    bad = concept_reply([(999999, "hallucinated id")])
    fix = json.dumps({"action": "final", "result": {"concept_sets": {
        "ulcer": {"items": [{"concept_id": 100, "include_descendants": True,
                             "is_excluded": False,
                             "rationale": "replaced with a real concept"}]}}}})
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [bad],
        "builder": [fix],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success", r.reason
    assert r.validator_retries == 1
    assert r.resolved["ulcer"] == {100, 110, 120}


def t_builder_cannot_touch_unnamed_sets(con):
    sets = {
        "ulcer": {"name": "ulcer", "domain": "Condition",
                  "description": "peptic ulcer disease", "items": []},
        "nsaid": {"name": "nsaid", "domain": "Drug",
                  "description": "NSAID exposure", "items": []},
    }
    crit = [{"concept_set": "nsaid", "window_start_days": -90,
             "window_end_days": 0, "rule": "at_least_one"}]
    fix = json.dumps({"action": "final", "result": {"concept_sets": {
        "ulcer": {"items": [{"concept_id": 100, "include_descendants": True,
                             "is_excluded": False, "rationale": "fixed"}]}}}})
    c = RoleScriptedClient({
        "planner": [plan_reply(sets, crit)],
        "concept": [concept_reply([(999999, "bad id")]),
                    concept_reply([(300, "ibuprofen")])],
        "builder": [fix],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success", r.reason
    nsaid_ids = [i.concept_id for i in r.spec.concept_sets["nsaid"].items]
    assert nsaid_ids == [300], f"builder altered a set it did not name: {nsaid_ids}"


def t_builder_retries_capped(con):
    bad = concept_reply([(999999, "hallucinated id")])
    useless = json.dumps({"action": "final", "result": {"concept_sets": {}}})
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [bad],
        "builder": [useless] * 6,
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True,
                        budget=Budget(validator_retries=2))
    assert r.status == "failed"
    assert "validator errors persisted" in r.reason
    assert c.count("builder") == 2


def t_non_standard_concept_rejected(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(400, "a source code, not standard")])],
        "builder": [json.dumps({"action": "final", "result": {"concept_sets": {
            "ulcer": {"items": [{"concept_id": 100,
                                 "include_descendants": True,
                                 "is_excluded": False,
                                 "rationale": "standard concept"}]}}}})],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success"
    assert r.validator_retries == 1


def t_c4_no_validator(con):
    """With the validator off, a bad concept survives to the output."""
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [concept_reply([(999999, "hallucinated id")])],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True, use_validator=False)
    assert r.status == "success"
    assert c.count("builder") == 0
    ids = [i.concept_id for i in r.spec.concept_sets["ulcer"].items]
    assert ids == [999999], "C4 must not silently repair"


# --- tool loop and budgets --------------------------------------------------

def t_concept_agent_uses_tools(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [SEARCH, concept_reply([(100, "found by search")])],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True)
    assert r.status == "success"
    assert r.tracker.tool_calls == 1
    second = c.seen["concept"][1][-1]["content"]
    assert "Peptic ulcer" in second, "tool output was not returned to the agent"


def t_concept_tool_cap(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [SEARCH] * 5 + [concept_reply([(100, "eventually")])],
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True,
                        budget=Budget(concept_agent_tool_calls=2))
    assert r.status == "success"
    assert r.tracker.tool_calls == 2, r.tracker.tool_calls


def t_llm_budget_fails_run(con):
    c = RoleScriptedClient({
        "planner": [plan_reply()],
        "concept": [SEARCH] * 20,
        "critic": [ACCEPT]})
    r = run_multi_agent(c, MODELS, Q, con, use_critic=True,
                        budget=Budget(max_llm_calls=4))
    assert r.status == "failed"
    assert "llm_calls" in r.reason


def t_planner_failure_is_reported(con):
    c = RoleScriptedClient({"planner": ["this is not json", "still not json"]})
    r = run_multi_agent(c, MODELS, Q, con)
    assert r.status == "failed" and "planner" in r.reason


def t_never_raises(con):
    c = RoleScriptedClient({"planner": [plan_reply()], "concept": ["garbage"] * 9})
    r = run_multi_agent(c, MODELS, Q, con)
    assert r.status == "failed"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "vocab.duckdb"
        build_vocab(db)
        con = duckdb.connect(db.as_posix(), read_only=True)
        try:
            print("C3 (no critic)")
            for name, fn in [
                ("happy path", t_c3_happy_path),
                ("critic never consulted", t_c3_never_calls_critic),
                ("C1 and C3 share the code path", t_c1_and_c3_share_code_path),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nC1 CRITIC LOOP")
            for name, fn in [
                ("accept on first review", t_c1_accept),
                ("revision round", t_c1_revision_round),
                ("feedback reaches the concept agent",
                 t_c1_feedback_reaches_concept_agent),
                ("revision targets named sets only",
                 t_c1_revision_targets_named_sets_only),
                ("critic rounds capped", t_c1_critic_rounds_capped),
                ("unroutable issue logged as unusable",
                 t_c1_unroutable_issue_is_logged_as_unusable),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nVALIDATOR AND BUILDER")
            for name, fn in [
                ("builder repairs a bad concept", t_builder_repairs_bad_concept),
                ("builder cannot touch unnamed sets",
                 t_builder_cannot_touch_unnamed_sets),
                ("builder retries capped", t_builder_retries_capped),
                ("non-standard concept rejected", t_non_standard_concept_rejected),
                ("C4 without validator does not repair", t_c4_no_validator),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nTOOL LOOP AND BUDGETS")
            for name, fn in [
                ("concept agent uses tools", t_concept_agent_uses_tools),
                ("concept tool cap", t_concept_tool_cap),
                ("llm budget fails the run", t_llm_budget_fails_run),
                ("planner failure reported", t_planner_failure_is_reported),
                ("never raises", t_never_raises),
            ]:
                check(name, lambda f=fn: f(con))
        finally:
            con.close()

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
