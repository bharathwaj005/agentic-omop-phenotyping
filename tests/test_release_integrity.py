"""Release-integrity tests: the frozen results, references and tables are mutually consistent."""
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "analysis_tier1_20261028"
N_TASKS = {"v53": 20, "neuro": 12}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_final_runs_has_exactly_the_128_design_runs():
    fr = pd.read_csv(RES / "final_runs.csv")
    keys = set(zip(fr.task_id, fr.configuration))
    expected = {(f"T{i:02d}", c) for i in range(1, 21) for c in ("C1", "C2", "C3", "C4")} | \
               {(f"N{i:02d}", c) for i in range(1, 13) for c in ("C1", "C2", "C3", "C4")}
    assert len(fr) == 128
    assert keys == expected


def test_t10_uses_the_adhd_cohort_1025_everywhere():
    for f in ("scripts/run_benchmark.py", "src/eval/build_reference_v2.py"):
        text = (ROOT / f).read_text()
        v53 = re.search(r"V53\s*=\s*\[([^\]]+)\]", text).group(1)
        ids = [int(x) for x in re.findall(r"\d+", v53)]
        assert ids[9] == 1025, f"{f}: T10 maps to {ids[9]}"
        assert 967 not in ids, f"{f}: still lists cohort 967 (4-point MACE)"
    ref = json.loads((ROOT / "tasks/reference_v2/1025.json").read_text())
    assert 438409 in ref["entry_concept_ids"], "ADHD concept 438409 missing from the T10 reference"


def test_runner_reference_manifest_hash_matches_file():
    text = (ROOT / "scripts/run_benchmark.py").read_text()
    pinned = re.search(r'REFERENCE_V2_SHA256 = "([0-9a-f]{64})"', text).group(1)
    assert pinned == _sha(ROOT / "tasks/reference_v2/MANIFEST.json")


def test_every_task_has_a_reference_file():
    runs = pd.read_csv(RES / "final_runs.csv")
    for _, r in runs.drop_duplicates(["track", "task_id"]).iterrows():
        rep = json.loads((ROOT / r.chosen_report).read_text())
        cohort = "1025" if r.task_id == "T10" else str(rep["cohort_id"])
        assert (ROOT / "tasks/reference_v2" / f"{cohort}.json").is_file(), (r.task_id, cohort)


def test_table1_all0_means_reproduce_from_concept_metrics():
    m = pd.read_csv(RES / "concept_metrics.csv")
    t = pd.read_csv(RES / "table_main_results.csv")
    for _, row in t.iterrows():
        track = "v53" if row["Track"].upper().startswith("V") else "neuro"
        g = m[(m.track == track) & (m.configuration == row["Config"])]
        all0 = g.exact_f1.fillna(0).sum() / N_TASKS[track]
        assert float(row["Mean F1 (All=0)"]) == pytest.approx(all0, abs=6e-5), (track, row["Config"])


def test_table2_has_raw_and_holm_p_for_every_comparison():
    t = pd.read_csv(RES / "paired_tests_formatted.csv")
    assert len(t) == 6
    for col in ("p (raw)", "p (Holm)"):
        assert col in t.columns
        assert t[col].astype(float).between(0, 1).all()
    assert (t["p (Holm)"].astype(float) >= t["p (raw)"].astype(float) - 1e-12).all()


def test_t10_rescore_record_is_reproducible():
    over = json.loads((RES / "rescore_overrides_T10.json").read_text())
    assert over, "T10 re-scoring record is empty"
    assert all(v["resolution_reproduced"] for v in over.values())
    assert all(v["reference"].endswith("1025.json") for v in over.values())
