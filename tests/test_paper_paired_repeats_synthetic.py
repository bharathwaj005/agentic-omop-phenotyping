from scripts.make_paper_outputs import _tables


def test_paper_pairing_aggregates_synthetic_repeats_by_task():
    reports = [
        {"task_id": "T01", "configuration": "C1", "status": "success",
         "metrics": {"v2": {"full": {"f1": .2}}}},
        {"task_id": "T01", "configuration": "C1", "status": "success",
         "metrics": {"v2": {"full": {"f1": .8}}}},
        {"task_id": "T01", "configuration": "C2", "status": "success",
         "metrics": {"v2": {"full": {"f1": .4}}}},
    ]
    result = _tables(reports, {})
    row = next(r for r in result["table_5_paired"]
               if r["configuration_a"] == "C1" and r["configuration_b"] == "C2"
               and r["metric"] == "full.f1")
    assert row["n_paired_tasks"] == 1
    assert round(row["mean_delta_a_minus_b"], 8) == .1
