import json, glob, os
from collections import defaultdict
import numpy as np

def build_latex_table(run_dir, outfile):
    # data[task][config] = list of f1 scores
    data = defaultdict(lambda: defaultdict(list))
    for r in glob.glob(f"{run_dir}/**/report.json", recursive=True):
        try:
            with open(r, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            cfg = d.get("configuration") or "C1"
            task = d.get("task_id") or "Unknown"
            
            # Safely extract F1
            m = d.get("metrics", {}).get("v2", {})
            f1 = m.get("full", {}).get("f1")
            if f1 is None:
                f1 = m.get("f1")
            if f1 is not None:
                try:
                    f1 = float(f1)
                except (ValueError, TypeError):
                    f1 = 0.0
            else:
                f1 = 0.0
                
            data[task][cfg].append(f1)
        except Exception:
            pass

    configs = ["C1", "C2", "C3", "C4"]
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Cohort Extraction F1 Performance Across Configurations (" + os.path.basename(run_dir) + ")}",
        "\\label{tab:" + os.path.basename(run_dir) + "}",
        "\\begin{tabular}{lcccc}",
        "\\hline",
        "\\textbf{Task ID} & \\textbf{C1} & \\textbf{C2} & \\textbf{C3} & \\textbf{C4} \\\\",
        "\\hline"
    ]
    
    cfg_scores = {c: [] for c in configs}
    all_tasks = sorted(list(data.keys()))
    
    for t in all_tasks:
        row = [t]
        for c in configs:
            scores = data[t].get(c, [])
            if scores:
                val = scores[0]
                cfg_scores[c].append(val)
                row.append(f"{val:.3f}")
            else:
                row.append("-")
        lines.append(" & ".join(row) + " \\\\")

    lines.append("\\hline")
    # Mean summary row
    mean_row = ["\\textbf{Mean}"]
    for c in configs:
        sc = cfg_scores[c]
        if sc:
            mean_row.append(f"\\textbf{{{np.mean(sc):.3f}}}")
        else:
            mean_row.append("-")
    lines.append(" & ".join(mean_row) + " \\\\")
    
    lines.extend([
        "\\hline",
        "\\end{tabular}",
        "\\end{table}"
    ])
    
    with open(outfile, "w", encoding="utf-8") as out:
        out.write("\n".join(lines))
    print(f"Successfully generated: {outfile}")

if __name__ == "__main__":
    for rdir in ["results/codex_20261025/runs/official_v53_qwen7b", "results/codex_20261025/runs/official_neuro_qwen7b"]:
        if os.path.exists(rdir):
            build_latex_table(rdir, f"{rdir}/table.tex")
