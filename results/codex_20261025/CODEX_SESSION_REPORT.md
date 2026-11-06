# JBI engineering completion report — 2026-10-25

## Task status

| Task | Status | Evidence / limits |
|---|---|---|
| 1. Per-run deadline | Complete | Each task × configuration gets a fresh monotonic deadline. Regression covers timeout followed by a successful fresh run, no environment variable, and saved timeout trace/checkpoint. HTTP request timeout and retry delay use the current deadline. |
| 2. Duplicate guard fairness | Complete | No behavioral difference remains: both agents use the same signature, correction, one-tool-call accounting, and stop after the second duplicate retry. A parity test checks exact correction text, failed status/reason, and call counts. |
| 3. Neuro freeze package | Complete | 12 selected tasks, two exclusions, copied v2 gate summary, package/reference hashes, and a separate DRAFT questions JSONL plus human-review marker. `tasks/neuro_questions.jsonl` was not created. Patient evaluability uses direct entry-event concept coverage, not full cohort execution. |
| 4. Full-run orchestrator | Complete | Sequential/interleaved queue, isolated queue/checkpoint, per-run reports/traces/raw replies, resume, bounded infrastructure retry, and Ctrl+C handling implemented. Tests use the fake client or mocked run function. The endpoint/model preflight was not executed because network access is prohibited in this session. |
| 5. Status command | Complete | Read-only summary includes configuration/status counts, remaining work, observed mean/max time, estimated remaining time, and five latest timestamped failures. Synthetic test passes. |
| 6. Pilot comparison | Complete | Prints requested report fields and a rounded-up deadline suggestion without setting it. Synthetic test passes; no real pilot reports were generated. |
| 7. Tables and figures | Complete | Produces six CSV/Markdown tables and two PNG/SVG figures, including failure counts and paired tests. Tested only with synthetic fixtures; no real runs were analyzed. |
| 8. Methods fact sheet | Complete | Verified facts are listed in `METHODS_FACTS.md`; unverified sources/values are explicitly marked `UNVERIFIED`. |

No model/network calls were made and no benchmark runs/results were produced. The Neuro questions remain a draft and require human review before a final questions file is made.

## Neuro package

- Selected cohorts: 255, 863, 552, 1026, 287, 535, 1079, 544, 235, 550, 229, 1066.
- Excluded: 33 (0.9065 vs V5.3 cohort 864); 1080 (1.0000 vs Neuro cohort 235).
- Eunomia entry-event coverage: 255 has 136 matching persons; 287 has 3; the remaining 10 have 0. `patient_evaluable` is true for 255 and 287 only.
- Draft questions have N01–N12 IDs and contain only question text and task IDs. The adjacent `tasks/neuro_questions_DRAFT_README.txt` says “DRAFT - REQUIRES HUMAN REVIEW.”
- Package manifest: `results/benchmark_design/NEURO_FREEZE/MANIFEST.json`; it hashes every other package file, the draft question files, all 12 reference v2 files, and the reference v2 manifest.

## Files created or changed

### Changed existing files and pre-edit backups

- `src/runner/experiment.py` — pre-edit copies: `src/runner/experiment.py.backup_codex_20261025_174941` and `src/runner/experiment.py.backup_codex_20261025_175722`.
- `src/pipelines/deadline.py` — pre-edit copy: `src/pipelines/deadline.py.backup_codex_20261025_175722`.
- `scripts/make_freeze_manifest.py` — pre-edit copy: `scripts/make_freeze_manifest.py.backup_codex_20261025_175735`.
- `scripts/run_benchmark.py` — pre-edit copy: `scripts/run_benchmark.py.backup_codex_20261025_175848`.
- `scripts/benchmark_status.py` — pre-edit copy: `scripts/benchmark_status.py.backup_codex_20261025_175848`.
- `scripts/analyze_results.py` — pre-edit copy: `scripts/analyze_results.py.backup_codex_20261025_175940`.
- `scripts/make_paper_outputs.py` — pre-edit copies: `scripts/make_paper_outputs.py.backup_codex_20261025_175940` and `scripts/make_paper_outputs.py.backup_codex_20261025_180049`.
- `tests/test_run_deadline.py` — pre-edit copy: `tests/test_run_deadline.py.backup_codex_20261025_174941`.
- `tests/test_paper_paired_repeats_synthetic.py` — pre-edit copy: `tests/test_paper_paired_repeats_synthetic.py.backup_codex_20261025_180015`.

### New scripts and tests

- Scripts: `scripts/run_benchmark.py`, `scripts/benchmark_status.py`, `scripts/compare_pilots.py`, `scripts/make_paper_outputs.py`.
- Tests: `tests/test_duplicate_guard_parity.py`, `tests/test_run_benchmark_fake.py`, `tests/test_run_benchmark_queue_synthetic.py`, `tests/test_benchmark_status.py`, `tests/test_compare_pilots_synthetic.py`, `tests/test_make_paper_outputs_synthetic.py`, `tests/test_paired_repeat_aggregation_synthetic.py`, `tests/test_paper_paired_repeats_synthetic.py`.
- The new Neuro outputs, fact sheet, and this report are listed below. New files did not have pre-edit backups.

### Neuro and documentation outputs

- `results/benchmark_design/NEURO_FREEZE/task_list.csv`
- `results/benchmark_design/NEURO_FREEZE/exclusion_log.csv`
- `results/benchmark_design/NEURO_FREEZE/gate_summary_v2.txt`
- `results/benchmark_design/NEURO_FREEZE/README.txt`
- `results/benchmark_design/NEURO_FREEZE/MANIFEST.json`
- `tasks/neuro_questions_DRAFT.jsonl`
- `tasks/neuro_questions_DRAFT_README.txt`
- `results/codex_20261025/METHODS_FACTS.md`
- `results/codex_20261025/CODEX_SESSION_REPORT.md`
- A pre-edit copy of this report is `results/codex_20261025/CODEX_SESSION_REPORT.md.backup_codex_20261025_180208`.

## Test and verification results

- `./.venv/bin/python -m pytest -q`: **84 passed**.
- `./.venv/bin/python -m compileall -q src scripts`: **passed**.
- `git diff --check`: **passed**.
- All tests and compile checks used `.venv`. One path-existence check accidentally invoked system `python`; it only read two local path-existence flags and made no network or model call.
- No production preflight was invoked, so endpoint reachability and model presence remain unverified until the user runs the orchestrator.

## Protected-file checksum confirmation

The values below match the 2026-10-24 report and the supplied expected hashes:

| Protected file | SHA-256 |
|---|---|
| `results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv` | `205e4f69c4d43b89719c4291446d11b760b939b2610999e43c2a11dc4377e0f2` |
| `results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FINAL_ENTRY_JACCARD_190_PAIRS.csv` | `0dcdd9b3c99eda1c92dde3fec8914a8cf2280416147cfcab9f974fe7cb78c1b1` |
| `results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FINAL_REDUNDANCY_AUDIT.txt` | `095e4b3fce262f29ab926e3e5a12dc60898dacfd73363b7cf5ed83581db83c67` |
| `results/benchmark_design/V5_3_FREEZE/BENCHMARK_V5_3_FREEZE_MANIFEST.json` | `77a26b5178d0ed36c33f2bb3a8c42791ddc123794c9ca3a4ad2eec1465134f06` |
| `tasks/reference/134.json` | `a9ded2583ada1e552702595e3a80b132ce5a1d4dbebaf3ceef972492a4248c2c` |
| HDD `results/benchmark_runs/V5_3_REAL_RUN/RUN_QUEUE.csv` | `ac668c67c85ad69d061476c071f17c55ef24b0b4c913cebd42184687ddea6a66` |
| Frozen `tasks/reference_v2/MANIFEST.json` | `4f807ba055ed1a71d5ded423fab5bd27041efdb1cd27ea4f32ccaf6afaf688bb` |

## RUNBOOK

Run these blocks from `/home/bharathwaj/jbi` in the same terminal session. In step 1, put each candidate model name in `MODEL_CANDIDATES`; `<model name>` is the only value to replace. Pilot output folders use distinct numbered names.

### 1. Run T01 pilots for C2 and C1 for each candidate model

```bash
cd /home/bharathwaj/jbi
MODEL_CANDIDATES=("<model name>")
for i in "${!MODEL_CANDIDATES[@]}"; do
  MODEL="${MODEL_CANDIDATES[$i]}"
  CANDIDATE=$((i + 1))
  for CONFIG in C2 C1; do
    OUT="results/codex_20261024/pilots/T01_candidate${CANDIDATE}_${CONFIG}"
    ./.venv/bin/python scripts/run_pilot.py --task T01 --config "$CONFIG" --model "$MODEL" --out "$OUT" --reference-version v2
  done
done
```

### 2. Compare pilot runs

```bash
./.venv/bin/python scripts/compare_pilots.py results/codex_20261024/pilots/*
```

### 3. Set the deadline from the pilot suggestion

Read the suggested seconds printed in step 2, enter that value, and export it for each run:

```bash
read -r -p 'Enter the suggested JBI_RUN_DEADLINE_S seconds: ' JBI_RUN_DEADLINE_S
export JBI_RUN_DEADLINE_S
```

### 4. Create the final source freeze manifest

```bash
./.venv/bin/python scripts/make_freeze_manifest.py --out results/codex_20261025/freeze_manifest.json
```

### 5. Launch the V5.3 track for each candidate model

```bash
for i in "${!MODEL_CANDIDATES[@]}"; do
  MODEL="${MODEL_CANDIDATES[$i]}"
  CANDIDATE=$((i + 1))
  ./.venv/bin/python scripts/run_benchmark.py --track v53 --questions tasks/benchmark_questions.jsonl --model "$MODEL" --out "results/codex_20261025/runs/v53_candidate${CANDIDATE}" --freeze-manifest results/codex_20261025/freeze_manifest.json
done
```

### 6. Check V5.3 run status

```bash
for i in "${!MODEL_CANDIDATES[@]}"; do
  CANDIDATE=$((i + 1))
  ./.venv/bin/python scripts/benchmark_status.py "results/codex_20261025/runs/v53_candidate${CANDIDATE}"
done
```

### 7. Resume after an interruption

Run this for every candidate directory. Completed runs are skipped from the checkpoint.

```bash
for i in "${!MODEL_CANDIDATES[@]}"; do
  MODEL="${MODEL_CANDIDATES[$i]}"
  CANDIDATE=$((i + 1))
  ./.venv/bin/python scripts/run_benchmark.py --track v53 --questions tasks/benchmark_questions.jsonl --model "$MODEL" --out "results/codex_20261025/runs/v53_candidate${CANDIDATE}" --freeze-manifest results/codex_20261025/freeze_manifest.json --resume
done
```

### 8. Launch Neuro after human approval

After review, save the approved questions as `tasks/neuro_questions.jsonl`; this session intentionally created only the DRAFT file.

```bash
for i in "${!MODEL_CANDIDATES[@]}"; do
  MODEL="${MODEL_CANDIDATES[$i]}"
  CANDIDATE=$((i + 1))
  ./.venv/bin/python scripts/run_benchmark.py --track neuro --questions tasks/neuro_questions.jsonl --model "$MODEL" --out "results/codex_20261025/runs/neuro_candidate${CANDIDATE}" --freeze-manifest results/codex_20261025/freeze_manifest.json
done
```

After both tracks finish, generate manuscript tables and figures:

```bash
./.venv/bin/python scripts/make_paper_outputs.py results/codex_20261025/runs/* --out results/codex_20261025/paper_outputs
```
