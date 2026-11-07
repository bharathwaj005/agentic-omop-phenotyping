import duckdb

from src.eval.build_reference import build_one


def test_v2_builder_resolves_union_of_entry_arms_with_synthetic_duckdb():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE concept(concept_id INTEGER, standard_concept VARCHAR, invalid_reason VARCHAR)")
    con.execute("INSERT INTO concept VALUES (1, 'S', NULL), (2, 'S', NULL)")
    con.execute("CREATE TABLE concept_ancestor(ancestor_concept_id INTEGER, descendant_concept_id INTEGER)")
    raw = {
        "cohort_id": "1", "entry_codeset_ids": ["0", "1"],
        "entry_arms": [{"domain": "Condition", "codeset_id": "0"},
                       {"domain": "Drug", "codeset_id": "1"}],
        "concept_sets": {"0": {"name": "a", "items": [{"concept_id": 1}]},
                         "1": {"name": "b", "items": [{"concept_id": 2}]}}
    }
    result = build_one(con, raw, "T01")
    assert result["entry_concept_ids"] == [1, 2]
    assert result["all_concept_ids"] == [1, 2]
    assert result["entry_arms"] == raw["entry_arms"]
    con.close()
