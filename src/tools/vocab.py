"""Vocabulary tools: the only way agents touch the OMOP vocabulary.

Design notes that matter for the paper:

* These are DETERMINISTIC functions. The LLM decides *what* to look up; the
  database does the looking. That is what keeps token use low and results
  reproducible.
* Every function returns COMPACT output (TSV, capped rows). Verbose JSON tool
  results are the main hidden cost in agentic systems.
* The code runs against the full Athena vocabulary OR, during development,
  against Eunomia's small built-in vocabulary. Same table names, same SQL, so
  nothing changes when the real vocabulary arrives.

CLI:
    python -m src.tools.vocab "peptic ulcer" --domain Condition
"""

from __future__ import annotations

import argparse
import re
import sys
from contextlib import contextmanager
from typing import Optional

import duckdb

from src import paths
from src.llm.base import rows_to_tsv

MAX_ROWS = 15
_TOKEN = re.compile(r"[a-z0-9]+")


# --- connection -------------------------------------------------------------

@contextmanager
def open_source(prefer_full: bool = True):
    """Open the best available vocabulary.

    Returns (connection, label). Label is 'athena' or 'eunomia' and is recorded
    in the run log, so every result states which vocabulary produced it.
    """
    if prefer_full and paths.VOCAB_DB.exists():
        db, label = paths.VOCAB_DB, "athena"
    elif paths.EUNOMIA_DB.exists():
        db, label = paths.EUNOMIA_DB, "eunomia"
    else:
        raise FileNotFoundError(
            "No vocabulary available. Load Eunomia (python -m src.db.load_eunomia) "
            "or Athena (python -m src.db.load_vocab)."
        )
    con = duckdb.connect(db.as_posix(), read_only=True)
    try:
        con.execute(f"SET threads={paths.DUCKDB_THREADS}")
        yield con, label
    finally:
        con.close()


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def _has(con, name: str) -> bool:
    return name in _tables(con)


# --- search -----------------------------------------------------------------

def search_concepts(con, query: str, domain: Optional[str] = None,
                    standard_only: bool = True, limit: int = MAX_ROWS,
                    vocabulary: Optional[str] = None) -> list[tuple]:
    """Find concepts whose name or synonym contains every token of the query.

    Ranking: exact name match first, then shorter names (more general concepts
    sit higher in the hierarchy and are usually what a phenotype wants).
    Returns rows of (concept_id, concept_name, vocabulary_id, concept_class_id,
    n_descendants).
    """
    tokens = _TOKEN.findall((query or "").lower())
    if not tokens:
        return []

    use_search_table = _has(con, "concept_search")
    has_desc_count = _has(con, "descendant_count")
    has_synonym = _has(con, "concept_synonym")

    params: list = []
    where = ["c.invalid_reason IS NULL"]
    if standard_only:
        where.append("c.standard_concept = 'S'")
    if domain:
        where.append("c.domain_id = ?")
        params.append(domain)
    if vocabulary:
        where.append("c.vocabulary_id = ?")
        params.append(vocabulary)

    if use_search_table:
        term_src = "concept_search s"
        join = "JOIN concept c ON c.concept_id = s.concept_id"
        term_col = "s.term"
    elif has_synonym:
        term_src = """(
            SELECT concept_id, lower(concept_name) AS term FROM concept
            UNION ALL
            SELECT concept_id, lower(concept_synonym_name) FROM concept_synonym
        ) s"""
        join = "JOIN concept c ON c.concept_id = s.concept_id"
        term_col = "s.term"
    else:
        term_src = "(SELECT concept_id, lower(concept_name) AS term FROM concept) s"
        join = "JOIN concept c ON c.concept_id = s.concept_id"
        term_col = "s.term"

    for t in tokens:
        where.append(f"{term_col} LIKE ?")
        params.append(f"%{t}%")

    desc_select = ("COALESCE(d.n_descendants, 0)" if has_desc_count else "NULL")
    desc_join = ("LEFT JOIN descendant_count d ON d.concept_id = c.concept_id"
                 if has_desc_count else "")

    exact = " ".join(tokens)
    sql = f"""
        SELECT DISTINCT c.concept_id, c.concept_name, c.vocabulary_id,
               c.concept_class_id, {desc_select} AS n_descendants
        FROM {term_src}
        {join}
        {desc_join}
        WHERE {' AND '.join(where)}
        ORDER BY (lower(c.concept_name) = ?) DESC,
                 length(c.concept_name) ASC,
                 c.concept_id ASC
        LIMIT ?
    """
    params.extend([exact, limit])
    return con.execute(sql, params).fetchall()


def get_concept(con, concept_id: int) -> Optional[tuple]:
    """Full record for one concept: id, name, domain, vocab, class, standard,
    valid flag, descendant count."""
    has_desc_count = _has(con, "descendant_count")
    desc_select = ("COALESCE(d.n_descendants, 0)" if has_desc_count else "NULL")
    desc_join = ("LEFT JOIN descendant_count d ON d.concept_id = c.concept_id"
                 if has_desc_count else "")
    return con.execute(
        f"""
        SELECT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id,
               c.concept_class_id, c.standard_concept,
               (c.invalid_reason IS NULL) AS is_valid,
               {desc_select} AS n_descendants
        FROM concept c {desc_join}
        WHERE c.concept_id = ?
        """,
        [concept_id],
    ).fetchone()


def get_descendants(con, concept_id: int, limit: int = MAX_ROWS
                    ) -> tuple[int, list[tuple]]:
    """(total_count, sample_rows). The count matters more than the sample:
    it tells the agent whether including descendants is safe or reckless."""
    if not _has(con, "concept_ancestor"):
        return 0, []
    total = con.execute(
        """SELECT count(*) FROM concept_ancestor
           WHERE ancestor_concept_id = ? AND descendant_concept_id <> ?""",
        [concept_id, concept_id],
    ).fetchone()[0]
    rows = con.execute(
        """
        SELECT c.concept_id, c.concept_name, c.concept_class_id,
               ca.min_levels_of_separation
        FROM concept_ancestor ca
        JOIN concept c ON c.concept_id = ca.descendant_concept_id
        WHERE ca.ancestor_concept_id = ? AND ca.descendant_concept_id <> ?
          AND c.invalid_reason IS NULL
        ORDER BY ca.min_levels_of_separation ASC, length(c.concept_name) ASC
        LIMIT ?
        """,
        [concept_id, concept_id, limit],
    ).fetchall()
    return total, rows


def get_ancestors(con, concept_id: int, max_levels: int = 2,
                  limit: int = MAX_ROWS) -> list[tuple]:
    """Parents and grandparents -- lets an agent climb to a broader concept."""
    if not _has(con, "concept_ancestor"):
        return []
    return con.execute(
        """
        SELECT c.concept_id, c.concept_name, c.concept_class_id,
               ca.min_levels_of_separation
        FROM concept_ancestor ca
        JOIN concept c ON c.concept_id = ca.ancestor_concept_id
        WHERE ca.descendant_concept_id = ? AND ca.ancestor_concept_id <> ?
          AND ca.min_levels_of_separation <= ?
          AND c.invalid_reason IS NULL
        ORDER BY ca.min_levels_of_separation ASC, length(c.concept_name) ASC
        LIMIT ?
        """,
        [concept_id, concept_id, max_levels, limit],
    ).fetchall()


def map_to_standard(con, concept_id: int, limit: int = MAX_ROWS) -> list[tuple]:
    """Follow 'Maps to' from a non-standard concept to its standard target."""
    if not _has(con, "concept_relationship"):
        return []
    return con.execute(
        """
        SELECT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id
        FROM concept_relationship r
        JOIN concept c ON c.concept_id = r.concept_id_2
        WHERE r.concept_id_1 = ? AND r.relationship_id = 'Maps to'
          AND c.standard_concept = 'S' AND c.invalid_reason IS NULL
        LIMIT ?
        """,
        [concept_id, limit],
    ).fetchall()


# --- agent-facing dispatch --------------------------------------------------

HEADERS = {
    "search_concepts": ["id", "name", "vocab", "class", "n_desc"],
    "get_concept": ["id", "name", "domain", "vocab", "class", "standard",
                    "valid", "n_desc"],
    "get_descendants": ["id", "name", "class", "levels"],
    "get_ancestors": ["id", "name", "class", "levels"],
    "map_to_standard": ["id", "name", "domain", "vocab"],
}

ALLOWED_ACTIONS = set(HEADERS) | {"final"}


def call_tool(con, action: str, args: dict) -> str:
    """Run one tool and return compact TSV for the prompt.

    Errors come back as text rather than exceptions, so the agent can recover
    (a wrong concept id should cost one turn, not the whole run).
    """
    try:
        if action == "search_concepts":
            rows = search_concepts(
                con,
                query=args.get("query", ""),
                domain=args.get("domain"),
                vocabulary=args.get("vocabulary"),
                standard_only=args.get("standard_only", True),
                limit=min(int(args.get("limit", MAX_ROWS)), MAX_ROWS),
            )
            if not rows:
                return (
                    "no matches in the requested domain and vocabulary filters; "
                    "try a shorter, clinically justified query while preserving "
                    "the domain and standard-concept constraint"
                )
            return rows_to_tsv(rows, HEADERS[action], MAX_ROWS)

        if action == "get_concept":
            row = get_concept(con, int(args["concept_id"]))
            if row is None:
                return f"concept {args['concept_id']} does not exist"
            return rows_to_tsv([row], HEADERS[action], 1)

        if action == "get_descendants":
            total, rows = get_descendants(con, int(args["concept_id"]))
            head = f"total_descendants={total}"
            if not rows:
                return head + "\n(none)"
            return head + "\n" + rows_to_tsv(rows, HEADERS[action], MAX_ROWS)

        if action == "get_ancestors":
            rows = get_ancestors(con, int(args["concept_id"]),
                                 int(args.get("max_levels", 2)))
            return (rows_to_tsv(rows, HEADERS[action], MAX_ROWS) if rows
                    else "(no ancestors found)")

        if action == "map_to_standard":
            rows = map_to_standard(con, int(args["concept_id"]))
            return (rows_to_tsv(rows, HEADERS[action], MAX_ROWS) if rows
                    else "(no standard mapping found)")

        return f"unknown tool {action!r}"
    except (KeyError, TypeError, ValueError) as e:
        return f"tool error: {type(e).__name__}: {e}"
    except duckdb.Error as e:
        return f"database error: {e}"


TOOL_DOC = """\
search_concepts   args: query (required), domain, vocabulary, limit
get_concept       args: concept_id
get_descendants   args: concept_id      -> total count plus a sample
get_ancestors     args: concept_id, max_levels
map_to_standard   args: concept_id      -> standard concept for a source code
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Search the OMOP vocabulary")
    ap.add_argument("query")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--descendants", type=int, default=None,
                    help="show descendants of this concept id instead")
    args = ap.parse_args()

    with open_source() as (con, label):
        print(f"vocabulary source: {label}\n")
        if args.descendants:
            print(call_tool(con, "get_concept",
                            {"concept_id": args.descendants}))
            print()
            print(call_tool(con, "get_descendants",
                            {"concept_id": args.descendants}))
        else:
            print(call_tool(con, "search_concepts",
                            {"query": args.query, "domain": args.domain}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
