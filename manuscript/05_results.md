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
In the Neurological track, the full multi-agent pipeline (C1) completed all 12 tasks and achieved a mean F1 of 0.6208 ± 0.410, with a mean concept recall of 0.6082 compared with 0.2597 for single-agent C2 and 0.2700 for both critic-ablated C3 and validator-ablated C4 (Figure 1).

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

C1 lost only one task in each comparison, and bootstrap 95% confidence intervals excluded zero for all three comparisons (mean paired differences +0.2651 to +0.3190; lower bounds +0.0638 to +0.0971). Unadjusted Wilcoxon tests were significant for all three comparisons (p = 0.0391 versus C2; p = 0.0312 versus C3 and C4), with Holm–Bonferroni-adjusted p = 0.0938 for each. Section 4.3 shows the same advantage, of similar size, on an independent set of 12 AD-related phenotypes.

### 4.1.2 V5.3 General Track: A Completion–Fidelity Trade-off
On the 20-cohort V5.3 benchmark, C1 produced a scored concept specification for 11 of 20 tasks, compared with 14, 15 and 16 for C2, C3 and C4. C1's nine non-scored runs comprised four unconverged validator-repair loops, two repeated tool-call loops, two infrastructure failures and one structured-output schema error. Among scored runs, C1 produced the highest mean F1 (0.2477 ± 0.337 vs. 0.2215 for C2, 0.1998 for C3 and 0.1517 for C4); under intention-to-evaluate accounting (All=0), single-agent C2 achieved the highest score (F1 = 0.1550 vs. 0.1362 for C1). No V5.3 paired comparison differed significantly (Holm-adjusted p ≥ 0.375); the bootstrap CI for C1 versus C4 excluded zero ([0.0003, 0.1059]). In a robustness analysis, the three cells whose retry ended with a dropped server connection (T05 C1, T11 C3, T17 C2) were re-executed a second time under the same frozen manifest: T05 C1 scored F1 = 0.2590, T11 C3 scored 0.0029 and T17 C2 timed out. With these results, C1 scored 12 of 20 tasks (scored mean F1 0.2486; All=0 0.1492 vs. 0.1550 for C2) and the paired comparisons were unchanged in direction and inference (unadjusted p ≥ 0.0625; Holm-adjusted p ≥ 0.19).

Figure 2 relates per-task F1 to wall-clock runtime. Most runs completed in roughly 100–350 seconds per task, well inside the 1,200-second deadline; high-F1 runs occurred across the runtime range, so longer runtime did not reliably buy higher quality.

![Figure 2. Cost–quality view of every scored run: exact F1 against wall-clock seconds per task, by configuration, for the V5.3 general track (left) and the Neurological track (right).](results/analysis_tier1_20261028/pareto_cost_quality.png)

### 4.1.3 Precision Discipline and Concept Grounding
Across both tracks, mean precision remained high in all eight track–configuration arms, ranging from 0.8390 to 1.0000 (computed over scored runs). The agents rarely included concepts outside the reference; omission, rather than spurious inclusion, was the dominant error mode.

## 4.2 Hierarchy-Aware Error Analysis

Table 3 re-scores every scored run with tolerance for adjacent concepts in the vocabulary hierarchy.

| Track | Config | Scored | F1 (exact) | F1 (k = 1) | F1 (k = 2) | Recall (k = 1) | Recall (k = 2) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| NEURO | C1 | 12 | 0.6208 | 0.7063 | 0.7216 | 0.6779 | 0.6819 |
| NEURO | C2 | 11 | 0.3242 | 0.5854 | 0.6731 | 0.5129 | 0.6052 |
| NEURO | C3 | 12 | 0.3556 | 0.6728 | 0.7012 | 0.5942 | 0.6313 |
| NEURO | C4 | 12 | 0.3473 | 0.6895 | 0.7179 | 0.6220 | 0.6591 |
| V5.3 | C1 | 11 | 0.2477 | 0.2935 | 0.3324 | 0.2262 | 0.2553 |
| V5.3 | C2 | 14 | 0.2215 | 0.2742 | 0.3458 | 0.2018 | 0.2591 |
| V5.3 | C3 | 15 | 0.1998 | 0.2343 | 0.2740 | 0.1998 | 0.2274 |
| V5.3 | C4 | 16 | 0.1517 | 0.2147 | 0.2694 | 0.1611 | 0.2008 |

*Table 3: Hierarchy-aware concept agreement. k = maximum ancestor/descendant distance in the OMOP concept_ancestor table counted as a match; k = 0 equals the primary exact F1. Means over scored runs.*

In the neurological track, allowing one hierarchy level raised the mean F1 of C2, C3 and C4 from 0.32–0.36 to 0.59–0.69, while C1 rose from 0.62 to 0.71; at k = 2 all configurations reached 0.67–0.72. The alternatives therefore located the correct clinical region of the vocabulary but stopped short of the exact concept set, whereas C1 more often produced the precise set used by expert-curated definitions. In the V5.3 track the gains were smaller (C1: 0.25 to 0.29 at k = 1), indicating that errors there arise mainly from missing concept groups and non-scored runs rather than adjacent concept choices.

## 4.3 Extension: Alzheimer's Disease Neuroinflammation Phenotypes

Table 4 summarizes the 48 runs of the ADN extension track; per-task results are given in Appendix Table A1.

| Config | Scored | Mean F1 (Scored) | Mean F1 (All=0) | n | W / T / L | Mean Δ | p | p (Holm) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| C1 | 12 / 12 | 0.7654 | 0.7654 | — | — | — | — | — |
| C2 | 11 / 12 | 0.3518 | 0.3225 | 11 | 8 / 1 / 2 | +0.392 | 0.0488 | 0.0938 |
| C3 | 12 / 12 | 0.3486 | 0.3486 | 12 | 6 / 6 / 0 | +0.417 | 0.0312 | 0.0938 |
| C4 | 12 / 12 | 0.3489 | 0.3489 | 12 | 6 / 5 / 1 | +0.416 | 0.0312 | 0.0938 |

*Table 4: Alzheimer's disease neuroinflammation extension track (12 tasks × 4 configurations). Paired comparisons are C1 versus each configuration over tasks scored by both (W / T / L = wins / ties / losses for C1); p = two-sided Wilcoxon signed-rank test; p (Holm) = Holm–Bonferroni adjustment across the three comparisons.*

C1 again achieved the highest fidelity, completing all 12 tasks with mean F1 0.7654 and precision 1.00, against 0.35 for each alternative. The advantage (+0.39 to +0.42) was of the same magnitude as in the neurological track, C1 lost at most two tasks in any comparison, and the pattern of statistics matched the neurological track (unadjusted p = 0.031–0.049; Holm-adjusted p = 0.094). The single non-scored run (A08 C2) ended when the operating system terminated the inference server for lack of memory; a robustness re-run scored F1 = 1.00 and left the comparison unchanged (C2 mean 0.41; C1 versus C2 +0.359, Holm-adjusted p = 0.094).

Inspection of the generated definitions identified the mechanism. For Alzheimer's disease (A01), rheumatoid arthritis (A04) and major depressive disorder (A12), all four configurations selected the same correct standard concept, but only C1 set it to include descendants. The alternatives therefore matched only the root concept of references containing 35, 134 and 72 concepts respectively, and scored F1 = 0.01–0.06. Where an alternative did include descendants (sepsis, A10, under C3 and C4), it also reached F1 = 1.00. The advantage did not arise from privileged information: across all 48 runs the agents called only vocabulary tools (concept search, concept lookup, standard mapping, ancestor and descendant queries), none of which can access cohort definitions. Drug-exposure cohorts nested within a disease were the most demanding tasks for every configuration (A05, JAK inhibitor new users in rheumatoid arthritis: F1 ≈ 0.70; A06, TNFα inhibitor new users in Crohn's disease: F1 ≤ 0.16).

---
