import pandas as pd
import numpy as np

OUT_DIR = "results/analysis_tier1_20261028"

def df_to_markdown_simple(df):
    headers = list(df.columns)
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(val) for val in row.values) + " |")
    return "\n".join(lines)

# 1. Clean Paired Statistics Table
df_stats = pd.read_csv(f"{OUT_DIR}/paired_statistical_tests.csv")
df_metrics = pd.read_csv(f"{OUT_DIR}/concept_metrics.csv")

clean_stats = []
rng = np.random.default_rng(20261028)

for track in ["v53", "neuro"]:
    sub = df_metrics[df_metrics["track"] == track]
    tasks = sorted(sub["task_id"].unique())
    c1_scores = {r["task_id"]: r["exact_f1"] for _, r in sub[sub["configuration"] == "C1"].iterrows()}
    
    for c_other in ["C2", "C3", "C4"]:
        co_scores = {r["task_id"]: r["exact_f1"] for _, r in sub[sub["configuration"] == c_other].iterrows()}
        diffs = []
        for t in tasks:
            v1 = c1_scores.get(t)
            v2 = co_scores.get(t)
            if pd.notna(v1) and pd.notna(v2):
                diffs.append(v1 - v2)
        diffs = np.array(diffs)
        n = len(diffs)
        wins = int(np.sum(diffs > 0))
        ties = int(np.sum(diffs == 0))
        losses = int(np.sum(diffs < 0))
        
        med = float(np.median(diffs)) if n > 0 else 0.0
        mean = float(np.mean(diffs)) if n > 0 else 0.0
        
        if n > 0:
            boot = [np.mean(rng.choice(diffs, size=n, replace=True)) for _ in range(10000)]
            ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
        else:
            ci_low, ci_high = 0.0, 0.0
            
        prev_row = df_stats[(df_stats["track"] == track) & (df_stats["comparison"] == f"C1 vs {c_other}")]
        p_val = prev_row["p_value"].values[0] if len(prev_row) > 0 and pd.notna(prev_row["p_value"].values[0]) else 1.0
        
        clean_stats.append({
            "Track": track.upper(),
            "Comparison": f"C1 vs {c_other}",
            "N (Paired)": n,
            "Wins": wins,
            "Ties": ties,
            "Losses": losses,
            "Median Diff": f"{med:.4f}",
            "Mean Diff": f"{mean:.4f}",
            "95% CI": f"[{ci_low:.4f}, {ci_high:.4f}]",
            "p-value": f"{p_val:.4f}" if p_val < 0.05 else "n.s."
        })

df_clean_stats = pd.DataFrame(clean_stats)
df_clean_stats.to_csv(f"{OUT_DIR}/paired_tests_formatted.csv", index=False)
with open(f"{OUT_DIR}/paired_tests_formatted.md", "w") as fp:
    fp.write(df_to_markdown_simple(df_clean_stats) + "\n")
print("Saved: paired_tests_formatted.csv and .md")

# 2. Main Results Summary Table
summary_rows = []
for trk in ["v53", "neuro"]:
    sub = df_metrics[df_metrics["track"] == trk]
    for c in ["C1", "C2", "C3", "C4"]:
        sc = sub[(sub["configuration"] == c) & sub["exact_f1"].notna()]
        all_c = sub[sub["configuration"] == c]
        
        summary_rows.append({
            "Track": trk.upper(),
            "Config": c,
            "Completed": f"{len(sc)} / {len(all_c)}",
            "Mean F1 (Scored)": f"{sc['exact_f1'].mean():.4f} ± {sc['exact_f1'].std():.3f}" if len(sc) > 0 else "-",
            "Mean F1 (All=0)": f"{all_c['exact_f1_zero_imputed'].mean():.4f}",
            "Mean Recall": f"{sc['exact_recall'].mean():.4f}" if len(sc) > 0 else "-",
            "Mean Precision": f"{sc['exact_precision'].mean():.4f}" if len(sc) > 0 else "-"
        })

df_summary = pd.DataFrame(summary_rows)
df_summary.to_csv(f"{OUT_DIR}/table_main_results.csv", index=False)
with open(f"{OUT_DIR}/table_main_results.md", "w") as fp:
    fp.write(df_to_markdown_simple(df_summary) + "\n")
print("Saved: table_main_results.csv and .md")
