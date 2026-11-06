"""Compute pairwise entry concept Jaccard gates for frozen task candidates."""
from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/codex_20261024"
V53 = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967, 1048, 1064,
       1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]
NEURO = [255, 33, 863, 552, 1026, 287, 535, 1079, 544, 235, 1080, 550,
         229, 1066]
THRESHOLD = 0.90


def jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def main() -> int:
    refs = ROOT / "tasks/reference_v2"
    sets = {cid: set(json.loads((refs / f"{cid}.json").read_text())["entry_concept_ids"])
            for cid in V53 + NEURO}
    pairs = []
    for group, candidates in (("V5.3", list(itertools.combinations(V53, 2))),
                              ("Neuro_vs_V5.3", [(n, v) for n in NEURO for v in V53]),
                              ("Neuro_vs_Neuro", list(itertools.combinations(NEURO, 2)))):
        for left, right in candidates:
            pairs.append({"group": group, "cohort_a": left, "cohort_b": right,
                          "jaccard": jaccard(sets[left], sets[right]),
                          "threshold_flag": jaccard(sets[left], sets[right]) >= THRESHOLD})
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "gate_v2_pairs.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    flagged = [p for p in pairs if p["threshold_flag"]]
    max_pair = max(pairs, key=lambda p: p["jaccard"])
    summary = ["V2 entry concept Jaccard gate", f"Pairs evaluated: {len(pairs)}",
               f"Threshold: {THRESHOLD:.2f}",
               f"Maximum: {max_pair['jaccard']:.6f} (cohorts {max_pair['cohort_a']} and {max_pair['cohort_b']}; {max_pair['group']})",
               f"Frozen v1 maximum: 0.722222; v2 change: {max_pair['jaccard'] - 0.722222:+.6f}",
               f"Pairs >= threshold: {len(flagged)}"]
    summary.extend(f"{p['group']}: {p['cohort_a']} vs {p['cohort_b']} = {p['jaccard']:.6f}" for p in flagged)
    (OUT / "gate_v2_summary.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
