"""Component 2 tests: vocabulary search and concept set resolution.

Builds a small synthetic vocabulary with a known hierarchy, so the tests run
anywhere -- no Athena, no Eunomia needed. Every expected answer is hand-checked.

Hierarchy used:
    100 Peptic ulcer
      +-- 110 Gastric ulcer
      |     +-- 111 Acute gastric ulcer with haemorrhage
      +-- 120 Duodenal ulcer
    200 Motion sickness          (unrelated, used for exclusions)
    300 Aspirin                  (Drug domain)
      +-- 310 Aspirin 81 MG Oral Tablet
    400 ASA                      (non-standard source code, maps to 300)

Run:  python -m tests.test_component2
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import duckdb

from src.tools import vocab
from src.tools.resolver import resolve_items, restrict_to_standard

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
    # id, name, domain, vocab, class, standard, invalid_reason
    (100, "Peptic ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (110, "Gastric ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (111, "Acute gastric ulcer with haemorrhage", "Condition", "SNOMED",
     "Clinical Finding", "S", None),
    (120, "Duodenal ulcer", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (200, "Motion sickness", "Condition", "SNOMED", "Clinical Finding", "S", None),
    (300, "Aspirin", "Drug", "RxNorm", "Ingredient", "S", None),
    (310, "Aspirin 81 MG Oral Tablet", "Drug", "RxNorm", "Clinical Drug",
     "S", None),
    (400, "ASA", "Drug", "NDC", "Source Code", None, None),
    (500, "Peptic ulcer, deprecated", "Condition", "SNOMED", "Clinical Finding",
     "S", "D"),
]

ANCESTORS = [
    # ancestor, descendant, min_levels, max_levels   (self-rows included)
    (100, 100, 0, 0), (100, 110, 1, 1), (100, 111, 2, 2), (100, 120, 1, 1),
    (110, 110, 0, 0), (110, 111, 1, 1),
    (111, 111, 0, 0), (120, 120, 0, 0), (200, 200, 0, 0),
    (300, 300, 0, 0), (300, 310, 1, 1), (310, 310, 0, 0),
]

SYNONYMS = [(100, "stomach ulcer"), (120, "ulcer of duodenum")]
RELATIONSHIPS = [(400, 300, "Maps to")]


def build_db(path: Path) -> None:
    con = duckdb.connect(path.as_posix())
    con.execute("""CREATE TABLE concept(
        concept_id BIGINT, concept_name VARCHAR, domain_id VARCHAR,
        vocabulary_id VARCHAR, concept_class_id VARCHAR,
        standard_concept VARCHAR, invalid_reason VARCHAR)""")
    con.executemany("INSERT INTO concept VALUES (?,?,?,?,?,?,?)", CONCEPTS)

    con.execute("""CREATE TABLE concept_ancestor(
        ancestor_concept_id BIGINT, descendant_concept_id BIGINT,
        min_levels_of_separation INT, max_levels_of_separation INT)""")
    con.executemany("INSERT INTO concept_ancestor VALUES (?,?,?,?)", ANCESTORS)

    con.execute("""CREATE TABLE concept_synonym(
        concept_id BIGINT, concept_synonym_name VARCHAR)""")
    con.executemany("INSERT INTO concept_synonym VALUES (?,?)", SYNONYMS)

    con.execute("""CREATE TABLE concept_relationship(
        concept_id_1 BIGINT, concept_id_2 BIGINT, relationship_id VARCHAR)""")
    con.executemany("INSERT INTO concept_relationship VALUES (?,?,?)",
                    RELATIONSHIPS)
    con.close()


# --- search -----------------------------------------------------------------

def t_search_exact_first(con):
    rows = vocab.search_concepts(con, "peptic ulcer", domain="Condition")
    assert rows, "expected matches"
    assert rows[0][0] == 100, f"exact match should rank first, got {rows[0]}"


def t_search_all_tokens(con):
    ids = {r[0] for r in vocab.search_concepts(con, "gastric ulcer")}
    assert 110 in ids and 111 in ids, ids
    assert 120 not in ids, "duodenal ulcer has no 'gastric' token"


def t_search_synonym(con):
    ids = {r[0] for r in vocab.search_concepts(con, "stomach ulcer")}
    assert 100 in ids, "synonyms must be searchable"


def t_search_domain_filter(con):
    ids = {r[0] for r in vocab.search_concepts(con, "aspirin", domain="Condition")}
    assert ids == set(), f"domain filter failed: {ids}"
    ids = {r[0] for r in vocab.search_concepts(con, "aspirin", domain="Drug")}
    assert 300 in ids


def t_search_excludes_invalid(con):
    ids = {r[0] for r in vocab.search_concepts(con, "peptic ulcer")}
    assert 500 not in ids, "deprecated concepts must not be returned"


def t_search_excludes_nonstandard(con):
    ids = {r[0] for r in vocab.search_concepts(con, "asa")}
    assert 400 not in ids, "non-standard concepts hidden when standard_only"
    ids = {r[0] for r in vocab.search_concepts(con, "asa", standard_only=False)}
    assert 400 in ids


def t_search_empty_query(con):
    assert vocab.search_concepts(con, "   ") == []


# --- hierarchy --------------------------------------------------------------

def t_descendants(con):
    total, rows = vocab.get_descendants(con, 100)
    assert total == 3, f"peptic ulcer has 3 descendants, got {total}"
    assert {r[0] for r in rows} == {110, 111, 120}


def t_ancestors(con):
    ids = {r[0] for r in vocab.get_ancestors(con, 111, max_levels=2)}
    assert ids == {100, 110}, ids
    ids = {r[0] for r in vocab.get_ancestors(con, 111, max_levels=1)}
    assert ids == {110}, ids


def t_get_concept(con):
    row = vocab.get_concept(con, 310)
    assert row[1] == "Aspirin 81 MG Oral Tablet"
    assert row[5] == "S" and row[6] is True


def t_map_to_standard(con):
    rows = vocab.map_to_standard(con, 400)
    assert [r[0] for r in rows] == [300], rows


# --- resolver ---------------------------------------------------------------

def t_resolve_with_descendants(con):
    ids = resolve_items(con, [
        {"concept_id": 100, "include_descendants": True, "is_excluded": False}])
    assert ids == {100, 110, 111, 120}, ids


def t_resolve_without_descendants(con):
    ids = resolve_items(con, [
        {"concept_id": 100, "include_descendants": False, "is_excluded": False}])
    assert ids == {100}, ids


def t_resolve_exclusion(con):
    """Peptic ulcer with descendants, minus gastric ulcer with descendants."""
    ids = resolve_items(con, [
        {"concept_id": 100, "include_descendants": True, "is_excluded": False},
        {"concept_id": 110, "include_descendants": True, "is_excluded": True},
    ])
    assert ids == {100, 120}, ids


def t_resolve_exclusion_leaf_only(con):
    ids = resolve_items(con, [
        {"concept_id": 100, "include_descendants": True, "is_excluded": False},
        {"concept_id": 110, "include_descendants": False, "is_excluded": True},
    ])
    assert ids == {100, 111, 120}, ids


def t_resolve_empty(con):
    assert resolve_items(con, []) == set()


def t_restrict_to_standard(con):
    ids = restrict_to_standard(con, {100, 400, 500, 300})
    assert ids == {100, 300}, f"non-standard and invalid must be dropped: {ids}"


# --- dispatch ---------------------------------------------------------------

def t_call_tool_search(con):
    out = vocab.call_tool(con, "search_concepts",
                          {"query": "peptic ulcer", "domain": "Condition"})
    assert out.splitlines()[0].startswith("id\tname"), out
    assert "100" in out


def t_call_tool_no_match(con):
    out = vocab.call_tool(con, "search_concepts", {"query": "zzzz nonsense"})
    assert "no matches" in out


def t_call_tool_bad_concept(con):
    out = vocab.call_tool(con, "get_concept", {"concept_id": 999999})
    assert "does not exist" in out


def t_call_tool_bad_args(con):
    out = vocab.call_tool(con, "get_concept", {})
    assert out.startswith("tool error"), out


def t_call_tool_unknown(con):
    assert "unknown tool" in vocab.call_tool(con, "drop_table", {})


def t_descendant_count_header(con):
    out = vocab.call_tool(con, "get_descendants", {"concept_id": 100})
    assert out.startswith("total_descendants=3"), out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test_vocab.duckdb"
        build_db(db)
        con = duckdb.connect(db.as_posix(), read_only=True)
        try:
            print("SEARCH")
            for name, fn in [
                ("exact match ranks first", t_search_exact_first),
                ("all tokens must match", t_search_all_tokens),
                ("synonyms searchable", t_search_synonym),
                ("domain filter", t_search_domain_filter),
                ("excludes invalid concepts", t_search_excludes_invalid),
                ("excludes non-standard by default", t_search_excludes_nonstandard),
                ("empty query safe", t_search_empty_query),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nHIERARCHY")
            for name, fn in [
                ("descendant count and sample", t_descendants),
                ("ancestors by level", t_ancestors),
                ("get_concept fields", t_get_concept),
                ("maps to standard", t_map_to_standard),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nRESOLVER")
            for name, fn in [
                ("include descendants", t_resolve_with_descendants),
                ("exclude descendants", t_resolve_without_descendants),
                ("exclusion with descendants", t_resolve_exclusion),
                ("exclusion leaf only", t_resolve_exclusion_leaf_only),
                ("empty item list", t_resolve_empty),
                ("restrict to standard", t_restrict_to_standard),
            ]:
                check(name, lambda f=fn: f(con))

            print("\nTOOL DISPATCH")
            for name, fn in [
                ("search returns tsv", t_call_tool_search),
                ("no-match message", t_call_tool_no_match),
                ("missing concept message", t_call_tool_bad_concept),
                ("bad args handled", t_call_tool_bad_args),
                ("unknown tool handled", t_call_tool_unknown),
                ("descendant header", t_descendant_count_header),
            ]:
                check(name, lambda f=fn: f(con))
        finally:
            con.close()

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
