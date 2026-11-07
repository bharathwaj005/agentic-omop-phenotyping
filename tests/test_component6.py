"""Component 6 tests: C2 single-agent baseline and C0-plus lexical baseline.

A ScriptedClient returns exact replies in order, so every branch of the agent
loop is driven deterministically: tool use, parse failure recovery, invalid
specification recovery, validation failure recovery, and each budget cap.

Run:  python -m tests.test_component6
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import duckdb

from src.llm.base import LLMResult, estimate_tokens
from src.pipelines.budget import Budget, BudgetExceeded, BudgetTracker
from src.pipelines.lexical import (
    clean_term, detect_age, detect_temporal, guess_domain, run_lexical,
    split_terms,
)
from src.pipelines.single_agent import run_single_agent

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


# --- synthetic vocabulary ---------------------------------------------------
# 100 Peptic ulcer > {110 Gastric ulcer, 120 Duodenal ulcer}
# 200 Asthma, 210 Chronic obstructive lung disease
# 300 Ibuprofen > 310 Ibuprofen 200 MG Oral Tablet
CONCEPTS = [
    (100, "Peptic ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (110, "Gastric ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (120, "Duodenal ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (200, "Asthma", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (205, "Childhood asthma", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (210, "Chronic obstructive lung disease", "Condition", "SNOMED",
     "Clinical Finding", "S", None),
    (300, "Ibuprofen", "Drug", "RxNorm", "Ingredient", "S", None),
    (310, "Ibuprofen 200 MG Oral Tablet", "Drug", "RxNorm", "Clinical Drug",
     "S", None),
]
ANCESTORS = [
    (100, 100, 0, 0), (100, 110, 1, 1), (100, 120, 1, 1),
    (110, 110, 0, 0), (120, 120, 0, 0),
    (200, 200, 0, 0), (200, 205, 1, 1), (205, 205, 0, 0), (210, 210, 0, 0),
    (300, 300, 0, 0), (300, 310, 1, 1), (310, 310, 0, 0),
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


class ScriptedClient:
    """Returns the scripted replies in order."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls = 0
        self.seen: list[list[dict]] = []

    def complete(self, system, messages, model, max_tokens=1500) -> LLMResult:
        self.calls += 1
        self.seen.append(list(messages))
        text = self.replies.pop(0) if self.replies else '{"action":"final"}'
        return LLMResult(text=text, input_tokens=estimate_tokens(str(messages)),
                         output_tokens=estimate_tokens(text), latency_s=0.0,
                         model=model)


GOOD_SPEC = json.dumps({
    "action": "final",
    "result": {
        "entry_concept_set": "ulcer",
        "first_occurrence_only": True,
        "age_min": 18,
        "prior_observation_days": 365,
        "concept_sets": {
            "ulcer": {"name": "ulcer", "domain": "Condition",
                      "description": "peptic ulcer disease",
                      "items": [{"concept_id": 100, "include_descendants": True,
                                 "is_excluded": False,
                                 "rationale": "covers gastric and duodenal"}]}},
        "criteria": [],
    },
})

SEARCH_ACTION = json.dumps({"action": "search_concepts",
                            "args": {"query": "peptic ulcer",
                                     "domain": "Condition"}})


# --- budget -----------------------------------------------------------------

def t_budget_blocks_llm():
    t = BudgetTracker(Budget(max_llm_calls=2))
    t.check_llm_call(); t.record_llm_call(10, 10)
    t.check_llm_call(); t.record_llm_call(10, 10)
    try:
        t.check_llm_call()
    except BudgetExceeded as e:
        assert e.what == "llm_calls"
        return
    raise AssertionError("third call should be refused")


def t_budget_blocks_tokens():
    t = BudgetTracker(Budget(max_tokens=100))
    t.check_llm_call(); t.record_llm_call(60, 60)
    try:
        t.check_llm_call()
    except BudgetExceeded as e:
        assert e.what == "tokens"
        return
    raise AssertionError("token cap should fire")


def t_budget_parity_documented():
    b = Budget()
    assert b.single_agent_tool_calls == b.concept_agent_tool_calls * 3, (
        "single-agent tool budget must match 3 concept sets x 6 calls")


# --- single agent -----------------------------------------------------------

def t_single_agent_direct_final(con):
    c = ScriptedClient([GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success", r.reason
    assert r.spec.entry_concept_set == "ulcer"
    assert r.resolved["ulcer"] == {100, 110, 120}, r.resolved
    assert r.tracker.llm_calls == 1


def t_single_agent_uses_tools(con):
    c = ScriptedClient([SEARCH_ACTION, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success"
    assert r.tracker.tool_calls == 1
    # the tool observation must be fed back to the model
    last_messages = c.seen[-1]
    assert any("Peptic ulcer" in m.get("content", "") for m in last_messages), \
        "search result was not returned to the agent"


def t_single_agent_recovers_parse_error(con):
    c = ScriptedClient(["Sure! Here is my plan, in prose.", GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success"
    assert r.parse_errors == 1
    assert "could not be parsed" in c.seen[-1][-1]["content"]


def t_single_agent_recovers_invalid_spec(con):
    bad = json.dumps({"action": "final", "result": {
        "entry_concept_set": "missing",
        "concept_sets": {"ulcer": {"name": "ulcer", "domain": "Condition",
                                   "description": "peptic ulcer", "items": []}}}})
    c = ScriptedClient([bad, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success"
    assert r.parse_errors == 1
    assert "rejected" in c.seen[-1][-1]["content"]


def t_single_agent_recovers_validation_failure(con):
    bad = json.dumps({"action": "final", "result": {
        "entry_concept_set": "ulcer",
        "concept_sets": {"ulcer": {
            "name": "ulcer", "domain": "Condition",
            "description": "peptic ulcer disease",
            "items": [{"concept_id": 999999, "include_descendants": True,
                       "is_excluded": False, "rationale": "invented id"}]}},
        "criteria": []}})
    c = ScriptedClient([bad, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success"
    fed_back = c.seen[-1][-1]["content"]
    assert "Validation failed" in fed_back and "concept_not_found" in fed_back


def t_single_agent_llm_budget(con):
    c = ScriptedClient(["not json"] * 10)
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con,
                         budget=Budget(max_llm_calls=3))
    assert r.status == "failed"
    assert "llm_calls" in r.reason
    assert c.calls == 3, c.calls


def t_single_agent_tool_budget(con):
    second_search = json.dumps({
        "action": "search_concepts",
        "args": {"query": "gastric ulcer", "domain": "Condition"}
    })
    third_search = json.dumps({
        "action": "search_concepts",
        "args": {"query": "duodenal ulcer", "domain": "Condition"}
    })
    c = ScriptedClient([SEARCH_ACTION, second_search, third_search, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con,
                         budget=Budget(single_agent_tool_calls=2))
    assert r.status == "success"
    assert r.tracker.tool_calls == 2, r.tracker.tool_calls
    assert any("Tool budget exhausted" in m.get("content", "")
               for m in c.seen[-1])



def t_single_agent_repeated_tool_call(con):
    # Two identical tool requests should not execute the same lookup twice.
    c = ScriptedClient([SEARCH_ACTION, SEARCH_ACTION, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success", r.reason
    assert r.tracker.tool_calls == 1, (
        f"repeated identical tool call executed; count={r.tracker.tool_calls}")

def t_single_agent_bad_tool_args_recovers(con):
    bad_tool = json.dumps({"action": "get_concept", "args": {}})
    c = ScriptedClient([bad_tool, GOOD_SPEC])
    r = run_single_agent(c, "m", "Adults with a first peptic ulcer.", con)
    assert r.status == "success", "a tool error must not kill the run"
    assert any("tool error" in m.get("content", "") for m in c.seen[-1])


def t_single_agent_never_raises(con):
    c = ScriptedClient([json.dumps({"action": "drop_table"})] * 5)
    r = run_single_agent(c, "m", "x", con, budget=Budget(max_llm_calls=2))
    assert r.status == "failed"


# --- C0-plus text handling --------------------------------------------------

def t_clean_term():
    assert clean_term("Identify patients with asthma") == "asthma"
    assert clean_term("adults who have peptic ulcer.") == "peptic ulcer"


def t_split_exclusion():
    p, req, exc = split_terms(
        "Identify patients with asthma who do not have COPD")
    assert p == "asthma", p
    assert exc == ["COPD"], exc


def t_split_requirement():
    p, req, exc = split_terms(
        "Patients with peptic ulcer who also had ibuprofen")
    assert p == "peptic ulcer", p
    assert req == ["ibuprofen"], req


def t_temporal():
    assert detect_temporal("first diagnosis of asthma")[0] is True
    assert detect_temporal("all events of asthma")[0] is False
    assert detect_temporal("new users of ibuprofen")[1] == 365
    assert detect_temporal("with 2 years of prior observation")[1] == 730


def t_age():
    assert detect_age("adults with asthma") == (18, None)
    assert detect_age("patients aged 65 or older") == (65, None)
    assert detect_age("patients aged under 18") == (None, 17)
    assert detect_age("patients with asthma") == (None, None)


def t_domain_guess():
    assert guess_domain("ibuprofen prescribed") == "Drug"
    assert guess_domain("peptic ulcer") == "Condition"
    assert guess_domain("ventilatory assist procedure") == "Procedure"


# --- C0-plus pipeline -------------------------------------------------------

def t_lexical_basic(con):
    r = run_lexical("Identify adults with a first diagnosis of peptic ulcer, "
                    "with one year of prior observation.", con)
    assert r.status == "success", r.reason
    assert r.spec.first_occurrence_only is True
    assert r.spec.age_min == 18
    assert r.spec.prior_observation_days == 365
    assert r.resolved["entry"] == {100, 110, 120}


def t_lexical_exclusion(con):
    r = run_lexical("Identify patients with asthma who do not have "
                    "chronic obstructive lung disease", con)
    assert r.status == "success", r.reason
    assert "exclude_1" in r.spec.concept_sets
    crit = [c for c in r.spec.criteria if c.rule == "none"]
    assert len(crit) == 1 and crit[0].concept_set == "exclude_1"
    assert r.resolved["exclude_1"] == {210}


def t_lexical_preserves_unresolved(con):
    r = run_lexical("Identify patients with asthma who do not have "
                    "pulmonary fibrosis", con)
    assert r.status == "success"
    assert "pulmonary fibrosis" in r.unresolved, r.unresolved
    assert "exclude_1" not in r.spec.concept_sets, \
        "an unresolvable term must not become a fabricated concept"


def t_lexical_no_fabrication(con):
    r = run_lexical("Identify patients with glioblastoma multiforme", con)
    assert r.status == "failed"
    assert r.unresolved == ["glioblastoma multiforme"]
    assert r.spec is None


def t_lexical_prefers_exact_over_subtype(con):
    r = run_lexical("Identify patients with asthma", con)
    ids = [i.concept_id for i in r.spec.concept_sets["entry"].items]
    assert ids == [200], f"must not substitute 'Childhood asthma': {ids}"


def t_lexical_deterministic(con):
    q = "Identify adults with a first diagnosis of peptic ulcer"
    a = run_lexical(q, con)
    b = run_lexical(q, con)
    assert a.spec.model_dump() == b.spec.model_dump()


def t_lexical_drug_domain(con):
    r = run_lexical("Identify new users of ibuprofen", con, domain_hint="Drug")
    assert r.status == "success", r.reason
    assert r.spec.entry_domain == "Drug"
    assert r.spec.prior_observation_days == 365
    assert r.resolved["entry"] == {300, 310}


def t_lexical_trace(con):
    r = run_lexical("Identify patients with asthma who do not have "
                    "chronic obstructive lung disease", con)
    steps = [t["step"] for t in r.trace]
    assert "parse" in steps and "entry_resolved" in steps
    assert "excluded_resolved" in steps


def main() -> int:
    print("BUDGET")
    for name, fn in [
        ("llm call cap", t_budget_blocks_llm),
        ("token cap", t_budget_blocks_tokens),
        ("single-agent budget parity", t_budget_parity_documented),
    ]:
        check(name, fn)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "vocab.duckdb"
        build_vocab(db)
        con = duckdb.connect(db.as_posix(), read_only=True)
        try:
            print("\nC2 SINGLE AGENT")
            for name, fn in [
                ("returns a spec directly", t_single_agent_direct_final),
                ("uses tools and sees results", t_single_agent_uses_tools),
                ("recovers from parse error", t_single_agent_recovers_parse_error),
                ("recovers from invalid spec", t_single_agent_recovers_invalid_spec),
                ("recovers from validation failure",
                 t_single_agent_recovers_validation_failure),
                ("llm budget enforced", t_single_agent_llm_budget),
                ("tool budget enforced", t_single_agent_tool_budget),
                ("repeated tool call handled", t_single_agent_repeated_tool_call),
                ("tool error recoverable", t_single_agent_bad_tool_args_recovers),
                ("never raises", t_single_agent_never_raises),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nC0-PLUS TEXT HANDLING")
            for name, fn in [
                ("lead-in stripping", t_clean_term),
                ("exclusion split", t_split_exclusion),
                ("requirement split", t_split_requirement),
                ("temporal markers", t_temporal),
                ("age detection", t_age),
                ("domain guessing", t_domain_guess),
            ]:
                check(name, fn)

            print("\nC0-PLUS PIPELINE")
            for name, fn in [
                ("basic cohort", t_lexical_basic),
                ("exclusion criterion", t_lexical_exclusion),
                ("preserves unresolved terms", t_lexical_preserves_unresolved),
                ("never fabricates a concept", t_lexical_no_fabrication),
                ("prefers exact over subtype", t_lexical_prefers_exact_over_subtype),
                ("deterministic", t_lexical_deterministic),
                ("drug domain", t_lexical_drug_domain),
                ("provenance trace", t_lexical_trace),
            ]:
                check(name, lambda f=fn: f(con))
        finally:
            con.close()

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
