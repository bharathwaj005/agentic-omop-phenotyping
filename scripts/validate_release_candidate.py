#!/usr/bin/env python3
"""Read-only check for the latest JBI release-candidate package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.release_validation import validate_release_candidate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    candidate = args.candidate
    if candidate is None:
        choices = sorted((root / "results").glob("jbi_release_candidate_*"))
        candidate = choices[-1] if choices else root / "results/__no_release_candidate__"
    report = validate_release_candidate(root, candidate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"Release candidate: {report.get('candidate')}")
    print(f"Release package validation: {report.get('status')}; checked files={report.get('checked_files')}")
    for issue in report.get("issues", []):
        print(f"- {issue}")
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
