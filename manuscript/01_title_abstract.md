# How Faithfully Do Agentic AI Systems Generate OMOP Cohort Definitions? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping

**Author:** Bharathwaj^a,\*^

^a^ Department of Biotechnology, [INSTITUTION], [CITY], [COUNTRY]

^\*^ Corresponding author. E-mail: [EMAIL]

**Code and data:** https://github.com/bharathwaj005/agentic-omop-phenotyping (release v1.0-jbi-submission)

## Highlights
- Four local LLM pipeline designs compared on 32 OMOP cohort tasks in 128 runs
- All runs used a CPU-only laptop with 8 GB RAM; no GPU or cloud model calls
- Multi-agent pipeline reached mean F1 0.62 on neurological cohorts vs 0.32-0.36
- Single-agent baseline produced more scorable general-track runs than C1 (14 vs 11)
- Errors were mostly missed concepts; mean precision was 0.84 or higher in every arm

## Abstract
**Objective:** Real-world evidence (RWE) studies rely on computable phenotype definitions across standardized common data models such as the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM). While agentic large language model (LLM) architectures show promise in translating unstructured clinical questions into formal cohort specifications, whether modular multi-agent architectures justify their computational and latency overhead in resource-constrained environments remains unresolved. We sought to determine whether a specialized multi-agent framework improves phenotype fidelity relative to single-agent baselines under strictly local, low-resource compute constraints.

**Methods:** We established a benchmark derived from the OHDSI Phenotype Library comprising a general phenotype track (V5.3, N=20) and a specialized Neurological track (N=12). Four system configurations were systematically ablated: C1 (full multi-agent with planner, concept resolver, critic, and schema validator), C2 (single agent with validator), C3 (multi-agent lacking critic), and C4 (multi-agent lacking validator). All systems executed locally via an 8-thread CPU without GPU acceleration (Intel Core i3-N305, 8 GB RAM) running quantized `qwen2.5:7b`. Phenotype fidelity was measured using dual-denominator concept metrics (F1, precision, recall vs. multi-arm corrected ground-truth specifications) with paired Wilcoxon signed-rank tests (Holm–Bonferroni adjusted) and percentile bootstrap 95% CIs (10,000 resamples).

**Results:** In the Neurological track, full multi-agent orchestration (C1) completed 12/12 tasks, achieving a scored-only mean F1 of 0.6208 ± 0.410 (recall 0.6082, precision 0.9295), with higher F1 than every alternative and bootstrap 95% CIs excluding zero for all three comparisons (vs C2 +0.3190 [0.0638, 0.5777]; vs C3 +0.2651 [0.0888, 0.4514]; vs C4 +0.2735 [0.0971, 0.4597]; uncorrected p = 0.039, 0.031 and 0.031; Holm-adjusted p = 0.094 for each). In the broader V5.3 general track, C1 led on scored runs (F1 = 0.2477 ± 0.337, 11/20 scored), but unconverged validator-repair loops and other failures lowered its intention-to-evaluate score (F1 = 0.1362). Under the intention-to-evaluate denominator (failures = 0), single-agent baseline C2 was most dependable (F1 = 0.1550, 14/20 scored). Mean precision was 0.8390 to 1.0000 across track–configuration arms, and every selected concept identifier exists in the OMOP vocabulary.

**Conclusion:** Local multi-agent LLM systems can effectively generate complex observational cohort definitions without cloud data leakage, but their utility depends heavily on clinical domain density. While multi-agent critique was associated with higher concept recall in specialized therapeutic domains, compounding inter-agent repair loops represent the primary vulnerability in broad, multi-criteria cohort construction.

**Keywords:** Real-World Evidence; Observational Health Data Sciences and Informatics; OMOP Common Data Model; Computable Phenotyping; Agentic AI; Natural Language Processing.
