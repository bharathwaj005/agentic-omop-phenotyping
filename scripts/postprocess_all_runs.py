import json, glob, os, sys

def summarize_run(run_dir, track_name):
    print(f"\n==================== {track_name} AUDIT ====================")
    if not os.path.exists(run_dir):
        print(f"Path does not exist: {run_dir}")
        return
    reports = glob.glob(f"{run_dir}/**/report.json", recursive=True)
    print(f"Total Completed Reports: {len(reports)}")
    scores = []
    for r in reports:
        try:
            with open(r, "r", encoding="utf-8") as f:
                d = json.load(f)
            task = d.get("task_id") or "Unknown"
            cfg = d.get("configuration") or "Unknown"
            m = d.get("metrics", {}).get("v2", {})
            f1 = m.get("full", {}).get("f1") or m.get("f1") or 0.0
            rec = m.get("full", {}).get("recall") or m.get("recall") or 0.0
            prec = m.get("full", {}).get("precision") or m.get("precision") or 0.0
            scores.append((cfg, task, f1, rec, prec))
        except Exception:
            pass
    if scores:
        print(f"{'Config':<8} {'Task':<8} {'F1':<10} {'Recall':<10} {'Precision':<10}")
        print("-" * 50)
        for cfg, task, f1, rec, prec in sorted(scores)[:25]:
            print(f"{cfg:<8} {task:<8} {f1:<10.4f} {rec:<10.4f} {prec:<10.4f}")
        if len(scores) > 25:
            print(f"... and {len(scores) - 25} more completed runs.")

if __name__ == "__main__":
    v53_dir = "results/codex_20261025/runs/official_v53_qwen7b"
    neuro_dir = "results/codex_20261025/runs/official_neuro_qwen7b"
    summarize_run(v53_dir, "V5.3 OFFICIAL TRACK")
    summarize_run(neuro_dir, "NEURO OFFICIAL TRACK")
