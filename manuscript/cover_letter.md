Dear Editors of the Special Issue on Agentic AI for Real-World Evidence Life Cycle Support,

We submit our original research manuscript titled:

"How Faithfully Do Agentic AI Systems Generate OMOP Cohort Definitions? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping"

for consideration for publication in the Journal of Biomedical Informatics (Elsevier).

This work presents an empirical benchmark evaluating multi-agent versus single-agent Large Language Model architectures for computable phenotype extraction on the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM). Benchmarking was conducted locally on low-resource hardware (consumer 8-core CPU, 8 GB RAM, no GPU, zero external network leakage) using quantized Qwen2.5-7B across two benchmark tracks: the V5.3 General track (20 phenotypes) and a targeted Neurological track (12 phenotypes).

Key findings include:
1. Domain-Specific Quality: On the Neurological track, the full cooperative multi-agent architecture (C1) achieved a mean F1 of 0.6208 ± 0.410 (recall 0.6082), compared with 0.3242–0.3556 for the alternatives; bootstrap 95% confidence intervals excluded zero for all three paired comparisons, although Holm-adjusted p-values were 0.094.
2. Operational Dependability: On complex multi-temporal cohorts (V5.3 track), execution reliability was the primary operational bottleneck: C1 led on scored runs (mean F1 0.2477, 11 of 20 tasks scored), but the single-agent baseline was more dependable under intention-to-evaluate accounting (mean F1 0.1550 versus 0.1362).
3. Precision Discipline: Mean precision ranged from 0.8390 to 1.0000 across all eight track–configuration arms; errors were dominated by missed concepts rather than incorrect ones.

The official frozen benchmark code, task specifications, and evaluation manifests are available at:
https://github.com/bharathwaj005/agentic-omop-phenotyping

This manuscript represents original work not submitted elsewhere. All authors have reviewed and approved the submission.

Sincerely,
Bharathwaj and Collaborators
Department of Biotechnology
bharathwaj@example.edu
