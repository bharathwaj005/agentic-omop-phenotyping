"""Component 1 tests. Run:  python -m tests.test_component1

No pytest needed -- plain asserts so it works anywhere.
"""

from __future__ import annotations

import json
import sys

from src.llm.base import ActionParseError, extract_json, parse_action, rows_to_tsv
from src.llm.fake_client import FakeClient
from src.logging.provenance import RunLog
from src.schema.spec import (
    CohortSpec, ConceptItem, ConceptSet, Criterion, CriticOutput, PlannerOutput,
)

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


def valid_spec() -> CohortSpec:
    return CohortSpec(
        question="demo",
        entry_concept_set="pu",
        age_min=18,
        prior_observation_days=365,
        concept_sets={
            "pu": ConceptSet(name="pu", domain="Condition",
                             description="peptic ulcer",
                             items=[ConceptItem(concept_id=4027663,
                                                rationale="covers subtypes")]),
            "nsaid": ConceptSet(name="nsaid", domain="Drug",
                                description="NSAIDs"),
        },
        criteria=[Criterion(concept_set="nsaid", window_start_days=-90,
                            window_end_days=0)],
    )


# --- schema -----------------------------------------------------------------

def t_spec_valid():
    s = valid_spec()
    assert s.spec_version == "1.1"
    assert s.entry_domain == "Condition"
    assert s.unfilled_sets() == ["nsaid"], s.unfilled_sets()
    assert s.all_concept_ids() == {4027663}


def t_spec_bad_entry():
    try:
        CohortSpec(entry_concept_set="missing", concept_sets={})
    except Exception:
        return
    raise AssertionError("should reject an entry set that does not exist")


def t_spec_bad_criterion_ref():
    try:
        CohortSpec(
            entry_concept_set="a",
            concept_sets={"a": ConceptSet(name="a", domain="Condition",
                                          description="x")},
            criteria=[Criterion(concept_set="nope")],
        )
    except Exception:
        return
    raise AssertionError("should reject a criterion referencing an unknown set")


def t_window_order():
    try:
        Criterion(concept_set="a", window_start_days=10, window_end_days=-10)
    except Exception:
        return
    raise AssertionError("should reject start > end")


def t_rationale_required():
    try:
        ConceptItem(concept_id=1, rationale="")
    except Exception:
        return
    raise AssertionError("rationale must be required and non-trivial")


def t_planner_to_spec():
    p = PlannerOutput(
        entry_concept_set="a",
        concept_sets={"a": ConceptSet(name="a", domain="Condition",
                                      description="thing")},
    )
    s = p.to_spec(question="q")
    assert s.question == "q" and s.unfilled_sets() == ["a"]


def t_critic_revise_needs_issues():
    try:
        CriticOutput(verdict="revise", issues=[])
    except Exception:
        pass
    else:
        raise AssertionError("revise with no issues must be rejected")
    ok = CriticOutput(verdict="accept")
    assert ok.issues == []


# --- action protocol --------------------------------------------------------

def t_extract_plain():
    assert extract_json('{"a": 1}')["a"] == 1


def t_extract_fenced():
    text = 'Here you go:\n```json\n{"action": "final", "result": {"x": 2}}\n```'
    assert extract_json(text)["result"]["x"] == 2


def t_extract_prose_wrapped():
    text = 'Thinking... {"action": "search", "args": {"q": "ulcer"}} done'
    assert extract_json(text)["action"] == "search"


def t_extract_garbage():
    try:
        extract_json("no json at all here")
    except ActionParseError:
        return
    raise AssertionError("must raise ActionParseError on unparseable text")


def t_parse_action_allowed():
    a, args = parse_action('{"action":"search","args":{"q":"x"}}',
                           {"search", "final"})
    assert a == "search" and args["q"] == "x"


def t_parse_action_rejects_unknown():
    try:
        parse_action('{"action":"drop_table"}', {"search", "final"})
    except ActionParseError:
        return
    raise AssertionError("must reject actions outside the allowed set")


def t_tsv():
    out = rows_to_tsv([(1, "a"), (2, "b")], ["id", "name"], max_rows=1)
    assert out.splitlines()[0] == "id\tname"
    assert "1 more rows omitted" in out


# --- fake client ------------------------------------------------------------

def t_fake_deterministic():
    c = FakeClient()
    r1 = c.complete("You are the planner agent.", [], "fake-strong")
    r2 = c.complete("You are the planner agent.", [], "fake-strong")
    assert r1.text == r2.text
    assert json.loads(r1.text)["action"] == "final"
    assert r1.input_tokens > 0 and r1.output_tokens > 0


def t_fake_fail_first():
    c = FakeClient(fail_first=True)
    bad = c.complete("You are the concept agent.", [], "m")
    good = c.complete("You are the concept agent.", [], "m")
    try:
        extract_json(bad.text)
        raise AssertionError("first reply should be unparseable")
    except ActionParseError:
        pass
    assert json.loads(good.text)["action"] == "final"


def t_fake_raises():
    c = FakeClient(raise_after=1)
    c.complete("planner", [], "m")
    try:
        c.complete("planner", [], "m")
    except RuntimeError:
        return
    raise AssertionError("should raise after the configured number of calls")


# --- provenance -------------------------------------------------------------

def t_runlog():
    log = RunLog("TEST_T99_rep1", "TEST", "T99", 1, models={"planner": "fake"})
    with log.step("llm", "planner", model="fake") as ev:
        ev.input_tokens, ev.output_tokens = 100, 50
    with log.step("tool", "search_concepts", query="x") as ev:
        ev.detail["rows"] = 3
    log.note("validator", passed=False)

    spec = valid_spec().model_dump()
    p = log.finish("success", final_spec=spec)
    assert p.exists()

    d = json.loads(p.read_text())
    assert d["totals"]["llm_calls"] == 1
    assert d["totals"]["tool_calls"] == 1
    assert d["totals"]["total_tokens"] == 150
    assert d["totals"]["validator_retries"] == 1
    assert d["auditability"] == 1.0, d["auditability"]
    assert d["environment"]["spec_version"] == "1.1"
    assert RunLog.exists("TEST", "T99", 1)
    p.unlink()


def t_runlog_records_exception():
    log = RunLog("TEST_T98_rep1", "TEST", "T98", 1)
    try:
        with log.step("llm", "planner") as ev:
            raise ValueError("boom")
    except ValueError:
        pass
    p = log.finish("failed", error="ValueError: boom")
    d = json.loads(p.read_text())
    assert d["status"] == "failed"
    assert "boom" in d["events"][0]["detail"]["error"]
    p.unlink()


def main() -> int:
    print("SCHEMA")
    check("valid spec", t_spec_valid)
    check("rejects unknown entry set", t_spec_bad_entry)
    check("rejects dangling criterion", t_spec_bad_criterion_ref)
    check("rejects inverted window", t_window_order)
    check("rationale required", t_rationale_required)
    check("planner output -> spec", t_planner_to_spec)
    check("critic revise needs issues", t_critic_revise_needs_issues)

    print("\nACTION PROTOCOL")
    check("plain json", t_extract_plain)
    check("fenced json", t_extract_fenced)
    check("prose-wrapped json", t_extract_prose_wrapped)
    check("garbage raises", t_extract_garbage)
    check("allowed action", t_parse_action_allowed)
    check("unknown action rejected", t_parse_action_rejects_unknown)
    check("tsv formatting", t_tsv)

    print("\nFAKE CLIENT")
    check("deterministic", t_fake_deterministic)
    check("fail-first path", t_fake_fail_first)
    check("raises on demand", t_fake_raises)

    print("\nPROVENANCE")
    check("run log totals", t_runlog)
    check("records exceptions", t_runlog_records_exception)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
