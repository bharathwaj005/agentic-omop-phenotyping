# 1. Introduction

Real-World Evidence (RWE) derived from observational electronic health record (EHR) and administrative claims databases plays an increasingly critical role in evaluating post-market drug safety, comparative effectiveness, and clinical outcomes [1]. Central to the validity of any observational study is computable phenotyping: the systematic identification of patient cohorts satisfying clinical inclusion, exclusion, and temporal criteria [2]. Within international consortia such as the Observational Health Data Sciences and Informatics (OHDSI) collaborative, phenotype definitions are operationalized against the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM) [11, 12]. Despite standardization, constructing cohort definitions manually remains a major bottleneck in the clinical research life cycle, often requiring weeks of iterative manual concept mapping across standardized vocabularies (e.g., SNOMED-CT, RxNorm, ICD-10) and complex relational rule engineering [2, 10].

Recent advances in large language models (LLMs) and agentic workflow orchestration have catalyzed interest in automating observational study pipelines [3, 4, 5, 9]. Unlike passive text generation, agentic architectures incorporate autonomous planning, iterative tool execution (such as SQL querying and vocabulary database lookup), self-reflection, and programmatic validation [2, 9]. However, a fundamental question remains open: *does the operational complexity of multi-agent modular architectures translate into demonstrable, trustworthy improvements in observational cohort fidelity?* [7].

Neurological and neurodegenerative phenotypes are a demanding test of this question. Their vocabularies are deep and hierarchical, and research on neuroinflammation in Alzheimer's disease (AD) depends on accurate definitions of both dementia outcomes and inflammatory exposures, an area in which observational estimates have proved sensitive to study design [14].

Existing explorations of AI-assisted phenotyping leave four gaps:
1. **Concept retrieval rather than cohort construction:** Many evaluations score single concept-set lookups rather than complete, executable cohort definitions that incorporate index events, observation windows, demographic bounds, and exclusion logic [10].
2. **Dependence on hosted cloud APIs:** Prior agentic frameworks frequently route clinical logic through commercial cloud endpoints, which raises data-governance concerns for healthcare institutions [4, 6].
3. **Absence of controlled ablation:** Multi-agent components are rarely decoupled under identical deadlines and budgets, leaving unclear which sub-agent provides measurable value [7, 8].
4. **Single-arm references:** Phenotype libraries often support disjunctive entry pathways; references that ignore them penalize systems that correctly identify valid alternative entry paths.

This study provides a controlled, fully reproducible evaluation of multi-agent versus single-agent phenotyping using an open-weights, 7-billion-parameter model (`qwen2.5:7b`) executing on consumer-grade hardware (Intel Core i3-N305, 8 GB RAM, CPU only).

### Contributions
1. **Controlled multi-agent versus single-agent benchmark:** Four ablated configurations (C1: full multi-agent; C2: single agent; C3: no critic; C4: no validator) under identical resource ceilings, on general and neurological tracks.
2. **Full-pipeline cohort execution:** Complete, machine-executable JSON cohort specifications capturing index events, inclusion and exclusion criteria, and domain assignments.
3. **Multi-arm reference correction:** 11 of 20 general-track OHDSI tasks have alternative entry criteria; single-arm references would penalize valid alternative entry paths.
4. **Local low-resource feasibility:** The operational envelope of agentic clinical workflows executed entirely on edge hardware, with no data leaving the device.
5. **Error anatomy:** Hierarchy-aware analysis and an AD neuroinflammation extension track that trace performance differences to a specific, detectable failure (omitted concept descendants), with practical safeguards for agent-assisted phenotyping.
6. **Transparent accounting:** A failure taxonomy, dual-denominator reporting, robustness re-runs, and a public release of all code, prompts, references and run logs.

---
