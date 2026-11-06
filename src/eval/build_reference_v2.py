"""Build complete multi-arm reference files without touching the frozen v1 set.

The v2 files are written under the repository's ``tasks/reference_v2`` folder.
The Athena database is opened through the shared read-only resolver.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from src import paths
from src.eval.build_reference import build_one
from src.eval.extract_reference import cohorts_dir, parse_definition
from src.tools.resolver import open_vocab

V53 = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967, 1048, 1064,
       1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]
NEURO = [255, 33, 863, 552, 1026, 287, 535, 1079, 544, 235, 1080, 550,
         229, 1066]
TASKS = {cid: f"T{i:02d}" for i, cid in enumerate(V53, 1)}
FROZEN = (Path("results/benchmark_design/V5_3_FREEZE"), paths.REFERENCE_DIR)


def _safe_output(output: Path) -> Path:
    resolved = output.resolve()
    for frozen in FROZEN:
        frozen_resolved = frozen.resolve()
        if resolved == frozen_resolved or frozen_resolved in resolved.parents:
            raise ValueError(f"refusing frozen reference output: {resolved}")
    return resolved


def build(output: Path | None = None) -> dict:
    out = _safe_output(output or (Path(__file__).resolve().parents[2] / "tasks/reference_v2"))
    out.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys(V53 + NEURO))
    source = cohorts_dir()
    v1_dir = Path(__file__).resolve().parents[2] / "tasks/reference"
    reports = {"all_concept_mismatches": [], "entry_not_superset": [],
               "single_arm_entry_mismatches": []}
    manifest = {"reference_version": "v2", "cohorts": {}}
    with open_vocab(read_only=True) as con:
        for cid in ids:
            target = out / f"{cid}.json"
            if target.exists():
                raise FileExistsError(f"refusing to overwrite {target}")
            raw = parse_definition(source / f"{cid}.json")
            if raw is None:
                raise ValueError(f"could not parse cohort definition {cid}")
            ref = build_one(con, raw, TASKS.get(cid, f"N{cid}"))
            ref["reference_version"] = "v2"
            v1_path = v1_dir / f"{cid}.json"
            if v1_path.exists():
                v1 = json.loads(v1_path.read_text())
                v2all, v1all = set(ref["all_concept_ids"]), set(v1["all_concept_ids"])
                if v2all != v1all:
                    reports["all_concept_mismatches"].append(cid)
                if not set(ref["entry_concept_ids"]).issuperset(v1["entry_concept_ids"]):
                    reports["entry_not_superset"].append(cid)
                if len(ref["entry_arms"]) <= 1 and set(ref["entry_concept_ids"]) != set(v1["entry_concept_ids"]):
                    reports["single_arm_entry_mismatches"].append(cid)
            content = json.dumps(ref, indent=1) + "\n"
            target.write_text(content)
            manifest["cohorts"][str(cid)] = hashlib.sha256(content.encode()).hexdigest()
    manifest_path = out / "MANIFEST.json"
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (out / "SANITY.json").write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n")
    print(json.dumps(reports, indent=2, sort_keys=True))
    return reports


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
