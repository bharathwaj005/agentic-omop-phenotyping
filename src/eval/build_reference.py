"""Stage 2 of the reference standard: resolve expressions into concept ID sets.

Requires vocab.duckdb (the Athena load). Reads the selected tasks from
tasks.jsonl and writes one resolved reference file per task.

Output: HDD/tasks/reference/<task_id>.json

Usage:
    python -m src.eval.build_reference
    python -m src.eval.build_reference --all     # every parsed cohort
"""

from __future__ import annotations

import argparse
import json
import sys

from src import paths
from src.tools.resolver import open_vocab, resolve_items, restrict_to_standard


def load_tasks() -> list[dict]:
    if not paths.TASKS_FILE.exists():
        raise FileNotFoundError(
            f"{paths.TASKS_FILE} not found. Create tasks.jsonl first "
            "(one JSON object per line, with task_id and phenotype_library_id)."
        )
    tasks = []
    for line in paths.TASKS_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    return tasks


def build_one(con, raw: dict, task_id: str) -> dict:
    # New raw records carry all entry arms; legacy records fall back to one.
    entry_keys = raw.get("entry_codeset_ids")
    if not entry_keys:
        arms = raw.get("entry_arms") or []
        entry_keys = list(dict.fromkeys(a["codeset_id"] for a in arms))
    if not entry_keys and raw.get("entry_codeset_id") is not None:
        entry_keys = [raw["entry_codeset_id"]]
    entry_keys = [str(k) for k in entry_keys]
    resolved_sets: dict[str, list[int]] = {}
    all_ids: set[int] = set()

    for cs_id, cs in raw["concept_sets"].items():
        ids = resolve_items(con, cs["items"])
        ids = restrict_to_standard(con, ids)
        resolved_sets[cs_id] = sorted(ids)
        all_ids |= ids

    entry_ids: set[int] = set()
    for entry_key in entry_keys:
        entry_ids.update(resolved_sets.get(entry_key, []))
    entry_arms = raw.get("entry_arms") or []
    return {
        "reference_version": "2.0" if entry_arms or len(entry_keys) > 1 else "1.0-compatible",
        "task_id": task_id,
        "cohort_id": raw["cohort_id"],
        # Legacy fields point to the first arm; plural fields are authoritative.
        "entry_codeset_id": entry_keys[0] if entry_keys else None,
        "entry_codeset_ids": entry_keys,
        "entry_domains": sorted({a.get("domain") for a in entry_arms if a.get("domain")}),
        "entry_arms": entry_arms,
        "entry_domain": raw.get("entry_domain"),
        "entry_concept_ids": sorted(entry_ids),
        "entry_concept_ids_by_codeset": {
            key: resolved_sets.get(key, []) for key in entry_keys
        },
        "all_concept_ids": sorted(all_ids),
        "concept_sets": {
            cs_id: {"name": raw["concept_sets"][cs_id]["name"],
                    "concept_ids": ids}
            for cs_id, ids in resolved_sets.items()
        },
        "counts": {"entry": len(entry_ids), "all": len(all_ids)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="resolve every parsed cohort, not just tasks.jsonl")
    ap.add_argument("--v2", action="store_true",
                    help="read reference_raw_v2/ and write reference_v2/; preserve v1")
    args = ap.parse_args()

    raw_dir = paths.TASKS_DIR / ("reference_raw_v2" if args.v2 else "reference_raw")
    out_dir = paths.TASKS_DIR / "reference_v2" if args.v2 else paths.REFERENCE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        targets = [(f.stem, f) for f in sorted(raw_dir.glob("*.json"))]
    else:
        targets = []
        for t in load_tasks():
            cid = str(t["phenotype_library_id"])
            targets.append((t["task_id"], raw_dir / f"{cid}.json"))

    written = missing = 0
    with open_vocab() as con:
        for task_id, raw_file in targets:
            if not raw_file.exists():
                print(f"  [miss] {task_id}: {raw_file.name} not parsed")
                missing += 1
                continue
            raw = json.loads(raw_file.read_text())
            ref = build_one(con, raw, task_id)
            (out_dir / f"{task_id}.json").write_text(json.dumps(ref, indent=1))
            print(f"  [ok]   {task_id:<8} cohort {raw['cohort_id']:<6} "
                  f"entry={ref['counts']['entry']:>5} concepts  "
                  f"all={ref['counts']['all']:>5}")
            written += 1

    print(f"\nwritten: {written}   missing: {missing}")
    print(f"output : {out_dir}")

    if written:
        empties = [f.stem for f in out_dir.glob("*.json")
                   if json.loads(f.read_text())["counts"]["entry"] == 0]
        if empties:
            print(f"\nWARNING: empty entry sets for {empties}. "
                  "Their vocabularies may be missing from the Athena download.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
