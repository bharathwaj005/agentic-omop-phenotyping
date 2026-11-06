"""Summarize per-run reports without hiding failures or missing metrics."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results/codex_20261024/analysis.json"


def _number(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _metric(run: dict, scope: str, name: str):
    metrics = run.get("metrics", {}).get("v2", {})
    value = metrics.get(scope, {}).get(name) if isinstance(metrics, dict) else None
    if value is None:
        value = run.get(f"concept_{name}_{scope}")
    return _number(value)


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _aggregate(runs: list[dict]) -> dict:
    metric_names = ("precision", "recall", "f1", "jaccard")
    metrics = {scope: {name: {"mean": _mean([_metric(r, scope, name) for r in runs]),
                              "n": sum(_metric(r, scope, name) is not None for r in runs),
                              "missing": sum(_metric(r, scope, name) is None for r in runs)}
                      for name in metric_names} for scope in ("full", "entry")}
    statuses = Counter(str(r.get("status", "missing_status")) for r in runs)
    cost = {}
    for name in ("wall_seconds", "llm_calls", "tool_calls", "input_tokens", "output_tokens"):
        values = [_number(r.get(name, r.get("timings", {}).get(name))) for r in runs]
        cost[name] = {"mean": _mean(values), "n": sum(v is not None for v in values),
                      "missing": sum(v is None for v in values)}
    return {"runs": len(runs), "status_counts": dict(sorted(statuses.items())),
            "failed_runs": sum(r.get("status") not in ("success", "completed") for r in runs),
            "metrics_v2": metrics, "cost": cost}


def _key_metric(run: dict, name: str):
    scope, metric = name.split(".", 1)
    return _metric(run, scope, metric)


def analyze(reports: list[dict]) -> dict:
    configs: dict[str, list[dict]] = defaultdict(list)
    for run in reports:
        configs[str(run.get("configuration", "unknown"))].append(run)

    breakdown = {"track": {}, "complexity": {}}
    for field in breakdown:
        groups: dict[str, list[dict]] = defaultdict(list)
        for run in reports:
            value = run.get(field)
            if field == "track" and value is None:
                tid = str(run.get("task_id", ""))
                value = "V5.3 core" if tid.startswith("T") else "Neuro" if tid else "unknown"
            groups[str(value or "unknown")].append(run)
        breakdown[field] = {name: {config: _aggregate([r for r in group
                                                if str(r.get("configuration", "unknown")) == config])
                                   for config in sorted(configs)}
                            for name, group in sorted(groups.items())}

    paired = {}
    for metric in ("full.f1", "full.jaccard", "entry.f1", "entry.jaccard"):
        by_config_task: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for run in reports:
            value = _key_metric(run, metric)
            if value is not None:
                by_config_task[str(run.get("configuration", "unknown"))][str(run.get("task_id"))].append(value)
        for i, config_a in enumerate(sorted(configs)):
            for config_b in sorted(configs)[i + 1:]:
                common = sorted(set(by_config_task[config_a]) & set(by_config_task[config_b]))
                a = [_mean(by_config_task[config_a][t]) for t in common]
                b = [_mean(by_config_task[config_b][t]) for t in common]
                if not common:
                    test = {"n": 0, "statistic": None, "p_value": None}
                elif all(x == y for x, y in zip(a, b)):
                    test = {"n": len(common), "statistic": 0.0, "p_value": 1.0}
                else:
                    result = wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
                    test = {"n": len(common), "statistic": float(result.statistic),
                            "p_value": float(result.pvalue)}
                paired[f"{config_a}__{config_b}__{metric}"] = test

    return {"configurations": {config: _aggregate(runs)
                               for config, runs in sorted(configs.items())},
            "breakdowns": breakdown, "paired_wilcoxon_v2": paired,
            "paired_metric_definition": "task-paired v2 full/entry F1 and Jaccard; repeated runs are averaged within task/configuration; n is the number of tasks with both values present"}


def _load_reports(inputs: list[Path]) -> list[dict]:
    files = []
    for path in inputs:
        files.extend([path] if path.is_file() else sorted(path.rglob("report.json")))
    reports = []
    for path in files:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            reports.extend(data["runs"])
        elif isinstance(data, dict):
            reports.append(data)
    return reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    allowed = (ROOT / "results/codex_20261024").resolve()
    if out != allowed and allowed not in out.parents:
        parser.error("--out must be inside results/codex_20261024/")
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    reports = _load_reports(args.reports)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analyze(reports), indent=2, sort_keys=True) + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
