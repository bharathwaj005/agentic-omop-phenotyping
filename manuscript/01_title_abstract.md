<!-- src: manuscript/01_title_abstract.md -->
# Do Agentic AI-Generated Cohort Definitions Preserve Real-World Evidence? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping on OMOP

## Highlights
- Controlled evaluation of multi-agent vs. single-agent OMOP cohort extraction.
- Fully local execution using quantized 7B LLM on consumer CPU (8 GB RAM).
- Multi-agent critique significantly outperformed ablated variants in neuro phenotypes.
- Execution reliability, not semantic hallucination, proved to be the primary failure bottleneck.
- Multi-arm entry corrections proved essential to prevent false-negative phenotypic scoring.

## Abstract
**Objective:** Real-world evidence (RWE) studies rely on computable phenotype definitions across standardized common data models such as the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM). While agentic large language model (LLM) architectures show promise in translating unstructured clinical questions into formal cohort specifications, whether modular multi-agent architectures justify their computational and latency overhead in resource-constrained environments remains unresolved. We sought to determine whether a specialized multi-agent framework improves phenotype fidelity and preserves observational evidence relative to single-agent baselines under strictly local, low-resource compute constraints.

**Methods:** We established a benchmark derived from the OHDSI Phenotype Library comprising a general phenotype track (V5.3, N=20) and a specialized Neurological track (N=12). Four system configurations were systematically ablated: C1 (full multi-agent with planner, concept resolver, critic, and schema validator), C2 (single agent with validator), C3 (multi-agent lacking critic), and C4 (multi-agent lacking validator). All systems executed locally via an 8-thread CPU without GPU acceleration (Intel Core i3-N305, 8 GB RAM) running quantized `qwen2.5:7b`. Phenotype fidelity was measured using dual-denominator concept metrics (F1, precision, recall vs. multi-arm corrected ground-truth specifications) alongside paired Wilcoxon signed-rank hypothesis tests with 10,000 bootstrap resamples.

**Results:** In the Neurological track, full multi-agent orchestration (C1) completed 12/12 tasks, achieving a scored-only mean F1 of 0.6208 ± 0.410 (recall 0.6082, precision 0.9295), achieving substantial improvements over ablated pipelines with 95% bootstrap CIs strictly above zero (C1 vs C3 mean diff +0.2651, 95% CI [0.0881, 0.4535], uncorrected p = 0.0312; C1 vs C4 mean diff +0.2735, 95% CI [0.0935, 0.4615], uncorrected p = 0.0312; non-significant after Holm-Bonferroni correction). In the broader V5.3 general track, C1 led scored tasks (F1 = 0.3002 ± 0.353, 9/20 complete), but multi-stage inter-agent repair deadlocks reduced its full-denominator completion score (F1 = 0.1351). Under an intention-to-evaluate denominator (failures = 0), single-agent baseline C2 proved most reliable (F1 = 0.1550, 13/20 complete). Precision remained high across all configurations (0.9036 to 1.0000), confirming that standard concept hallucination was rare.

**Conclusion:** Local multi-agent LLM systems can effectively generate complex observational cohort definitions without cloud data leakage, but their utility depends heavily on clinical domain density. While multi-agent critique significantly elevates concept recall in specialized therapeutic domains, compounding inter-agent repair loops represent the primary vulnerability in broad, multi-criteria cohort construction.

**Keywords:** Real-World Evidence; Observational Health Data Sciences and Informatics; OMOP Common Data Model; Computable Phenotyping; Agentic AI; Natural Language Processing.
