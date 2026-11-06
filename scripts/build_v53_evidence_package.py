#!/usr/bin/env python3
"""Build a timestamped local V5.3 integrity package without editing source evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark_integrity import audit
from src.v53_reconciliation import write_package


def _run_test(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return {"command": " ".join(command), "exit_code": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip(),
            "passed": result.returncode == 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New output directory, preferably under repository results/")
    parser.add_argument("--skip-tests", action="store_true", help="Do not rerun tests; package will record NOT_RUN.")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    artifacts = args.artifacts.resolve()
    queue = args.queue.resolve()
    if out == queue or out.is_relative_to(artifacts):
        parser.error("output directory must be outside the canonical queue and benchmark evidence directory")
    if out.exists():
        parser.error(f"output directory already exists; refusing to overwrite: {out}")

    test_results = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "tests": []}
    if args.skip_tests:
        test_results["state"] = "NOT_RUN"
    else:
        commands = [
            [sys.executable, "-m", "pytest", "-q", "tests/test_benchmark_integrity.py"],
            [sys.executable, "-m", "pytest", "-q"],
        ]
        test_results["tests"] = [_run_test(command, ROOT) for command in commands]
        test_results["state"] = "PASS" if all(row["passed"] for row in test_results["tests"]) else "FAIL"

    report = audit(queue, artifacts, args.expected_sha256)
    outcome = write_package(out, report, ROOT, artifacts, test_results)
    print(json.dumps({"package": outcome["output_dir"], "gate": outcome["gate"]["overall_status"],
                      "ledger_rows": outcome["ledger_rows"], "test_state": test_results["state"],
                      "tests": test_results["tests"]}, indent=2))
    return 0 if test_results["state"] in {"PASS", "NOT_RUN"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
