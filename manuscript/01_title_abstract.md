# How Faithfully Do Agentic AI Systems Generate OMOP Cohort Definitions? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping

**Author:** Bharathwaj^a,\*^

^a^ Department of Biotechnology, [INSTITUTION], [CITY], [COUNTRY]

^\*^ Corresponding author. E-mail: [EMAIL]

**Code and data:** https://github.com/bharathwaj005/agentic-omop-phenotyping (release v1.0-jbi-submission)

## Highlights
- Four local LLM pipeline designs compared on 32 OMOP cohort tasks in 128 runs
- All runs used a CPU-only laptop with 8 GB RAM; no GPU or cloud model calls
- Multi-agent pipeline reached mean F1 0.62 on neurological cohorts vs 0.32-0.36
- Same pattern on 12 Alzheimer's neuroinflammation phenotypes: F1 0.77 vs 0.35
- Omitted concept descendants, not wrong concepts, drove most errors

## Abstract
**Objective:** Computable phenotypes on the Observational Medical Outcomes Partnership (OMOP) Common Data Model underpin real-world evidence (RWE), but building them remains slow and expert-dependent. We tested whether a multi-agent large language model (LLM) pipeline generates more faithful OMOP cohort definitions than single-agent or ablated designs when run entirely on local, low-resource hardware, and we characterized the errors that agents make.

**Methods:** Thirty-two tasks derived from the OHDSI Phenotype Library formed a general track (V5.3, n = 20) and a neurological track (n = 12). Four configurations were compared: C1 (planner, concept resolver, builder, critic and validator), C2 (single agent with validator), C3 (no critic) and C4 (no validator), all using quantized `qwen2.5:7b` on a CPU-only laptop with 8 GB RAM (128 runs). Definitions were scored by exact concept-level F1 against multi-arm-corrected references under scored-only and intention-to-evaluate denominators, with paired Wilcoxon tests (Holm-adjusted) and bootstrap 95% confidence intervals (CIs). Secondary analyses credited matches within one or two levels of the concept hierarchy, and an extension track of 12 Alzheimer's disease (AD) neuroinflammation phenotypes (48 runs) examined error mechanisms.

**Results:** In the neurological track, C1 completed all 12 tasks with mean F1 0.62 versus 0.32–0.36 for the alternatives; bootstrap CIs of every paired difference excluded zero (versus C2: +0.32 [0.06, 0.58]), with Holm-adjusted p = 0.094. The AD neuroinflammation track showed the same pattern (C1 0.77 versus 0.35; Holm-adjusted p = 0.094). In the general track, C1 led on scored runs (0.25) while single-agent C2 completed more tasks, giving the highest intention-to-evaluate F1 (0.155). Precision was 0.84–1.00 in every arm: errors were omissions. All configurations usually selected the correct root concepts; the alternatives lost most of their score by omitting concept descendants, and one-level hierarchy credit raised their neurological F1 to 0.59–0.69.

**Conclusion:** Local agentic pipelines can draft OMOP cohort definitions without patient data leaving the institution. Multi-agent critique produced more complete definitions for neurological and AD-related phenotypes, and single-agent designs were more reliable for broad cohorts. Because the dominant error is a specific, detectable omission, deterministic hierarchy checks with clinician review offer a direct path to trustworthy agent-drafted phenotypes for dementia research.

**Keywords:** Real-World Evidence; Observational Health Data Sciences and Informatics; OMOP Common Data Model; Computable Phenotyping; Agentic AI; Alzheimer's Disease.

---
