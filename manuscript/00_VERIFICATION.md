<!-- src: manuscript/00_VERIFICATION.md -->
# Pre-Submission Audit and Quantitative Data Traceability

This document records the exact file origins, configurations, and raw counts used throughout the submitted manuscript.

## 1. Architectural Configurations
Verified against `src/runner/experiment.py`:
- **C1**: Multi-agent + Critic + Schema/Semantic Validator (`ExperimentConfig(use_critic=True, use_validator=True, single_agent=False)`)
- **C2**: Single-Agent Baseline + Schema/Semantic Validator (`ExperimentConfig(use_critic=False, use_validator=True, single_agent=True)`)
- **C3**: Multi-agent + Schema/Semantic Validator, No Critic (`ExperimentConfig(use_critic=False, use_validator=True, single_agent=False)`)
- **C4**: Multi-agent + Critic, No Schema/Semantic Validator (`ExperimentConfig(use_critic=True, use_validator=False, single_agent=False)`)

## 2. Quantitative Ground Truth Registry
<!-- src: results/analysis_tier1_20261028/table_main_results.csv -->
| Track | Config | Completed (N) | Scored F1 (Mean ± SD) | All=0 F1 (Mean) | Mean Recall | Mean Precision |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| V5.3 | C1 | 9 / 20 | 0.3002 ± 0.353 | 0.1351 | 0.2374 | 0.9903 |
| V5.3 | C2 | 13 / 20 | 0.2385 ± 0.321 | 0.1550 | 0.1842 | 0.9036 |
| V5.3 | C3 | 13 / 20 | 0.2288 ± 0.314 | 0.1487 | 0.2024 | 0.9385 |
| V5.3 | C4 | 14 / 20 | 0.1717 ± 0.316 | 0.1202 | 0.1398 | 1.0000 |
| NEURO | C1 | 12 / 12 | 0.6208 ± 0.410 | 0.6208 | 0.6082 | 0.9295 |
| NEURO | C2 | 11 / 12 | 0.3242 ± 0.362 | 0.2972 | 0.2597 | 1.0000 |
| NEURO | C3 | 12 / 12 | 0.3556 ± 0.311 | 0.3556 | 0.2700 | 1.0000 |
| NEURO | C4 | 12 / 12 | 0.3473 ± 0.308 | 0.3473 | 0.2700 | 0.9583 |

<!-- src: results/analysis_tier1_20261028/paired_tests_formatted.csv -->
### Paired Wilcoxon Signed-Rank Statistics (C1 Reference)
- **V5.3 C1 vs C2:** N=9, 3 wins / 3 ties / 3 losses, Median Diff = 0.0000, Mean Diff = +0.0442, 95% Bootstrap CI [-0.0600, 0.1707], p > 0.05 (n.s.).
- **V5.3 C1 vs C3:** N=9, 3 wins / 6 ties / 0 losses, Median Diff = 0.0000, Mean Diff = +0.0514, 95% Bootstrap CI [0.0000, 0.1267], p > 0.05 (n.s.).
- **V5.3 C1 vs C4:** N=9, 4 wins / 5 ties / 0 losses, Median Diff = 0.0000, Mean Diff = +0.0571, 95% Bootstrap CI [0.0006, 0.1267], p > 0.05 (n.s.).
- **NEURO C1 vs C2:** N=11, 7 wins / 3 ties / 1 loss, Median Diff = +0.0288, Mean Diff = +0.3190, 95% Bootstrap CI [0.0614, 0.5778], p > 0.05 (n.s.).
- **NEURO C1 vs C3:** N=12, 6 wins / 5 ties / 1 loss, Median Diff = +0.1500, Mean Diff = +0.2651, 95% Bootstrap CI [0.0881, 0.4535], uncorrected p = 0.0312 (Holm-corrected p > 0.05, n.s.).
- **NEURO C1 vs C4:** N=12, 6 wins / 5 ties / 1 loss, Median Diff = +0.1517, Mean Diff = +0.2735, 95% Bootstrap CI [0.0935, 0.4615], uncorrected p = 0.0312 (Holm-corrected p > 0.05, n.s.).

## 3. Discrepancy & Gap Log
- `T05_C2` is absent from official V5.3 runs (`results/codex_20261025/runs/official_v53_qwen7b/T05_C2/`). Recorded as missing.
- Infrastructure aborts occurred in `T05_C1`, `T11_C3`, and `T17_C2`.
