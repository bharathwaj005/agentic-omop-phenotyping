#!/usr/bin/env python3
"""Idempotent fixes to scripts/run_benchmark.py for the public release.

1. T10 -> OHDSI cohort 1025 (was 967, 4-point MACE; see docs/ERRATA.md).
2. Pin REFERENCE_V2_SHA256 to the corrected tasks/reference_v2/MANIFEST.json.
3. Skip machine-specific absolute paths in the frozen-file preflight when they do
   not exist (so the benchmark can be re-run outside the original laptop).
4. Add the 'adn' (Alzheimer's neuroinflammation) extension track.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
f = ROOT / "scripts" / "run_benchmark.py"
t = f.read_text()
orig = t


def sub(old, new, label):
    global t
    if new in t:
        print(f"  already: {label}"); return
    if old not in t:
        raise SystemExit(f"  PATTERN NOT FOUND ({label}): {old[:70]}")
    t = t.replace(old, new, 1); print(f"  fixed:   {label}")


sub("864, 967, 1048", "864, 1025, 1048", "T10 cohort 967 -> 1025")
manifest_sha = hashlib.sha256((ROOT / "tasks/reference_v2/MANIFEST.json").read_bytes()).hexdigest()
cur = re.search(r'REFERENCE_V2_SHA256 = "([0-9a-f]{64})"', t).group(1)
if cur != manifest_sha:
    t = t.replace(f'REFERENCE_V2_SHA256 = "{cur}"', f'REFERENCE_V2_SHA256 = "{manifest_sha}"  # corrected T10 reference (docs/ERRATA.md)')
    print("  fixed:   reference manifest hash pinned")
else:
    print("  already: reference manifest hash pinned")
sub("        path = Path(raw) if raw.startswith(\"/\") else ROOT / raw\n        if not path.is_file()",
    "        path = Path(raw) if raw.startswith(\"/\") else ROOT / raw\n        if raw.startswith(\"/\") and not path.exists():\n            continue  # machine-specific provenance file; not shipped with the repository\n        if not path.is_file()",
    "portable frozen-file preflight")
sub('expected = "T" if track == "v53" else "N"', 'expected = {"v53": "T", "neuro": "N", "adn": "A"}[track]', "adn task prefix")
sub('    path = ROOT / "results/benchmark_design/NEURO_FREEZE/task_list.csv"',
    '    path = ROOT / ("tasks/adn/task_list.csv" if track == "adn" else "results/benchmark_design/NEURO_FREEZE/task_list.csv")',
    "adn cohort map")
sub('v1_folder = "reference" if track == "v53" else "reference_neuro"',
    'v1_folder = {"v53": "reference", "neuro": "reference_neuro", "adn": "reference_adn"}[track]', "adn v1 folder")
sub('for version, folder in (("v1", v1_folder), ("v2", "reference_v2")):',
    'for version, folder in (("v1", v1_folder), ("v2", "reference_adn" if track == "adn" else "reference_v2")):', "adn v2 folder")
sub('    if version == "v2":\n        folder = "reference_v2"\n    else:\n        folder = "reference" if track == "v53" else "reference_neuro"',
    '    if track == "adn":\n        folder = "reference_adn"\n    elif version == "v2":\n        folder = "reference_v2"\n    else:\n        folder = "reference" if track == "v53" else "reference_neuro"',
    "adn reference loader")
sub('choices=["v53", "neuro"]', 'choices=["v53", "neuro", "adn"]', "adn CLI choice")
if t != orig:
    f.write_text(t)
print("run_benchmark.py ready")
