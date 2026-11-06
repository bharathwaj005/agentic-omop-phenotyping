"""Read-only validation of a generated JBI release-candidate evidence bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_PACKAGE_FILES = {
    "README.md", "methodology.md", "data_dictionary.md", "historical_integrity.md",
    "model_evaluation.md", "test_report.md", "environment.md", "submission_index.md",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_release_candidate(project_root: str | Path,
                               candidate: str | Path) -> dict[str, Any]:
    """Check package completeness, file hashes, and model-run manifests only."""
    root, package = Path(project_root).resolve(), Path(candidate).resolve()
    issues: list[str] = []
    checked = 0
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "candidate": str(package), "checked_files": 0,
                "issues": [f"release manifest unreadable: {exc}"]}
    if manifest.get("schema_version") != 1:
        issues.append("unsupported release manifest schema_version")

    package_entries = {item.get("path") for item in manifest.get("package_files", [])}
    missing_docs = sorted(REQUIRED_PACKAGE_FILES - package_entries)
    if missing_docs:
        issues.append("required package documents missing from manifest: " + ", ".join(missing_docs))
    groups = [
        ("package_files", package),
        ("implementation_sources", root),
        ("evaluation_inputs", root),
        ("mutable_project_logs", None),
        ("frozen_benchmark_evidence_inventory", None),
        ("exploratory_local_model_run_artifacts", root),
    ]
    for group_name, base in groups:
        values = manifest.get(group_name)
        if not isinstance(values, list):
            issues.append(f"manifest group missing or invalid: {group_name}")
            continue
        for item in values:
            raw_path = item.get("path")
            expected = item.get("sha256")
            if not isinstance(raw_path, str) or not isinstance(expected, str):
                issues.append(f"invalid path/hash entry in {group_name}")
                continue
            path = Path(raw_path) if base is None or Path(raw_path).is_absolute() else base / raw_path
            try:
                observed = _sha256(path)
            except OSError as exc:
                issues.append(f"cannot read {raw_path}: {exc}")
                continue
            checked += 1
            if observed != expected:
                issues.append(f"SHA-256 mismatch: {raw_path}")

    checksum_path = package / "manifest.sha256"
    try:
        checksum_lines = checksum_path.read_text(encoding="utf-8").splitlines()
        expected_checks = {}
        for line in checksum_lines:
            digest, path = line.split("  ", 1)
            expected_checks[path] = digest
        for group_name, base in groups:
            for item in manifest.get(group_name, []):
                raw = item["path"]
                resolved = (Path(raw) if base is None or Path(raw).is_absolute()
                            else base / raw).resolve()
                expected = expected_checks.get(str(resolved))
                if expected != item.get("sha256"):
                    issues.append(f"companion checksum entry missing or differs: {raw}")
        mhash = _sha256(manifest_path)
        if expected_checks.get(str(manifest_path.resolve())) != mhash:
            issues.append("companion checksum does not cover manifest.json")
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append(f"companion checksum file invalid: {exc}")

    model_runs = []
    for item in manifest.get("exploratory_local_model_run_artifacts", []):
        path = root / item.get("path", "")
        if path.name != "run_manifest.v1.json":
            continue
        try:
            run_manifest = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = json.loads((path.parent / "checkpoint.json").read_text(encoding="utf-8"))
            row = checkpoint["runs"][0]
            report_path = root / row["report_path"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if run_manifest.get("schema_version") != 1:
                raise ValueError("unsupported run manifest schema")
            if run_manifest.get("runtime_queue_initial", {}).get("sha256") is None:
                raise ValueError("initial runtime queue hash absent")
            if report.get("schema_version") != 1 or report.get("attempt_id") is None:
                raise ValueError("versioned attempt report or attempt identity absent")
            if report.get("status") == "success" and not isinstance(report.get("final_spec"), dict):
                raise ValueError("success report has no reviewable final_spec")
            model_runs.append({"model": report.get("model_requested"),
                               "status": report.get("status"),
                               "context": report.get("ollama_num_ctx"),
                               "report": str(report_path)})
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            issues.append(f"model evaluation artifact invalid at {path.parent}: {exc}")
    if not model_runs:
        issues.append("no versioned model-evaluation run was verifiable")
    model_doc = package / "model_evaluation.md"
    if not model_doc.is_file() or "not a leaderboard" not in model_doc.read_text(encoding="utf-8").lower():
        issues.append("model evaluation disclosure of exploratory scope is missing")

    return {"status": "PASS" if not issues else "FAIL", "candidate": str(package),
            "checked_files": checked, "model_runs": model_runs,
            "issues": issues, "read_only": True}
