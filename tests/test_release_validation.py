import hashlib
import json
from pathlib import Path

from src.release_validation import REQUIRED_PACKAGE_FILES, validate_release_candidate


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(root):
    package = root / "results/jbi_release_candidate_test"
    package.mkdir(parents=True)
    docs = []
    for name in REQUIRED_PACKAGE_FILES:
        path = package / name
        path.write_text("exploratory; not a leaderboard\n", encoding="utf-8")
        docs.append({"path": name, "sha256": _sha(path)})
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    reference = root / "tasks/reference.json"
    reference.parent.mkdir(parents=True)
    reference.write_text("reference", encoding="utf-8")

    run_dir = root / "runs/local"
    run_dir.mkdir(parents=True)
    report = run_dir / "report.json"
    report.write_text(json.dumps({"schema_version": 1, "attempt_id": "a1",
                                  "model_requested": "qwen2.5:7b", "status": "failed",
                                  "ollama_num_ctx": 4096}), encoding="utf-8")
    checkpoint = run_dir / "checkpoint.json"
    checkpoint.write_text(json.dumps({"runs": [{"report_path": "runs/local/report.json"}]}), encoding="utf-8")
    run_manifest = run_dir / "run_manifest.v1.json"
    run_manifest.write_text(json.dumps({"schema_version": 1,
                                        "runtime_queue_initial": {"sha256": "a" * 64}}), encoding="utf-8")
    run_artifacts = [{"path": p.relative_to(root).as_posix(), "sha256": _sha(p)}
                     for p in (report, checkpoint, run_manifest)]
    frozen = root / "frozen/evidence.json"
    frozen.parent.mkdir()
    frozen.write_text("preserved", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "package_files": docs,
        "implementation_sources": [{"path": "src/example.py", "sha256": _sha(source)}],
        "evaluation_inputs": [{"path": "tasks/reference.json", "sha256": _sha(reference)}],
        "mutable_project_logs": [],
        "frozen_benchmark_evidence_inventory": [{"path": str(frozen), "sha256": _sha(frozen)}],
        "exploratory_local_model_run_artifacts": run_artifacts,
    }
    manifest_path = package / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checks = [(item["sha256"], (package / item["path"]).resolve()) for item in docs]
    checks += [(_sha(source), source.resolve()), (_sha(reference), reference.resolve()),
               (_sha(frozen), frozen.resolve())]
    checks += [(item["sha256"], (root / item["path"]).resolve()) for item in run_artifacts]
    checks.append((_sha(manifest_path), manifest_path.resolve()))
    (package / "manifest.sha256").write_text(
        "".join(f"{digest}  {path}\n" for digest, path in checks), encoding="utf-8")
    return package, source


def test_release_candidate_is_read_only_and_hash_checked(tmp_path):
    package, source = _candidate(tmp_path)
    before = _sha(source)
    report = validate_release_candidate(tmp_path, package)
    assert report["status"] == "PASS"
    assert report["read_only"] is True
    assert report["model_runs"][0]["context"] == 4096
    assert _sha(source) == before

    source.write_text("value = 2\n", encoding="utf-8")
    failed = validate_release_candidate(tmp_path, package)
    assert failed["status"] == "FAIL"
    assert any("SHA-256 mismatch" in issue for issue in failed["issues"])
