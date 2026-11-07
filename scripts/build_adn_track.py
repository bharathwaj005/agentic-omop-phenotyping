#!/usr/bin/env python3
"""Build the Alzheimer's-disease neuroinflammation (ADN) extension track.

Twelve tasks, each anchored on a peer-reviewed or published OHDSI Phenotype Library
cohort, covering AD/dementia outcomes, acute brain dysfunction, systemic inflammatory
and autoimmune exposures, anti-inflammatory treatment initiation, infection and
depression. References are built with the project's own reference builder, exactly
like the V5.3 and neurological tracks.

Writes:
  tasks/adn/ad_neuroinflammation_questions.jsonl   (blinded questions, task_id A01..A12)
  tasks/adn/task_list.csv                          (task_id -> OHDSI cohort_id, name)
  tasks/reference_adn/<cohort_id>.json             (reference concept sets)
  tasks/cohort_definitions/<cohort_id>.json        (source Circe definitions)

This track is an EXTENSION and is not part of the submitted results.

    .venv/bin/python scripts/build_adn_track.py
"""
from __future__ import annotations

import csv
import json
import shutil
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.eval.build_reference import build_one
from src.eval.extract_reference import cohorts_dir, parse_definition
from src.tools.resolver import concept_names, open_vocab

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/OHDSI/PhenotypeLibrary/main/inst/cohorts/{}.json"

TASKS = [
    ("A01", 100, "[P][R] Alzheimer's disease", "outcome",
     "Identify patients with Alzheimer's disease based on diagnosis evidence."),
    ("A02", 651, "[P][R] Dementia", "outcome",
     "Identify patients with dementia of any type based on diagnosis evidence."),
    ("A03", 95, "[P] Delirium", "acute brain dysfunction",
     "Identify patients with an episode of delirium based on diagnosis evidence."),
    ("A04", 457, "[P][R] Rheumatoid arthritis", "inflammatory exposure",
     "Identify patients with rheumatoid arthritis based on diagnosis evidence."),
    ("A05", 1070, "[P] New users of JAK inhibitors nested in Rheumatoid arthritis", "anti-inflammatory treatment",
     "Identify patients with rheumatoid arthritis who are new users of Janus kinase (JAK) inhibitors."),
    ("A06", 1069, "[P] New users of TNFa inhibitors nested in Crohns disease", "anti-inflammatory treatment",
     "Identify patients with Crohn's disease who are new users of tumor necrosis factor alpha inhibitors."),
    ("A07", 629, "[P][R] Inflammatory bowel disease", "inflammatory exposure",
     "Identify patients with inflammatory bowel disease, including Crohn's disease or ulcerative colitis, based on diagnosis evidence."),
    ("A08", 475, "[P][R] Psoriasis", "inflammatory exposure",
     "Identify patients with psoriasis based on diagnosis evidence."),
    ("A09", 509, "[P][R] Systemic lupus erythematosus", "autoimmune exposure",
     "Identify patients with systemic lupus erythematosus based on diagnosis evidence."),
    ("A10", 463, "[P][R] Sepsis", "systemic inflammation",
     "Identify patients with sepsis based on diagnosis evidence."),
    ("A11", 615, "[P][R] Herpes simplex", "infection (viral hypothesis)",
     "Identify patients with herpes simplex virus infection based on diagnosis evidence."),
    ("A12", 699, "[P][R] Major Depressive Disorder", "neuropsychiatric comorbidity",
     "Identify patients with major depressive disorder based on diagnosis evidence."),
]


def definition(cid: int, dest: Path) -> Path:
    target = dest / f"{cid}.json"
    if target.exists():
        return target
    src = cohorts_dir() / f"{cid}.json"
    if src.exists():
        shutil.copy2(src, target)
    else:
        with urllib.request.urlopen(RAW.format(cid), timeout=60) as r:
            target.write_bytes(r.read())
    return target


def main() -> int:
    adn = ROOT / "tasks" / "adn"; ref_dir = ROOT / "tasks" / "reference_adn"; defs = ROOT / "tasks" / "cohort_definitions"
    for d in (adn, ref_dir, defs):
        d.mkdir(parents=True, exist_ok=True)
    problems = 0
    with open_vocab(read_only=True) as con, \
         (adn / "ad_neuroinflammation_questions.jsonl").open("w") as q, \
         (adn / "task_list.csv").open("w", newline="") as tl:
        w = csv.writer(tl); w.writerow(["task_id", "cohort_id", "cohort_name", "role"])
        for tid, cid, name, role, question in TASKS:
            raw = parse_definition(definition(cid, defs))
            if raw is None:
                print(f"  {tid} cohort {cid}: could not parse definition"); problems += 1; continue
            ref = build_one(con, raw, tid)
            ref["reference_version"] = "adn-v1"
            (ref_dir / f"{cid}.json").write_text(json.dumps(ref, indent=1) + "\n")
            q.write(json.dumps({"task_id": tid, "question": question}) + "\n")
            w.writerow([tid, cid, name, role])
            sample = [n for _, n, *_ in concept_names(con, set(ref["entry_concept_ids"]), limit=3)] if ref["entry_concept_ids"] else []
            ok = len(ref["all_concept_ids"]) > 0
            problems += 0 if ok else 1
            print(f"  {tid} cohort {cid:>5} entry={len(ref['entry_concept_ids']):>5} all={len(ref['all_concept_ids']):>5} "
                  f"{'OK ' if ok else 'EMPTY'} | {name[:45]:45} | e.g. {'; '.join(s[:30] for s in sample)}")
    print(f"ADN track: {len(TASKS)} tasks, {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
