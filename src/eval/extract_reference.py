"""Stage 1 of the reference standard: parse Circe JSON into flat expressions.

This needs no vocabulary, so it can run before the Athena download arrives.
Stage 2 (build_reference.py) resolves these expressions into concept ID sets.

Output: one JSON per cohort in  HDD/tasks/reference_raw/<cohortId>.json

Usage:
    python -m src.eval.extract_reference
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src import paths

DOMAIN_KEYS = {
    "ConditionOccurrence": "Condition",
    "DrugExposure": "Drug",
    "ProcedureOccurrence": "Procedure",
    "Measurement": "Measurement",
    "Observation": "Observation",
    "VisitOccurrence": "Visit",
    "DeviceExposure": "Device",
}


def cohorts_dir() -> Path:
    return paths.PHENOTYPE_LIBRARY / "PhenotypeLibrary" / "inst" / "cohorts"


def parse_items(concept_set: dict) -> list[dict]:
    """Flatten one concept set expression into plain item dicts."""
    items = []
    for it in concept_set.get("expression", {}).get("items", []):
        concept = it.get("concept", {}) or {}
        cid = concept.get("CONCEPT_ID")
        if cid is None:
            continue
        items.append({
            "concept_id": int(cid),
            "concept_name": concept.get("CONCEPT_NAME"),
            "domain_id": concept.get("DOMAIN_ID"),
            "standard_concept": concept.get("STANDARD_CONCEPT"),
            "include_descendants": bool(it.get("includeDescendants", False)),
            "include_mapped": bool(it.get("includeMapped", False)),
            "is_excluded": bool(it.get("isExcluded", False)),
        })
    return items


def entry_codesets(definition: dict) -> list[dict]:
    """Collect every primary-criteria codeset as an alternative entry arm.

    Circe stores the primary criteria as a list of alternatives. Preserve each
    codeset/domain pair rather than silently selecting only the first one.
    """
    crit_list = definition.get("PrimaryCriteria", {}).get("CriteriaList", []) or []
    arms: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for crit in crit_list:
        for key, body in crit.items():
            if key not in DOMAIN_KEYS or not isinstance(body, dict):
                continue
            cid = body.get("CodesetId")
            if cid is None:
                continue
            pair = (str(int(cid)), key)
            if pair in seen:
                continue
            seen.add(pair)
            arms.append({
                "codeset_id": pair[0],
                "domain_key": key,
                "domain": DOMAIN_KEYS[key],
            })
    return arms


def parse_definition(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
    except Exception:                                    # noqa: BLE001
        return None

    concept_sets = {}
    for cs in d.get("ConceptSets", []) or []:
        cs_id = cs.get("id")
        if cs_id is None:
            continue
        concept_sets[str(cs_id)] = {
            "name": cs.get("name", ""),
            "items": parse_items(cs),
        }

    crit_list = d.get("PrimaryCriteria", {}).get("CriteriaList", []) or []
    arms = entry_codesets(d)
    entry_key = arms[0]["codeset_id"] if arms else None
    entry_domain = arms[0]["domain"] if arms else None
    entry_domains = sorted({arm["domain"] for arm in arms})

    return {
        "cohort_id": path.stem,
        # Legacy first-arm fields retained for consumers of old raw references.
        "entry_codeset_id": entry_key,
        "entry_domain": entry_domain,
        "entry_domains": entry_domains,
        "entry_arms": arms,
        "entry_codeset_ids": list(dict.fromkeys(a["codeset_id"] for a in arms)),
        "n_concept_sets": len(concept_sets),
        "n_inclusion_rules": len(d.get("InclusionRules", []) or []),
        "n_primary_criteria": len(crit_list),
        "observation_window_prior":
            d.get("PrimaryCriteria", {})
             .get("ObservationWindow", {})
             .get("PriorDays", 0),
        "first_occurrence_only":
            (d.get("PrimaryCriteria", {}).get("PrimaryCriteriaLimit", {})
              .get("Type") == "First"),
        "concept_sets": concept_sets,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", action="store_true",
                    help="write multi-entry references to reference_raw_v2/ without touching v1")
    args = ap.parse_args()
    paths.ensure_dirs()
    src_dir = cohorts_dir()
    if not src_dir.exists():
        print(f"ERROR: {src_dir} not found. Clone the Phenotype Library first.")
        return 1

    out_dir = paths.TASKS_DIR / ("reference_raw_v2" if args.v2 else "reference_raw")
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(src_dir.glob("*.json"))
    ok = skipped = 0
    for f in files:
        parsed = parse_definition(f)
        if parsed is None:
            skipped += 1
            continue
        if not parsed["concept_sets"] or parsed["entry_codeset_id"] is None:
            skipped += 1
            continue
        (out_dir / f"{parsed['cohort_id']}.json").write_text(
            json.dumps(parsed, indent=1)
        )
        ok += 1

    print(f"parsed  : {ok}")
    print(f"skipped : {skipped}  (no concept sets or no resolvable entry event)")
    print(f"output  : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
