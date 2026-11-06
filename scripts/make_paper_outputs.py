"""Build manuscript tables and figures from supplied per-run report folders."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import wilcoxon

from scripts.analyze_results import _load_reports, _metric, analyze

ROOT = Path(__file__).resolve().parents[1]
V53 = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967, 1048, 1064,
       1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]


def _write_table(out: Path, name: str, rows: list[dict], note: str) -> None:
    fields = list(rows[0]) if rows else ["note"]
    with (out / f"{name}.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows or [{"note": note}])
    lines = [f"# {name.replace('_', ' ').title()}", "", f"n and failures: {note}", ""]
    if rows:
        lines.append("| " + " | ".join(fields) + " |")
        lines.append("| " + " | ".join("---" for _ in fields) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(f, "")) for f in fields) + " |")
    (out / f"{name}.md").write_text("\n".join(lines) + "\n")


def _composition() -> tuple[list[dict], dict[str, dict]]:
    v53_path = ROOT / "results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv"
    neuro_path = ROOT / "results/benchmark_design/NEURO_FREEZE/task_list.csv"
    if not v53_path.is_file() or not neuro_path.is_file():
        raise FileNotFoundError("both V5.3 and Neuro freeze task-list files are required")
    with v53_path.open(newline="") as f:
        v53_rows = list(csv.DictReader(f))
    with neuro_path.open(newline="") as f:
        neuro_rows = list(csv.DictReader(f))
    metadata = {}
    v53_tasks = {str(cid): f"T{i:02d}" for i, cid in enumerate(V53, 1)}
    for row in v53_rows:
        task_id = v53_tasks.get(str(row.get("cohort_id")))
        if task_id is None:
            raise ValueError(f"unexpected cohort in V5.3 freeze file: {row.get('cohort_id')}")
        row = dict(row)
        row["task_id"], row["track"] = task_id, "V5.3 core"
        metadata[task_id] = row
    for row in neuro_rows:
        row = dict(row)
        row["track"] = "Neuro"
        metadata[row["task_id"]] = row
    grouped = defaultdict(list)
    for row in metadata.values():
        grouped[(row["track"], str(row.get("complexity", "unknown")))].append(row)
    table = []
    for (track, complexity), rows in sorted(grouped.items()):
        domains = sorted({d for r in rows for d in str(r.get("entry_domains", r.get("entry_domain", "unknown"))).split("|") if d})
        evaluable = sum(str(r.get("patient_evaluable", r.get("eunomia_evaluable", ""))).lower() in {"true", "1"} for r in rows)
        table.append({"track": track, "complexity": complexity,
                      "tasks": len(rows), "cohorts": len({r.get("cohort_id") for r in rows}),
                      "entry_domains": ", ".join(domains),
                      "patient_evaluable_n": evaluable,
                      "patient_not_evaluable_n": len(rows) - evaluable})
    return table, metadata


def _enrich(reports: list[dict], metadata: dict[str, dict]) -> list[dict]:
    result = []
    for original in reports:
        r = dict(original)
        task_id = str(r.get("task_id", ""))
        meta = metadata.get(task_id, {})
        track_name = {"v53": "V5.3 core", "neuro": "Neuro"}.get(
            str(r.get("track", "")).lower(), r.get("track"))
        r["track"] = track_name or meta.get("track", "unknown")
        r["complexity"] = meta.get("complexity", r.get("complexity", "unknown"))
        if not r.get("cohort_id"):
            r["cohort_id"] = meta.get("cohort_id")
        result.append(r)
    return result


def _tables(reports: list[dict], metadata: dict[str, dict]) -> dict[str, list[dict]]:
    configs = sorted({str(r.get("configuration", "unknown")) for r in reports})
    table2, table3, table4, table5, table6 = [], [], [], [], []
    for config in configs:
        rows = [r for r in reports if str(r.get("configuration", "unknown")) == config]
        failures = sum(r.get("status") not in {"success", "completed"} for r in rows)
        for scope in ("full", "entry"):
            for metric in ("precision", "recall", "f1", "jaccard"):
                values = [_metric(r, scope, metric) for r in rows]
                values = [v for v in values if isinstance(v, (int, float))]
                table2.append({"configuration": config, "scope": scope,
                               "metric": metric, "mean": statistics.fmean(values) if values else "NA",
                               "n": len(values), "failures_counted": failures,
                               "runs_in_denominator": len(rows)})
        for field in ("wall_seconds", "llm_calls", "tool_calls", "input_tokens", "output_tokens"):
            values = [r.get(field, r.get("timings", {}).get(field)) for r in rows]
            values = [float(v) for v in values if isinstance(v, (int, float))]
            table3.append({"configuration": config, "cost_metric": field,
                           "mean": statistics.fmean(values) if values else "NA",
                           "max": max(values) if values else "NA", "n": len(values),
                           "runs_in_denominator": len(rows), "failures_counted": failures})

        for track in sorted({str(r.get("track", "unknown")) for r in rows}):
            for complexity in sorted({str(r.get("complexity", "unknown"))
                                      for r in rows if str(r.get("track", "unknown")) == track}):
                group = [r for r in rows if str(r.get("track", "unknown")) == track
                         and str(r.get("complexity", "unknown")) == complexity]
                for scope in ("full", "entry"):
                    for metric in ("precision", "recall", "f1", "jaccard"):
                        vals = [_metric(r, scope, metric) for r in group]
                        vals = [v for v in vals if isinstance(v, (int, float))]
                        table4.append({"track": track, "complexity": complexity,
                                       "configuration": config, "scope": scope,
                                       "metric": metric,
                                       "mean": statistics.fmean(vals) if vals else "NA",
                                       "n": len(vals), "runs": len(group),
                                       "failures_counted": sum(x.get("status") not in {"success", "completed"} for x in group)})

        categories = Counter()
        for r in rows:
            if r.get("status") in {"success", "completed"}:
                continue
            text = (str(r.get("reason", "")) + " " + str(r.get("status", ""))).lower()
            if "timeout" in text:
                category = "timeout"
            elif "budget" in text:
                category = "budget exhausted"
            elif "validator" in text:
                category = "validator exhausted"
            elif "connection" in text or "http 5" in text or "unreachable" in text:
                category = "infrastructure"
            elif "interrupt" in text or "process killed" in text:
                category = "interrupted"
            else:
                category = "other failure"
            categories[category] += 1
        for category in ("timeout", "budget exhausted", "validator exhausted", "infrastructure", "interrupted", "other failure"):
            table6.append({"configuration": config, "failure_category": category,
                           "count": categories[category], "all_runs": len(rows),
                           "failures_counted": failures})

    for metric in ("full.f1", "entry.f1", "full.jaccard", "entry.jaccard"):
        scope, field = metric.split(".")
        values = defaultdict(lambda: defaultdict(list))
        for r in reports:
            val = _metric(r, scope, field)
            if isinstance(val, (int, float)):
                values[str(r.get("configuration", "unknown"))][str(r.get("task_id"))].append(val)
        for i, a in enumerate(configs):
            for b in configs[i+1:]:
                common = sorted(set(values[a]) & set(values[b]))
                a_values = [statistics.fmean(values[a][t]) for t in common]
                b_values = [statistics.fmean(values[b][t]) for t in common]
                diffs = [x-y for x,y in zip(a_values,b_values)]
                if not diffs:
                    stat, pvalue = "NA", "NA"
                elif all(d == 0 for d in diffs):
                    stat, pvalue = 0.0, 1.0
                else:
                    test = wilcoxon(a_values, b_values,
                                    zero_method="wilcox", alternative="two-sided")
                    stat, pvalue = float(test.statistic), float(test.pvalue)
                mean_delta = statistics.fmean(diffs) if diffs else None
                direction = "A higher" if mean_delta and mean_delta > 0 else "B higher" if mean_delta and mean_delta < 0 else "no mean difference" if mean_delta == 0 else "not estimable"
                table5.append({"configuration_a": a, "configuration_b": b,
                               "metric": metric, "n_paired_tasks": len(common),
                               "wilcoxon_statistic": stat, "p_value": pvalue,
                               "mean_delta_a_minus_b": mean_delta if mean_delta is not None else "NA",
                               "effect_direction": direction,
                               "failures_counted": "all runs retained in Table 6; paired n includes metric-complete tasks"})
    return {"table_2_main_results": table2, "table_3_cost": table3,
            "table_4_track_complexity": table4, "table_5_paired": table5,
            "table_6_failures": table6}


def _figures(out: Path, reports: list[dict]) -> None:
    configs = sorted({str(r.get("configuration", "unknown")) for r in reports})
    fig, ax = plt.subplots(figsize=(max(8, len(configs) * 1.8), 5))
    positions, data, labels, colors = [], [], [], []
    for i, config in enumerate(configs, 1):
        for offset, scope, color in ((-0.16, "full", "#2471A3"), (0.16, "entry", "#D68910")):
            vals = [_metric(r, scope, "recall") for r in reports
                    if str(r.get("configuration", "unknown")) == config]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if vals:
                positions.append(i + offset); data.append(vals)
                labels.append(f"{config}\n{scope}"); colors.append(color)
        absent = sum(r.get("status") not in {"success", "completed"}
                     or _metric(r, "full", "recall") is None
                     for r in reports if str(r.get("configuration", "unknown")) == config)
        ax.text(i, 1.03, f"missing/fail={absent}", ha="center", va="bottom", fontsize=8)
    if data:
        artists = ax.boxplot(data, positions=positions, widths=0.25, patch_artist=True,
                             showfliers=False)
        for box, color in zip(artists["boxes"], colors):
            box.set_facecolor(color); box.set_alpha(0.45)
        for pos, vals, color in zip(positions, data, colors):
            jitter = [pos + ((j % 5) - 2) * 0.025 for j in range(len(vals))]
            ax.scatter(jitter, vals, color=color, s=20, alpha=0.8)
    ax.set_xticks(range(1, len(configs) + 1), configs)
    ax.set_ylim(0, 1.15); ax.set_ylabel("Recall against v2")
    ax.set_title("Figure 1. Full and entry recall; missing/failure counts annotated")
    fig.tight_layout()
    fig.savefig(out / "figure_1_recall.png", dpi=180); fig.savefig(out / "figure_1_recall.svg")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    for config in configs:
        group = [r for r in reports if str(r.get("configuration", "unknown")) == config]
        good = [r for r in group if isinstance(_metric(r, "full", "recall"), (int, float))
                and isinstance(r.get("wall_seconds", r.get("timings", {}).get("wall_seconds")), (int, float))]
        xs = [r.get("wall_seconds", r.get("timings", {}).get("wall_seconds")) for r in good]
        ys = [_metric(r, "full", "recall") for r in good]
        ax.scatter(xs, ys, label=f"{config} (shown={len(good)}, missing/fail={len(group)-len(good)})", alpha=0.75)
    ax.set_xlabel("Wall time (seconds)"); ax.set_ylabel("Full recall against v2")
    ax.set_title("Figure 2. Run cost versus full recall")
    ax.legend(); fig.tight_layout()
    fig.savefig(out / "figure_2_cost_vs_recall.png", dpi=180); fig.savefig(out / "figure_2_cost_vs_recall.svg")
    plt.close(fig)


def generate(run_dirs: list[Path], out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    composition, metadata = _composition()
    reports = _enrich(_load_reports(run_dirs), metadata)
    result = analyze(reports)
    out.mkdir(parents=True)
    _write_table(out, "table_1_composition", composition,
                 "n is the number of cohorts in the frozen task lists; there are no run outcomes in this table, so failure count is not applicable")
    tables = _tables(reports, metadata)
    notes = {
        "table_2_main_results": "n is metric-present runs; failure count includes every non-success run and no failed run is assigned a metric.",
        "table_3_cost": "n is runs with observed cost; failures remain included whenever cost was recorded.",
        "table_4_track_complexity": "n is metric-present runs; runs and failures are also shown for each subgroup.",
        "table_5_paired": "n is tasks with metric values in both configurations; failures remain counted in Table 6.",
        "table_6_failures": "counts use all runs; successful runs are excluded only from failure categories.",
    }
    for name, rows in tables.items():
        _write_table(out, name, rows, notes[name])
    (out / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    _figures(out, reports)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    allowed = ROOT / "results/codex_20261025"
    if out != allowed and allowed not in out.parents:
        parser.error("--out must be inside results/codex_20261025/")
    try:
        generate(args.run_dirs, out)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
