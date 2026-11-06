"""Read and summarize a run directory without modifying it."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

COMPLETE = {"success", "failed", "timeout", "budget_exhausted",
            "validator_exhausted", "completed"}
FAILURE = {"failed", "timeout", "budget_exhausted", "validator_exhausted", "interrupted"}


def summarize(out: Path) -> dict:
    checkpoint_path = out / "checkpoint.json"
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"missing checkpoint: {checkpoint_path}")
    checkpoint = json.loads(checkpoint_path.read_text())
    rows = checkpoint.get("runs", [])
    by_config = {}
    for config in sorted({str(r.get("configuration", "unknown")) for r in rows}):
        subset = [r for r in rows if str(r.get("configuration", "unknown")) == config]
        times = [float(r["wall_seconds"]) for r in subset
                 if r.get("wall_seconds") not in (None, "")]
        remaining = sum(
            r.get("status") not in COMPLETE
            and not (r.get("status") == "interrupted" and int(r.get("attempts", 0)) >= 2)
            for r in subset)
        mean = statistics.fmean(times) if times else None
        by_config[config] = {
            "counts_by_status": {status: sum(r.get("status") == status for r in subset)
                                 for status in sorted({str(r.get("status", "unknown")) for r in subset})},
            "runs": len(subset), "remaining": remaining,
            "mean_wall_seconds": mean,
            "max_wall_seconds": max(times) if times else None,
            "estimated_remaining_seconds": mean * remaining if mean is not None else None,
        }
    failures = [{"task_id": r.get("task_id"), "configuration": r.get("configuration"),
                 "status": r.get("status"), "reason": r.get("reason"),
                 "finished_at": r.get("finished_at")}
                for r in rows if r.get("status") in FAILURE]
    failures.sort(key=lambda r: r.get("finished_at") or "", reverse=True)
    total_remaining = sum(x["remaining"] for x in by_config.values())
    estimates = [x["estimated_remaining_seconds"] for x in by_config.values()
                 if x["estimated_remaining_seconds"] is not None]
    return {"track": checkpoint.get("track"), "model": checkpoint.get("model"),
            "runs": len(rows), "remaining": total_remaining,
            "estimated_remaining_seconds": sum(estimates) if estimates else None,
            "by_configuration": by_config, "last_5_failures": failures[:5]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = summarize(args.out_dir.expanduser().resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
