import csv
import json

from scripts import make_paper_outputs as paper


def test_paper_outputs_use_synthetic_fixture_and_write_all_formats(tmp_path, monkeypatch):
    root = tmp_path
    v53 = root / "results/benchmark_design/V5_3_FREEZE"
    neuro = root / "results/benchmark_design/NEURO_FREEZE"
    v53.mkdir(parents=True); neuro.mkdir(parents=True)
    with (v53 / "BENCHMARK_FINAL20_V5_3_FINAL.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["cohort_id", "cohort_name", "complexity", "entry_domain", "eunomia_evaluable"])
        writer.writeheader(); writer.writerow({"cohort_id": 134, "cohort_name": "synthetic", "complexity": "simple", "entry_domain": "Condition", "eunomia_evaluable": "True"})
    with (neuro / "task_list.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["task_id", "cohort_id", "cohort_name", "complexity", "entry_domains", "patient_evaluable"])
        writer.writeheader(); writer.writerow({"task_id": "N01", "cohort_id": 255, "cohort_name": "synthetic neuro", "complexity": "medium", "entry_domains": "Drug", "patient_evaluable": "false"})
    monkeypatch.setattr(paper, "ROOT", root)
    reports_dir = root / "runs"; reports_dir.mkdir()
    report = {"task_id": "T01", "cohort_id": "134", "track": "V5.3 core",
              "complexity": "simple", "configuration": "C1", "status": "success",
              "wall_seconds": 4, "llm_calls": 2, "tool_calls": 1,
              "input_tokens": 5, "output_tokens": 4,
              "metrics": {"v2": {"full": {"precision": .7, "recall": .8, "f1": .75, "jaccard": .6},
                                   "entry": {"precision": .6, "recall": .5, "f1": .55, "jaccard": .4}}}}
    (reports_dir / "report.json").write_text(json.dumps(report))
    out = root / "paper"
    paper.generate([reports_dir], out)
    for name in ("table_1_composition", "table_2_main_results", "table_3_cost",
                 "table_4_track_complexity", "table_5_paired", "table_6_failures"):
        assert (out / f"{name}.csv").is_file()
        assert (out / f"{name}.md").is_file()
    for name in ("figure_1_recall", "figure_2_cost_vs_recall"):
        assert (out / f"{name}.png").is_file()
        assert (out / f"{name}.svg").is_file()
