"""Concept set resolution against the OMOP vocabulary.

The SAME function resolves the reference standard and the system's output, so
the comparison is fair. Do not write a second copy of this logic anywhere.

Semantics (mirrors OHDSI concept set expressions):
  include item concept          -> always
  include_descendants           -> add all descendants via concept_ancestor
  is_excluded                   -> the item and (if flagged) its descendants
                                   are removed AFTER all inclusions
  include_mapped                -> NOT applied; see note below

Note on include_mapped: mapped source concepts are non-standard codes that map
INTO the concept. Our agents work with standard concepts only, so resolving
mapped concepts in the reference would penalise the system for something it is
not asked to produce. We resolve standard concepts only, on both sides, and
state this in the paper's Methods.

Usage:
    from src.tools.resolver import resolve_items, open_vocab
    with open_vocab() as con:
        ids = resolve_items(con, items)
"""

from __future__ import annotations

from contextlib import contextmanager

import duckdb

from src import paths


@contextmanager
def open_vocab(read_only: bool = True):
    """Open the vocabulary database with memory-safe settings."""
    if not paths.VOCAB_DB.exists():
        raise FileNotFoundError(
            f"{paths.VOCAB_DB} not found. Run: python -m src.db.load_vocab"
        )
    con = duckdb.connect(paths.VOCAB_DB.as_posix(), read_only=read_only)
    try:
        if not read_only:
            paths.configure(con)
        else:
            con.execute(f"SET threads={paths.DUCKDB_THREADS}")
        yield con
    finally:
        con.close()


def _expand(con, concept_ids: list[int], with_descendants: bool) -> set[int]:
    if not concept_ids:
        return set()
    ids = set(int(c) for c in concept_ids)
    if not with_descendants:
        return ids
    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"""
        SELECT DISTINCT descendant_concept_id
        FROM concept_ancestor
        WHERE ancestor_concept_id IN ({placeholders})
        """,
        list(ids),
    ).fetchall()
    return ids | {r[0] for r in rows}


def resolve_items(con, items: list[dict]) -> set[int]:
    """Resolve a list of concept set items into a set of concept IDs."""
    inc_desc, inc_plain, exc_desc, exc_plain = [], [], [], []
    for it in items:
        cid = it.get("concept_id")
        if cid is None:
            continue
        bucket = (
            (exc_desc if it.get("include_descendants") else exc_plain)
            if it.get("is_excluded")
            else (inc_desc if it.get("include_descendants") else inc_plain)
        )
        bucket.append(int(cid))

    included = _expand(con, inc_desc, True) | _expand(con, inc_plain, False)
    excluded = _expand(con, exc_desc, True) | _expand(con, exc_plain, False)
    return included - excluded


def restrict_to_standard(con, concept_ids: set[int]) -> set[int]:
    """Keep only valid standard concepts. Used for fair comparison."""
    if not concept_ids:
        return set()
    ids = list(concept_ids)
    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"""
        SELECT concept_id FROM concept
        WHERE concept_id IN ({placeholders})
          AND standard_concept = 'S' AND invalid_reason IS NULL
        """,
        ids,
    ).fetchall()
    return {r[0] for r in rows}


def concept_names(con, concept_ids: set[int], limit: int = 50) -> list[tuple]:
    """Names for a sample of concept IDs -- for adjudication exports."""
    if not concept_ids:
        return []
    ids = list(concept_ids)[:limit]
    placeholders = ",".join("?" * len(ids))
    return con.execute(
        f"""
        SELECT concept_id, concept_name, domain_id, vocabulary_id
        FROM concept WHERE concept_id IN ({placeholders})
        ORDER BY concept_name
        """,
        ids,
    ).fetchall()


if __name__ == "__main__":
    # Smoke test: atrial fibrillation with descendants, minus nothing.
    demo = [{"concept_id": 313217, "include_descendants": True,
             "is_excluded": False}]
    with open_vocab() as con:
        ids = resolve_items(con, demo)
        std = restrict_to_standard(con, ids)
        print(f"resolved        : {len(ids):,} concepts")
        print(f"standard only   : {len(std):,} concepts")
        for row in concept_names(con, std, limit=5):
            print("   ", row)
