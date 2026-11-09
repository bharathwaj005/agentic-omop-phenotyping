"""Compare pilot report bundles and suggest a run deadline without setting it."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def _read_reports(dirs: list[Path]) -> list[dict]:
    reports = []
    for directory in dirs:
        files = [directory] if directory.is_file() and directory.name == "report.json" else sorted(directory.rglob("report.json"))
        for path in files:
            reports.append(json.loads(path.read_text()))
    return reports


def _metric(report: dict, scope: str, name: str):
    return report.get("metrics", {}).get("v2", {}).get(scope, {}).get(name)


def compare(reports: list[dict]) -> tuple[list[dict], int | None]:
    rows = []
    success_times = []
    for report in reports:
        spec = report.get("final_spec") or {}
        arms = report.get("entry_arms") or spec.get("entry_arms") or []
        domains = sorted({str(a.get("event_domain", a.get("domain", "unknown"))) for a in arms})
        items = [i for cs in (spec.get("concept_sets") or {}).values()
                 for i in cs.get("items", [])]
        descendants = any(bool(i.get("include_descendants")) for i in items)
        time_s = report.get("wall_seconds", report.get("timings", {}).get("wall_seconds"))
        if report.get("status") == "success" and isinstance(time_s, (int, float)):
            success_times.append(float(time_s))
        names = report.get("model_names_used") or [report.get("model_requested", "")]
        rows.append({
            "model": ",".join(str(x) for x in names),
            "configuration": report.get("configuration", ""),
            "status": report.get("status", "unknown"),
            "wall_time_s": time_s,
            "llm_calls": report.get("llm_calls"), "tool_calls": report.get("tool_calls"),
            "tokens": report.get("input_tokens", 0) + report.get("output_tokens", 0),
            "entry_arms": len(arms), "entry_arm_domains": ",".join(domains),
            "has_drug_arm": any(d.lower() == "drug" for d in domains),
            "any_include_descendants": descendants,
            "full_precision_v2": _metric(report, "full", "precision"),
            "full_recall_v2": _metric(report, "full", "recall"),
            "entry_precision_v2": _metric(report, "entry", "precision"),
            "entry_recall_v2": _metric(report, "entry", "recall"),
        })
    suggested = None
    if success_times:
        suggested = int(math.ceil((3 * max(success_times)) / 60) * 60)
    return rows, suggested


def _table(rows: list[dict]) -> str:
    columns = list(rows[0]) if rows else ["model", "configuration", "status"]
    values = [[str(row.get(col) if row.get(col) is not None else "NA") for col in columns]
              for row in rows]
    widths = [max(len(columns[i]), *(len(r[i]) for r in values)) for i in range(len(columns))]
    header = " | ".join(columns[i].ljust(widths[i]) for i in range(len(columns)))
    sep = "-+-".join("-" * w for w in widths)
    body = [" | ".join(r[i].ljust(widths[i]) for i in range(len(columns))) for r in values]
    return "\n".join([header, sep, *body])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pilot_dirs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        rows, suggestion = compare(_read_reports(args.pilot_dirs))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(_table(rows))
    if suggestion is None:
        print("Suggested JBI_RUN_DEADLINE_S: unavailable (no successful pilot with wall time)")
    else:
        print(f"Suggested JBI_RUN_DEADLINE_S={suggestion} (3 x slowest successful pilot, rounded up to a minute; suggestion only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
