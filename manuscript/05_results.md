# 4. Results

## 4.1 Primary Performance Across Tracks

Table 1 summarizes computable phenotype extraction performance across the V5.3 General (N = 20) and Neurological (N = 12) benchmark tracks under dual-denominator accounting.

| Track | Config | Scored | Mean F1 (Scored) | Mean F1 (All=0) | Mean Recall | Mean Precision |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **V5.3 General** | C1 | 11 / 20 | 0.2477 ± 0.337 | 0.1362 | 0.1953 | 0.9012 |
| **V5.3 General** | C2 | 14 / 20 | 0.2215 ± 0.315 | 0.1550 | 0.1711 | 0.8390 |
| **V5.3 General** | C3 | 15 / 20 | 0.1998 ± 0.300 | 0.1498 | 0.1762 | 0.8800 |
| **V5.3 General** | C4 | 16 / 20 | 0.1517 ± 0.299 | 0.1213 | 0.1231 | 0.9375 |
| **NEURO Track** | C1 | 12 / 12 | 0.6208 ± 0.410 | 0.6208 | 0.6082 | 0.9295 |
| **NEURO Track** | C2 | 11 / 12 | 0.3242 ± 0.362 | 0.2972 | 0.2597 | 1.0000 |
| **NEURO Track** | C3 | 12 / 12 | 0.3556 ± 0.311 | 0.3556 | 0.2700 | 1.0000 |
| **NEURO Track** | C4 | 12 / 12 | 0.3473 ± 0.308 | 0.3473 | 0.2700 | 0.9583 |

*Table 1: Dual-denominator benchmarking results. Scored = runs that produced a resolvable concept specification, evaluated against Reference v2 (runs with no overlap count as F1 = 0); All=0 additionally assigns zero to failed, unparsable and timed-out runs. Recall and precision are means over scored runs.*

Figure 1 shows the distribution of exact F1 on scored tasks for each configuration and track.

![Figure 1. Exact F1 on scored tasks by configuration for the V5.3 general track (left) and the Neurological track (right). Boxes show the interquartile range, the orange line the median, whiskers 1.5 × IQR; circles are outlying tasks.](results/analysis_tier1_20261028/f1_boxplots.png)

### 4.1.1 Neurological Track: Domain-Specific Agentic Advantage
In the Neurological track, the full multi-agent pipeline (C1) completed all 12 tasks (100% completion) and achieved a mean F1 of 0.6208 ± 0.410, with a mean concept recall of 0.6082 compared with 0.2597 for single-agent C2 and 0.2700 for both critic-ablated C3 and validator-ablated C4 (Figure 1).

Table 2 presents paired statistical comparisons anchored on C1.

| Track | Comparison | n | W / T / L | Median Δ | Mean Δ | 95% bootstrap CI | p | p (Holm) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| V5.3 | C1 vs C2 | 10 | 3 / 4 / 3 | 0.0000 | +0.0398 | [-0.0551, 0.1547] | 0.8438 | 0.8438 |
| V5.3 | C1 vs C3 | 11 | 3 / 8 / 0 | 0.0000 | +0.0421 | [0.0000, 0.1037] | 0.2500 | 0.5000 |
| V5.3 | C1 vs C4 | 11 | 4 / 7 / 0 | 0.0000 | +0.0467 | [0.0003, 0.1059] | 0.1250 | 0.3750 |
| **NEURO** | **C1 vs C2** | 11 | 7 / 3 / 1 | +0.0288 | +0.3190 | [0.0638, 0.5777] | 0.0391 | 0.0938 |
| **NEURO** | **C1 vs C3** | 12 | 6 / 5 / 1 | +0.1500 | +0.2651 | [0.0888, 0.4514] | 0.0312 | 0.0938 |
| **NEURO** | **C1 vs C4** | 12 | 6 / 5 / 1 | +0.1517 | +0.2735 | [0.0971, 0.4597] | 0.0312 | 0.0938 |

*Table 2: Paired comparisons anchored on configuration C1 over tasks scored by both configurations (W / T / L = wins / ties / losses for C1; Δ = C1 minus comparator F1). p = two-sided Wilcoxon signed-rank test; p (Holm) = Holm–Bonferroni adjustment within each track.*

Bootstrap 95% confidence intervals (10,000 resamples) excluded zero for all three comparisons in the Neurological track (mean paired differences +0.2651 to +0.3190; lower 95% CI bounds +0.0638 to +0.0971). Uncorrected Wilcoxon tests were nominally significant for all three comparisons (p = 0.0391 versus C2 and p = 0.0312 versus C3 and C4), but Holm–Bonferroni adjustment yields p = 0.0938 for each. The consistent direction of the paired differences suggests that the cooperative multi-agent architecture improves concept recall in targeted clinical domains, although this effect does not survive family-wise correction and should be confirmed on larger task sets.

### 4.1.2 V5.3 General Track: Reliability Bottlenecks
On the 20-cohort V5.3 benchmark, C1 produced a scored concept specification for 11 of 20 tasks (55%), compared with 14, 15 and 16 for C2, C3 and C4. C1's nine failures comprised four unconverged validator-repair loops, two repeated tool-call loops, two infrastructure failures and one structured-output schema error. Among scored runs, C1 produced the highest mean F1 (0.2477 ± 0.337 vs. 0.2215 for C2, 0.1998 for C3 and 0.1517 for C4). Under intention-to-evaluate accounting (All=0), however, monolithic baseline C2 was more dependable (F1 = 0.1550 vs. 0.1362 for C1). No V5.3 paired comparison was significant (Holm-adjusted p ≥ 0.375), although the bootstrap CI for C1 versus C4 marginally excluded zero ([0.0003, 0.1059]).

Figure 2 relates per-task F1 to wall-clock runtime. Most runs completed in roughly 100–350 seconds per task, well inside the 1,200-second deadline; high-F1 runs occurred across the runtime range, so longer runtime did not reliably buy higher quality.

![Figure 2. Cost–quality view of every scored run: exact F1 against wall-clock seconds per task, by configuration, for the V5.3 general track (left) and the Neurological track (right).](results/analysis_tier1_20261028/pareto_cost_quality.png)

### 4.1.3 Precision Discipline and Concept Grounding
Across both tracks, mean precision remained high in all eight track–configuration arms, ranging from 0.8390 to 1.0000 (computed over scored runs). All 47 distinct concept identifiers selected in scored runs exist in the installed OMOP vocabulary (47 standard), consistent with the deterministic vocabulary constraints enforced through DuckDB query bindings. Recall dropout, rather than spurious concept inclusion, constituted the primary error mode.
