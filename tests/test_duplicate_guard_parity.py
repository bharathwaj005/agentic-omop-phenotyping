import json

import duckdb

from src.agents.concept import run_concept_agent
from src.llm.base import LLMResult, estimate_tokens
from src.pipelines.budget import Budget
from src.pipelines.single_agent import run_single_agent
from src.schema.spec import ConceptSet
from src.tools import vocab


class DuplicateReplyClient:
    def __init__(self):
        self.messages = []
        self.calls = 0

    def complete(self, system, messages, model, max_tokens=1500):
        self.messages.append(list(messages))
        self.calls += 1
        text = json.dumps({"action": "search_concepts", "args": {"query": "parity"}})
        return LLMResult(text, estimate_tokens(str(messages)), estimate_tokens(text), 0, model)


def test_single_agent_bounds_finalization_while_concept_agent_stops_duplicates(monkeypatch):
    monkeypatch.setattr(vocab, "call_tool", lambda *args: "one matching concept")
    single_client, concept_client = DuplicateReplyClient(), DuplicateReplyClient()
    con = duckdb.connect(":memory:")
    single = run_single_agent(single_client, "fake-model", "synthetic question", con,
                              budget=Budget())
    concept = run_concept_agent(
        concept_client, "fake-model",
        ConceptSet(name="set", domain="Condition", description="synthetic"),
        con, budget=Budget())

    assert single.status == concept.status == "failed"
    assert "repeated identical vocabulary tool call requested after bounded finalization" in single.reason
    assert concept.reason == "repeated identical vocabulary tool call after 2 corrective retries"
    assert single.tracker.tool_calls == concept.tool_calls == 1
    assert single_client.calls == 4
    assert concept_client.calls == 3
    single_correction = single_client.messages[3][-1]["content"]
    concept_correction = concept_client.messages[2][-1]["content"]
    assert "FINALIZATION REQUIRED" in single_correction
    assert "FINALIZATION REQUIRED" not in concept_correction
    con.close()
