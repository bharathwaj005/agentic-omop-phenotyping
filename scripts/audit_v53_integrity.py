#!/usr/bin/env python3
"""Run read-only integrity reconciliation for the frozen V5.3 artifacts."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark_integrity import audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True,
                        help="V5_3_REAL_RUN directory containing manifest/results/recovery")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True,
                        help="JSON output path; choose a separate writable location")
    args = parser.parse_args()
    report_path = args.report.resolve()
    artifacts_path = args.artifacts.resolve()
    queue_resolved = args.queue.resolve()
    if report_path == queue_resolved or report_path.is_relative_to(artifacts_path):
        parser.error("--report must be outside the queue and benchmark artifact directory")
    report = audit(args.queue, args.artifacts, args.expected_sha256)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"runs={len(report['runs'])} attempts={len(report['attempt_records'])} findings={len(report['findings'])}")
    print(f"queue_sha256={report['queue_sha256']} report={report_path}")
    return 0 if report.get("queue_sha256") == args.expected_sha256 else 2


if __name__ == "__main__":
    raise SystemExit(main())
