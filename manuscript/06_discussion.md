# 6. Discussion

## 6.1 Principal Findings & Trade-offs
This empirical benchmark provides a rigorous, two-sided evaluation of multi-agent LLM systems for automated computable phenotyping on the OMOP Common Data Model:

1. **Domain-Specific Expressivity (Neurological Track):** In targeted clinical domains with rich hierarchical concept spaces, full multi-agent cooperation (C1) doubled concept recall to 0.6082 and achieved a mean $F_1$ of 0.6208 ± 0.410, compared to single-agent C2 (mean $F_1 = 0.3242$, recall 0.2597) and ablated baselines C3–C4 (~0.2700 recall). Bootstrap 95% confidence intervals strictly excluded zero across all pairwise comparisons (+0.2651 to +0.3190). While unadjusted Wilcoxon comparisons vs. C3 and C4 reached nominal significance ($p = 0.0312$), family-wise error control via Holm-Bonferroni correction yields non-significance ($p \approx 0.09$). Thus, the claim of multi-agent benefit rests on the uniform directionality of paired differences and bootstrap stability rather than unadjusted asymptotic significance.
2. **Operational Dependability (V5.3 General Track):** On complex multi-temporal phenotypes, execution reliability proved to be the primary operational bottleneck. C1 completed execution on 11 of 20 tasks, with 9 successfully parsed into verifiable definitions (mean scored $F_1 = 0.3002$ vs. 0.2385 for C2). However, under intention-to-evaluate accounting (where unparsed runs are scored as 0), monolithic single-agent prompting (C2) proved more dependable overall (mean $F_1 = 0.1550$ vs. $0.1351$ for C1).
3. **Precision Discipline:** Precision remained strictly bounded between 0.9036 and 1.0000 across all 128 benchmark configurations. Grounding local models with deterministic DuckDB vocabulary queries prevented hallucination of invalid standard concept identifiers; concept recall dropout, rather than false-positive intrusion, constituted the primary error mode.

## 6.2 Hypothesized Failure Mechanisms
We identify two distinct behavioral hypotheses to explain performance divergences across architectures:

- **Handoff Friction (Hypothesis):** In multi-agent pipelines, dividing responsibility across Planner, Concept Resolver, Builder, and Critic roles introduces intermediate communication boundaries. When clinical criteria involve nested disjunctive branches (such as Task T01: ADHD diagnosis vs. drug exposure criteria), semantic omissions in early planning cascade into incomplete cohort specifications downstream.
- **Premature Pruning (Hypothesis):** We hypothesize that single-agent baselines often experience premature cognitive closure, retrieving a narrow cluster of initial concepts while terminating search prior to exploring descendant hierarchies. Conversely, multi-agent pipelines explore deeper concept sets but face structural JSON formatting friction that risks premature pruning before the deterministic validator, discarding valid candidate concepts prior to evaluation.

## 6.3 Methodological Implications for Low-Resource RWE
Executing agentic AI pipelines on edge hardware (consumer 8-core CPU, 8 GB RAM) without external cloud leakage is technically viable for observational health research. However, realizing multi-agent expressivity requires strict grammar-guided decoding and robust schema constraints to prevent formatting attrition from nullifying semantic gains.
