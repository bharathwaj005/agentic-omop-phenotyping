import os, sys, glob, json, math, random, shutil, warnings
import duckdb
import numpy as np
import pandas as pd
from collections import defaultdict
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT_DIR = "results/analysis_tier1_20261028"
os.makedirs(OUT_DIR, exist_ok=True)

# -------------------------------------------------------------
# TASK 0: RESULT SELECTION & AUDIT
# -------------------------------------------------------------
print("--> Executing Task 0: Result Selection & Reconciliation")
V53_DIR = "results/codex_20261025/runs/official_v53_qwen7b"
NEURO_DIR = "results/codex_20261025/runs/official_neuro_qwen7b"
INFRA_FAIL_KEYWORDS = ["RemoteDisconnected", "connection refused", "ConnectionResetError", "500 Server Error", "502 Bad Gateway", "503 Service Unavailable", "preflight requires", "Killed"]

configs = ["C1", "C2", "C3", "C4"]
v53_tasks = [f"T{i:02d}" for i in range(1, 21)]
neuro_tasks = [f"N{i:02d}" for i in range(1, 13)]

final_rows = []
infra_failures_no_retry = []

def audit_directory(track_name, task_list, base_dir):
    for t in task_list:
        for c in configs:
            target_prefix = f"{t}_{c}"
            run_dirs = sorted([d for d in glob.glob(f"{base_dir}/{target_prefix}*") if os.path.isdir(d)])
            
            if not run_dirs:
                final_rows.append({
                    "track": track_name, "task_id": t, "configuration": c,
                    "chosen_report": "", "attempt_paths": "", "status": "missing",
                    "failure_reason": "Run directory not created", "failure_class": "infrastructure",
                    "selection_rationale": "Missing directory; no attempt run"
                })
                continue
            
            first_dir = run_dirs[0]
            first_rep = os.path.join(first_dir, "report.json")
            chosen_dir = first_dir
            selection_rationale = "First attempt selected"
            
            rep_data = {}
            if os.path.exists(first_rep):
                with open(first_rep) as fp:
                    try: rep_data = json.load(fp)
                    except: pass
            
            first_status = rep_data.get("status", "failed" if not rep_data else "completed")
            first_reason = rep_data.get("reason") or rep_data.get("error") or ""
            
            is_infra = any(k in str(first_reason) for k in INFRA_FAIL_KEYWORDS) or first_status == "failed"
            if len(run_dirs) > 1 and is_infra:
                chosen_dir = run_dirs[-1]
                selection_rationale = "Retry chosen because attempt 1 suffered infrastructure/fatal error"
            
            chosen_rep = os.path.join(chosen_dir, "report.json")
            cdata = {}
            if os.path.exists(chosen_rep):
                with open(chosen_rep) as fp:
                    try: cdata = json.load(fp)
                    except: pass
            
            status = cdata.get("status", "unknown")
            reason = cdata.get("reason") or cdata.get("error") or ""
            
            fclass = "none"
            if status != "completed" and status != "success":
                r_str = str(reason).lower()
                if any(k.lower() in r_str for k in INFRA_FAIL_KEYWORDS): fclass = "infrastructure"
                elif "timeout" in r_str or "deadline" in r_str: fclass = "timeout"
                elif "schema" in r_str or "pydantic" in r_str or "jsondecode" in r_str or "validationerror" in r_str: fclass = "structured_output_schema_error"
                elif "validator" in r_str or "repair" in r_str: fclass = "validator_repair_loop_unconverged"
                elif "domain" in r_str: fclass = "domain_mismatch"
                elif "tool" in r_str or "search" in r_str or "repeated" in r_str: fclass = "repeated_tool_call_loop"
                elif "budget" in r_str: fclass = "llm_budget_exhausted"
                else: fclass = "infrastructure"
                
                if len(run_dirs) == 1 and fclass == "infrastructure":
                    infra_failures_no_retry.append(f"{t}_{c} ({track_name})")

            final_rows.append({
                "track": track_name, "task_id": t, "configuration": c,
                "chosen_report": chosen_rep, "attempt_paths": ";".join(run_dirs),
                "status": status, "failure_reason": str(reason), "failure_class": fclass,
                "selection_rationale": selection_rationale
            })

audit_directory("v53", v53_tasks, V53_DIR)
audit_directory("neuro", neuro_tasks, NEURO_DIR)

df_final = pd.DataFrame(final_rows)
df_final.to_csv(f"{OUT_DIR}/final_runs.csv", index=False)

# -------------------------------------------------------------
# TASK 1 & 2: EXTRACT METRICS DIRECTLY FROM REPORT REPOSITORIES
# -------------------------------------------------------------
print("--> Executing Tasks 1 & 2: Loading Concept Metrics from Verified Reports")

metric_rows = []
for idx, r in df_final.iterrows():
    rep_path = r["chosen_report"]
    f1, rec, prec, jacc = None, None, None, None
    status = r["status"]
    
    if rep_path and os.path.exists(rep_path):
        with open(rep_path) as fp:
            try:
                d = json.load(fp)
                m = d.get("metrics", {}).get("v2", {})
                full = m.get("full", {})
                f1_val = full.get("f1", m.get("f1"))
                rec_val = full.get("recall", m.get("recall"))
                prec_val = full.get("precision", m.get("precision"))
                jacc_val = full.get("jaccard", m.get("jaccard"))

                if f1_val is not None: f1 = float(f1_val)
                if rec_val is not None: rec = float(rec_val)
                if prec_val is not None: prec = float(prec_val)
                if jacc_val is not None: jacc = float(jacc_val)
            except Exception:
                pass

    metric_rows.append({
        "track": r["track"], "task_id": r["task_id"], "configuration": r["configuration"],
        "status": status,
        "exact_f1": f1,
        "exact_recall": rec,
        "exact_precision": prec,
        "exact_jaccard": jacc,
        "exact_f1_zero_imputed": f1 if f1 is not None else 0.0
    })

df_metrics = pd.DataFrame(metric_rows)
df_metrics.to_csv(f"{OUT_DIR}/concept_metrics.csv", index=False)

# -------------------------------------------------------------
# TASK 5: FAILURE TAXONOMY
# -------------------------------------------------------------
print("--> Executing Task 5: Failure Taxonomy Breakdown")
fail_df = df_final[df_final["failure_class"] != "none"]
fail_summary = fail_df.groupby(["track", "configuration", "failure_class"]).size().reset_index(name="count")
fail_summary.to_csv(f"{OUT_DIR}/failure_taxonomy.csv", index=False)

# -------------------------------------------------------------
# TASK 6: COST METRICS
# -------------------------------------------------------------
print("--> Executing Task 6: Cost Metrics")
cost_rows = []
for idx, r in df_final.iterrows():
    rep = r["chosen_report"]
    wall_s, llm_calls, in_tok, out_tok = 0.0, 0, 0, 0
    if rep and os.path.exists(rep):
        with open(rep) as fp:
            try:
                d = json.load(fp)
                t = d.get("timings", {})
                wall_s = float(t.get("llm_time_s") or (t.get("eval_duration_ms", 0)/1000.0) or 0.0)
                out_tok = int(t.get("eval_count") or t.get("tokens_generated") or 0)
                in_tok = int(t.get("prompt_eval_count") or 0)
                llm_calls = int(d.get("llm_calls", 1 if out_tok > 0 else 0))
            except Exception: pass

    cost_rows.append({
        "track": r["track"], "task_id": r["task_id"], "configuration": r["configuration"],
        "wall_seconds": wall_s, "llm_calls": llm_calls, "input_tokens": in_tok, "output_tokens": out_tok
    })

df_cost = pd.DataFrame(cost_rows)
df_cost.to_csv(f"{OUT_DIR}/cost_metrics.csv", index=False)

# -------------------------------------------------------------
# TASK 7: STATISTICAL TESTING & WILCOXON COMPARISONS
# -------------------------------------------------------------
print("--> Executing Task 7: Statistics & Paired Wilcoxon Tests")
merged = pd.merge(df_metrics, df_cost, on=["track", "task_id", "configuration"])
stat_results = []
rng = np.random.default_rng(20261028)

for track in ["v53", "neuro"]:
    df_t = merged[merged["track"] == track]
    tasks_avail = sorted(df_t["task_id"].unique())
    
    # Task 7 rule: Pair only on tasks scored in both
    c1_map = {row["task_id"]: row["exact_f1"] for _, row in df_t[df_t["configuration"] == "C1"].iterrows()}
    
    for c_other in ["C2", "C3", "C4"]:
        co_map = {row["task_id"]: row["exact_f1"] for _, row in df_t[df_t["configuration"] == c_other].iterrows()}
        
        paired = []
        for tid in tasks_avail:
            v1 = c1_map.get(tid)
            v2 = co_map.get(tid)
            if v1 is not None and v2 is not None:
                paired.append((v1, v2))
                
        n = len(paired)
        if n > 0:
            a = np.array([p[0] for p in paired])
            b = np.array([p[1] for p in paired])
            diffs = a - b
            wins = int(np.sum(diffs > 0))
            ties = int(np.sum(diffs == 0))
            losses = int(np.sum(diffs < 0))
            
            pval = 1.0
            if np.any(diffs != 0) and n >= 5:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        stat, pval = stats.wilcoxon(diffs)
                except Exception:
                    pval = 1.0
            
            boot_means = [np.mean(rng.choice(diffs, size=n, replace=True)) for _ in range(10000)]
            ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])
            
            stat_results.append({
                "track": track, "comparison": f"C1 vs {c_other}", "n": n,
                "wins": wins, "ties": ties, "losses": losses,
                "median_diff": float(np.median(diffs)), "mean_diff": float(np.mean(diffs)),
                "ci_95_low": float(ci_low), "ci_95_high": float(ci_high), "p_value": float(pval)
            })

df_stats = pd.DataFrame(stat_results)
df_stats.to_csv(f"{OUT_DIR}/paired_statistical_tests.csv", index=False)

# -------------------------------------------------------------
# TASK 8: VISUALIZATIONS & FACT SHEET
# -------------------------------------------------------------
print("--> Executing Task 8: Generating Plots & Fact Sheet")

fig, axs = plt.subplots(1, 2, figsize=(12, 5))
for idx, trk in enumerate(["v53", "neuro"]):
    sub = merged[merged["track"] == trk]
    cfg_f1 = [sub[(sub["configuration"] == c) & (sub["exact_f1"].notna())]["exact_f1"].values for c in configs]
    try:
        axs[idx].boxplot(cfg_f1, tick_labels=configs)
    except TypeError:
        axs[idx].boxplot(cfg_f1, labels=configs)
    axs[idx].set_title(f"Exact F1 on Scored Tasks ({trk.upper()})")
    axs[idx].set_ylabel("F1 Score")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/f1_boxplots.png", dpi=300)
plt.savefig(f"{OUT_DIR}/f1_boxplots.svg")
plt.close()

fig, axs = plt.subplots(1, 2, figsize=(12, 5))
for idx, trk in enumerate(["v53", "neuro"]):
    sub = merged[merged["track"] == trk]
    for c in configs:
        c_sub = sub[(sub["configuration"] == c) & (sub["exact_f1"].notna())]
        axs[idx].scatter(c_sub["wall_seconds"], c_sub["exact_f1"], label=c, alpha=0.7)
    axs[idx].set_title(f"Cost-Quality Pareto ({trk.upper()})")
    axs[idx].set_xlabel("Wall Seconds")
    axs[idx].set_ylabel("F1 Score")
    axs[idx].legend()
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/pareto_cost_quality.png", dpi=300)
plt.savefig(f"{OUT_DIR}/pareto_cost_quality.svg")
plt.close()

with open(f"{OUT_DIR}/RESULTS_FACTS.md", "w") as fp:
    fp.write("# Tier-1 Analysis Empirical Fact Sheet\n\n")
    fp.write("All numbers computed from official runs under results/codex_20261025/.\n\n")
    for trk in ["v53", "neuro"]:
        fp.write(f"### Track: {trk.upper()}\n")
        sub = df_metrics[df_metrics["track"] == trk]
        for c in configs:
            sc = sub[(sub["configuration"] == c) & (sub["exact_f1"].notna())]["exact_f1"]
            sc_all = sub[sub["configuration"] == c]["exact_f1_zero_imputed"]
            mean_scored = f"{sc.mean():.4f} (std = {sc.std():.4f}, n = {len(sc)})" if len(sc) > 0 else "N/A"
            mean_all = f"{sc_all.mean():.4f} (n = {len(sc_all)})"
            fp.write(f"- **{c}**: Scored-only F1 = {mean_scored} | Failures=0 F1 = {mean_all}\n")
        fp.write("\n")

print("\n=== PIPELINE RUN COMPLETE ===")
