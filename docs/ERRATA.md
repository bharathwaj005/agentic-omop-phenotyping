# Errata and post-run corrections

All corrections below were made after the 128 official runs and **without re-running any model**. The frozen run artefacts under `results/codex_20261025/runs/` are unchanged.

## E1 — Task T10 scored against the wrong cohort (6 Nov 2026)

- **What happened:** T10 asks for patients with ADHD (condition or procedure evidence). Its reference was built from OHDSI Phenotype Library cohort **967**, which is *[P] 4-point MACE* (myocardial infarction, sudden cardiac death, stroke, heart failure). The intended cohort is **1025**, *[P] First event of Attention-deficit hyperactivity (ADHD) disorder or procedure*. The cohort identifier was transcribed wrongly in the V5.3 task list (`V53` in `src/eval/build_reference_v2.py` and `scripts/run_benchmark.py`).
- **How it was found:** all configurations that answered T10 predicted the ADHD concept 438409 and scored zero overlap; the reference contained only cardiovascular concepts.
- **Correction:** `tasks/reference_v2/1025.json` was built from cohort 1025 with the project's own reference builder. The stored T10 outputs were re-scored with the same resolver and metric code; re-resolution reproduced every stored concept-set size exactly (`results/analysis_tier1_20261028/rescore_overrides_T10.json`). The superseded reference is kept at `tasks/reference_v2/superseded/967_4-point-MACE_mislabelled_as_T10.json`, and the runner now maps T10 to 1025.
- **Effect:** V5.3 C1, C3 and C4 gain a scored T10 run (F1 0.0228 each); conclusions are unchanged in direction.

## E2 — Zero-overlap runs were left unscored

`set_metrics` returned F1 = None when precision = recall = 0. Seven completed runs (T04 × 4 configurations, T10 × 3) were therefore excluded from the scored means. They are now scored as F1 = 0 (`src/metrics/evaluation.py`, `scripts/run_tier1_analysis.py`).

## E3 — Paired-test pipeline bug and missing Holm step

`run_tier1_analysis.py` paired tasks with `is not None`, which lets NaN through; four of six comparisons produced NaN statistics and the table formatter reported them as "n.s.". Pairing now uses `pd.notna`, and Holm–Bonferroni adjustment within each track is computed and reported for every comparison (NEURO C1 vs C2: raw p = 0.0391, Holm p = 0.0938).

## E4 — Placeholder outputs removed from the release

`grounding_audit.csv` and `evidence_fidelity.csv` contained only zeros (the patient-level evaluation produced no reference patients in Eunomia) and were removed, together with stale prose drafts. The manuscript no longer makes patient-level claims.

## E5 — Runner portability

`scripts/run_benchmark.py` required a file on the original author's external drive and pinned the pre-correction reference-manifest hash. Missing machine-specific files are now skipped and the hash is pinned to the corrected manifest.

## Post-freeze file changes

A reproducibility audit of a fresh clone (9 Nov 2026) compared every file hashed in `results/codex_20261025/freeze_manifest_OFFICIAL.json` with the released repository: 236 entries match exactly and five files differ. All five are the corrections disclosed in the manuscript; none changes any model output, and all affected scores were recomputed from the stored run outputs.

| File | Change | Reason | Effect on official runs |
| --- | --- | --- | --- |
| `src/eval/build_reference_v2.py` | T10 reference built from cohort 1025 instead of 967 | T10 cohort-identifier transcription error | Reference only; T10 re-scored |
| `tasks/reference_v2/MANIFEST.json` | 1025 added, 967 moved to `superseded/`, erratum note | Same correction | Reference only |
| `src/metrics/evaluation.py` | F1 = 0 when precision + recall = 0 | Zero-overlap scoring rule | Scoring only; no run changed |
| `tests/test_scientific_validation.py` | Disjoint sets now expect F1 = 0.0 | Matches the scoring rule | Tests only |
| `scripts/run_benchmark.py` | T10 cohort 1025; reference-manifest hash pin; portable preflight; `adn` track option | Correction, portability, ADN extension | None; official runs were complete before the change |

Entries reported as "not in repository" refer to files outside the release (draft question files and local paths), which the manifest recorded for provenance.
