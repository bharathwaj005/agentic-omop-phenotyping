"""Write a source and run configuration hash manifest for review."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/codex_20261024/freeze_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_files() -> tuple[str, list[str]]:
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if not status.strip():
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        return commit, []
    tracked = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True)
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True)
    names = sorted(set(tracked.splitlines() + untracked.splitlines()))
    return "dirty", [n for n in names if (ROOT / n).is_file()]


def _model_names() -> list[str]:
    values = set()
    for key, value in os.environ.items():
        if not value or "MODEL" not in key.upper():
            continue
        # Only take explicit model-name settings; skip URLs and other values.
        if not (key.upper().endswith("_MODEL") or "_MODEL_" in key.upper()):
            continue
        if value.lower().startswith(("http://", "https://")) or "@" in value:
            continue
        values.add(value.strip())
    return sorted(values)


def build_manifest() -> dict:
    commit, dirty_names = _git_files()
    source_files = sorted((ROOT / "src").rglob("*.py"))
    prompt_files = sorted((ROOT / "src/llm/prompts").glob("*.md"))
    scripts = sorted((ROOT / "scripts").rglob("*.py"))
    ref_manifest = ROOT / "tasks/reference_v2/MANIFEST.json"
    return {
        "git_commit": commit,
        "dirty_file_sha256": {name: sha256(ROOT / name) for name in dirty_names},
        "sha256": {
            "src_python": {p.relative_to(ROOT).as_posix(): sha256(p) for p in source_files},
            "prompts": {p.relative_to(ROOT).as_posix(): sha256(p) for p in prompt_files},
            "run_scripts": {p.relative_to(ROOT).as_posix(): sha256(p) for p in scripts},
            "reference_v2_manifest": sha256(ref_manifest) if ref_manifest.exists() else None,
        },
        "model_names": _model_names(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    out = parser.parse_args(argv).out.expanduser().resolve()
    allowed = [(ROOT / "results/codex_20261024").resolve(),
               (ROOT / "results/codex_20261025").resolve()]
    if not any(out == base or base in out.parents for base in allowed):
        parser.error("--out must be inside a dated results/codex_YYYYMMDD/ folder")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    out.write_text(json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
