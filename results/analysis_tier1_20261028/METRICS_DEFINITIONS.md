# Metric Definitions: Tier-1 Analysis (JBI Benchmark)

## 1. Concept-Level Metrics (Exact & Semantic)
- **Exact Matches**: Predicted concept ID equals Reference concept ID in OMOP CDM.
  - Precision = $|Pred \cap Ref| / |Pred|$
  - Recall = $|Pred \cap Ref| / |Ref|$
  - $F_1 = 2 \cdot P \cdot R / (P + R)$
  - Jaccard = $|Pred \cap Ref| / |Pred \cup Ref|$
- **Semantic / Hierarchy-Aware Matches ($L \in \{1, 2\}$)**:
  - Concept $c_{pred}$ matches $Ref$ if $\exists c_{ref} \in Ref$ such that $c_{pred} = c_{ref}$ OR $(c_{pred}, c_{ref})$ are related in `concept_ancestor` with `min_levels_of_separation <= L`.
  - Semantic Recall: Concept $c_{ref} \in Ref$ is covered if $\exists c_{pred} \in Pred$ related with distance $\le L$.

## 2. Evidence Fidelity Metrics (Patient-Level Eunomia CDM)
- **Approximation & Execution**:
  - Generated Cohort: Executed via compiler if valid syntax; otherwise evaluated using entry-event approximation (earliest event in person history within any entry arm's concept set in domain table).
  - Reference Cohort: Evaluated using identical entry-event approximation on ground-truth v2 reference concept sets.
- **Patient Overlap**:
  - Patient Sensitivity: $|Persons_{gen} \cap Persons_{ref}| / |Persons_{ref}|$
  - Patient PPV: $|Persons_{gen} \cap Persons_{ref}| / |Persons_{gen}|$
  - Patient Jaccard: $|Persons_{gen} \cap Persons_{ref}| / |Persons_{gen} \cup Persons_{ref}|$
- **Baseline Covariate Balance**:
  - Baseline window: 365 days prior to cohort index date.
  - Covariates: Top 20 condition concepts and Top 20 drug ingredient concepts prevalent in reference cohort.
  - Standardized Mean Difference: $SMD = (\bar{X}_{gen} - \bar{X}_{ref}) / \sqrt{(s_{gen}^2 + s_{ref}^2)/2}$.
  - Summary metrics: Mean $|SMD|$, Max $|SMD|$, and proportion with $|SMD| > 0.1$.
