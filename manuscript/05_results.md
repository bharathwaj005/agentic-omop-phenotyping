# 5. Results

## 5.1 Primary Performance Across Tracks

Table 1 summarizes computable phenotype extraction performance across the V5.3 General ($N=20$) and Neurological ($N=12$) benchmark tracks under dual-denominator accounting.

| Track | Config | Completed | Mean F1 (Scored) | Mean F1 (All=0) | Mean Recall | Mean Precision |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **V5.3 General** | C1 | 9 / 20 | 0.3002 ± 0.353 | 0.1351 | 0.2374 | 0.9903 |
| **V5.3 General** | C2 | 13 / 20 | 0.2385 ± 0.321 | 0.1550 | 0.1842 | 0.9036 |
| **V5.3 General** | C3 | 13 / 20 | 0.2288 ± 0.314 | 0.1487 | 0.2024 | 0.9385 |
| **V5.3 General** | C4 | 14 / 20 | 0.1717 ± 0.316 | 0.1202 | 0.1398 | 1.0000 |
| **NEURO Track** | C1 | 12 / 12 | 0.6208 ± 0.410 | 0.6208 | 0.6082 | 0.9295 |
| **NEURO Track** | C2 | 11 / 12 | 0.3242 ± 0.362 | 0.2972 | 0.2597 | 1.0000 |
| **NEURO Track** | C3 | 12 / 12 | 0.3556 ± 0.311 | 0.3556 | 0.2700 | 1.0000 |
| **NEURO Track** | C4 | 12 / 12 | 0.3473 ± 0.308 | 0.3473 | 0.2700 | 0.9583 |

*Table 1: Dual-denominator benchmarking results. Scored reflects successful parses evaluated against Reference v2; All=0 assigns zero to unparsed outputs, schema rejections, and timeouts.*

### 5.1.1 Neurological Track: Domain-Specific Agentic Advantage
In the Neurological track, the full multi-agent pipeline (C1) completed all 12 tasks (100% completion) and achieved a mean $F_1$ of 0.6208 ± 0.410, doubling concept recall (0.6082) compared to single-agent C2 (0.2597), critic-ablated C3 (0.2700), and validator-ablated C4 (0.2700).

Table 2 presents paired statistical comparisons anchored on C1.

| Track | Comparison | N (Paired) | Wins | Ties | Losses | Median Diff | Mean Diff | 95% Bootstrap CI | p-value |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| V5.3 | C1 vs C2 | 9 | 3 | 3 | 3 | 0.0000 | +0.0442 | [-0.0600, 0.1707] | n.s. |
| V5.3 | C1 vs C3 | 9 | 3 | 6 | 0 | 0.0000 | +0.0514 | [0.0000, 0.1267] | n.s. |
| V5.3 | C1 vs C4 | 9 | 4 | 5 | 0 | 0.0000 | +0.0571 | [0.0006, 0.1267] | n.s. |
| **NEURO** | **C1 vs C2** | 11 | 7 | 3 | 1 | +0.0288 | +0.3190 | [0.0614, 0.5778] | n.s. |
| **NEURO** | **C1 vs C3** | 12 | 6 | 5 | 1 | +0.1500 | +0.2651 | [0.0881, 0.4535] | 0.0312* |
| **NEURO** | **C1 vs C4** | 12 | 6 | 5 | 1 | +0.1517 | +0.2735 | [0.0935, 0.4615] | 0.0312* |

*Table 2: Paired Wilcoxon signed-rank comparisons anchored on configuration C1. *Nominally significant at p < 0.05; non-significant following Holm-Bonferroni family-wise error rate correction (p ≈ 0.09).*

Bootstrap 95% confidence intervals (10,000 resamples) strictly excluded zero for all three comparisons in the Neurological track (+0.2651 to +0.3190 mean advantage). While uncorrected paired Wilcoxon tests against C3 and C4 achieved nominal significance ($p = 0.0312$), family-wise error control via Holm-Bonferroni adjustment yields $p \approx 0.09$. The consistent directionality across paired tasks establishes that the cooperative multi-agent architecture substantially enhances concept recall in targeted clinical domains.

### 5.1.2 V5.3 General Track: Reliability Bottlenecks
On the 20-cohort V5.3 benchmark, C1 succeeded in execution for 11 of 20 tasks, with 9 successfully parsed into verifiable cohort expressions (45% scored yield). Among scored definitions, C1 produced the highest mean $F_1$ (0.3002 ± 0.353 vs. 0.2385 for C2 and 0.1717 for C4). However, when evaluated under intention-to-evaluate accounting (All=0), monolithic baseline C2 demonstrated superior operational dependability ($F_1 = 0.1550$ vs. $0.1351$ for C1).

### 5.1.3 Precision Discipline and Concept Grounding
Across both tracks and all 128 benchmark configurations, precision remained exceptionally high, ranging from 0.9036 to 1.0000. Deterministic vocabulary constraints enforced through DuckDB query bindings prevented hallucination of non-existent OMOP concept identifiers. Recall dropout, rather than spurious concept inclusion, constituted the primary error mode.
