# Hierarchy-aware concept metrics (secondary analysis)

k = maximum ancestor/descendant distance in `concept_ancestor` counted as a match; k = 0 is exact matching (primary analysis). Means over scored runs.

| Track | Config | Scored | F1 (exact, k=0) | F1 (k=1) | F1 (k=2) | Recall (k=1) | Recall (k=2) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NEURO | C1 | 12 | 0.6208 | 0.7063 | 0.7216 | 0.6779 | 0.6819 |
| NEURO | C2 | 11 | 0.3242 | 0.5854 | 0.6731 | 0.5129 | 0.6052 |
| NEURO | C3 | 12 | 0.3556 | 0.6728 | 0.7012 | 0.5942 | 0.6313 |
| NEURO | C4 | 12 | 0.3473 | 0.6895 | 0.7179 | 0.6220 | 0.6591 |
| V53 | C1 | 11 | 0.2477 | 0.2935 | 0.3324 | 0.2262 | 0.2553 |
| V53 | C2 | 14 | 0.2182 | 0.2742 | 0.3458 | 0.2018 | 0.2591 |
| V53 | C3 | 15 | 0.1997 | 0.2343 | 0.2740 | 0.1998 | 0.2274 |
| V53 | C4 | 16 | 0.1516 | 0.2147 | 0.2694 | 0.1611 | 0.2008 |

Check: max |k=0 F1 − official exact F1| = 4.51e-02 (should be ~0).
