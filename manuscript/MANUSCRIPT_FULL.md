<!-- src: manuscript/01_title_abstract.md -->
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

---

<!-- src: manuscript/02_introduction.md -->
# 1. Introduction

Real-World Evidence (RWE) derived from observational electronic health record (EHR) and administrative claims databases plays an increasingly critical role in evaluating post-market drug safety, comparative effectiveness, and clinical outcomes [1]. Central to the validity of any observational study is computable phenotyping: the systematic identification of patient cohorts satisfying clinical inclusion, exclusion, and temporal criteria [2]. Within international consortia such as the Observational Health Data Sciences and Informatics (OHDSI) collaborative, phenotype definitions are operationalized against the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM) [11, 12]. Despite standardization, constructing cohort definitions manually remains a major bottleneck in the clinical research life cycle, often requiring weeks of iterative manual concept mapping across standardized vocabularies (e.g., SNOMED-CT, RxNorm, ICD-10) and complex relational rule engineering [2, 10].

Recent advances in large language models (LLMs) and agentic workflow orchestration have catalyzed interest in automating observational study pipelines [3, 4, 5, 9]. Unlike passive text generation, agentic architectures incorporate autonomous planning, iterative tool execution (such as SQL querying and vocabulary database lookup), self-reflection, and programmatic validation [2, 9]. However, as recently highlighted in open questions raised by clinical bioinformatics researchers, a fundamental gap persists: *Does the operational complexity and resource consumption of multi-agent modular architectures translate into demonstrable, trustworthy improvements in observational cohort fidelity?* [7].

Existing explorations of AI-assisted phenotyping suffer from four critical limitations:
1. **Conflation of Concept Retrieval with Cohort Extraction:** Many preliminary evaluations evaluate only single medical concept set lookups rather than complete, executable cohort definitions that incorporate temporal index events, observation windows, demographic bounds, and exclusion logic [10].
2. **Dependence on Proprietary, Hosted Cloud APIs:** Prior agentic frameworks frequently route sensitive clinical logic through large commercial cloud-hosted endpoints (e.g., GPT-4), introducing significant data-governance concerns for clinical healthcare enterprises [4, 6].
3. **Absence of Controlled Ablation:** When multi-agent systems are evaluated, their components are rarely decoupled under identical execution deadlines and token budgets, leaving it unclear which sub-agent provides measurable value [7, 8].
4. **Uncorrected Multi-Arm Reference Bias:** Gold-standard phenotype repositories often support disjunctive clinical pathways. Failing to model these multi-arm entry criteria penalizes AI systems that correctly identify valid alternative clinical entry paths.

To resolve these challenges, this study provides a controlled, fully reproducible evaluation of multi-agent versus single-agent phenotyping using an open-weights, 7-billion parameter language model (`qwen2.5:7b`) executing strictly on consumer-grade hardware (Intel Core i3-N305, 8 GB RAM, CPU-only execution).

### Contributions
1. **Controlled Multi-Agent vs. Single-Agent Benchmark:** Four systematically ablated configurations (C1: full multi-agent; C2: single-agent; C3: multi-agent without critic; C4: multi-agent without validator) under identical resource ceilings.
2. **Full-Pipeline Cohort Execution:** Scored complete, machine-executable JSON cohort specifications capturing index dates, inclusion/exclusion criteria, and domain assignments.
3. **Multi-Arm Ground-Truth Correction:** Demonstrated that 11 of 20 core OHDSI tasks feature alternative entry criteria, showing that single-arm references can artificially penalize valid alternative entry paths.
4. **Local Low-Resource Feasibility:** Documented the operational envelope of executing agentic clinical workflows entirely on edge hardware without external data leakage.
5. **Failure Taxonomy and Dual-Denominator Accounting:** Documented every non-success through a rigorous taxonomy, reporting outcomes under both scored-only and full-intent denominators.

---

<!-- src: manuscript/03_related_work.md -->
# 2. Related Work

### Computable Phenotyping and Common Data Models
Computable phenotyping bridges the semantic divide between raw electronic health record entries and epidemiological research definitions [1, 2]. Standardized vocabularies within the OMOP CDM map disparate institutional coding systems into unified concept identifiers across clinical domains [11, 12]. While formal phenotype libraries provide peer-reviewed definitions, developing new phenotypes requires extensive manual curation [2, 10].

### Agentic AI in Clinical Research Workflows
The evolution of LLMs from passive sequence predictors into autonomous, goal-directed agentic systems has introduced new paradigms for health data science [2, 9]. Agentic systems leverage external tool invocation, multi-step memory, and deterministic validation guards [9]. Frameworks such as Causal-Copilot [3], TrialGenie [4], EHRFlow [5], and FastOMOP [6] have applied agentic loops to causal inference, clinical trial design, and script generation. 

However, systematic benchmarking by Liu et al. [7] and MedAgentBench [8] showed that agentic systems often exhibit compounding error trajectories. The necessity of multi-agent division of labor versus constrained single-agent prompting remains an open debate [7, 9].

### Comparison with Contemporary Phenotype Extraction Systems
The closest contemporary investigation to our work is that of Chen et al. (2026) [10], who evaluated agentic authoring of OMOP concept sets. Our investigation differs in four fundamental dimensions:
- **Scope of Generation:** Chen et al. focused on isolated concept sets. We synthesize full, executable cohort specifications comprising temporal index events, entry windows, demographic bounds, and exclusion logic.
- **Architectural Ablation:** We isolate multi-agent planning, iterative critique, and schema validation against a single-agent baseline under identical compute budgets.
- **Hardware Profile:** While Chen et al. leveraged hosted commercial cloud endpoints, our pipeline executes locally on consumer-grade hardware (Intel Core i3, 8 GB RAM).
- **Reference Topology:** We introduce multi-arm reference corrections to account for disjunctive entry criteria within the OHDSI Phenotype Library.

---

<!-- src: manuscript/04_methods.md -->
# 3. Methods

## System Architecture and Multi-Agent Orchestration
The multi-agent phenotyping pipeline decomposes cohort construction into specialized functional roles (`src/agents/`, `src/tools/`):
1. **Planner Agent:** Converts natural-language clinical phenotype descriptions into structured clinical plans with domains, inclusion rules, and exclusion constraints (`src/agents/concept.py`, `src/schema/spec.py`).
2. **Concept Resolver Agent:** Invokes local DuckDB vocabulary tools (`src/tools/vocab.py`) to search standard OMOP concepts (`concept_search`, `concept_ancestor`).
3. **Builder Agent:** Synthesizes mapped concept sets and temporal offset windows into machine-readable JSON cohort definitions conforming to repository schema (`src/schema/spec.py`).
4. **Critic Agent:** Audits intermediate cohort specifications against the initial clinical prompt, identifying missing clinical qualifiers and returning critique directives (`src/llm/prompts/critic.md`).
5. **Validator Agent:** Programmatic engine (`src/tools/validator.py`) executing syntactic validation (Pydantic schema adherence) and semantic validation (OMOP CDM domain checks).

## Evaluated Configurations
Defined in `src/runner/experiment.py`:
- **C1 (Full Multi-Agent System):** Planner + Concept Resolver + Builder + Critic + Validator (`use_critic=True, use_validator=True, single_agent=False`).
- **C2 (Single-Agent Baseline):** Unified agent with schema and semantic validation (`use_critic=False, use_validator=True, single_agent=True`).
- **C3 (Ablated Multi-Agent — No Critic):** Full pipeline with validator, omitting critique (`use_critic=False, use_validator=True, single_agent=False`).
- **C4 (Ablated Multi-Agent — No Validator):** Full pipeline with critique, omitting schema and domain validator (`use_critic=True, use_validator=False, single_agent=False`).

## Engineering Safeguards and Budget Controls
- **LLM Call Ceiling:** 30 model invocations per task (`src/runner/experiment.py`).
- **Validator Repair Budget:** Maximum 3 deterministic repair attempts (`src/tools/validator.py`).
- **Wall-Clock Deadline:** 1,200 seconds per task (`JBI_RUN_DEADLINE_S`).
- **Duplicate Tool Call Guard:** Immediate abort on repeated identical vocabulary queries (`src/tools/vocab.py`).
- **Read-Only Database Access:** Databases mounted strictly read-only (`data/vocab.duckdb`, `data/eunomia.duckdb`).

## Benchmark Construction and Multi-Arm Reference Correction
- **Core Benchmark Track (V5.3):** 20 diverse cohort tasks (T01–T20) from OHDSI Phenotype Library (`results/benchmark_design/V5_3_FREEZE/`).
- **Neurological Phenotype Track:** 12 targeted cohorts (N01–N12) covering neurodegenerative and neuroinflammatory conditions (`results/benchmark_design/NEURO_FREEZE/`).
- **Reference v2:** 11 of 20 core V5.3 tasks feature disjunctive multi-arm entry criteria. Reference v2 (`tasks/reference_v2/`) establishes the ground-truth concept set as the union of all valid entry arms, reducing artificial pairwise entry overlap from 0.722 in v1 to 0.139 in v2.

## Reference Correction for Task T10
During the final audit we found that task T10 (attention-deficit hyperactivity disorder based on condition or procedure evidence) had been linked to OHDSI Phenotype Library cohort 967 (4-point MACE) instead of cohort 1025 (first event of ADHD disorder or procedure) because of a cohort-identifier transcription error. The T10 reference was rebuilt from cohort 1025 and the stored T10 outputs were re-scored with the same resolver and metric code, without re-running any model; re-resolution reproduced every stored concept-set size exactly. The superseded reference and the re-scoring record (`results/analysis_tier1_20261028/rescore_overrides_T10.json`) are retained in the repository.

## Quantitative Evaluation Metrics
- **Concept matching:** exact OMOP `concept_id` agreement between the union of all resolved predicted concept sets and the Reference v2 concept set (`results/analysis_tier1_20261028/METRICS_DEFINITIONS.md`).
- **Scored runs:** a run is scored when it produced a resolvable concept specification. Scored runs whose predictions share no concept with the reference receive precision = recall = F1 = 0. Failed, timed-out or unparsable runs are unscored.
- **Dual-denominator reporting:** mean F1 over scored runs, and intention-to-evaluate mean F1 over all tasks with unscored runs set to 0 (All=0).
- **Retries:** runs stopped by an infrastructure fault (memory preflight stop) were re-executed once (T05, T11 and T17); all other runs use the first attempt. Remaining infrastructure failures are counted as failures.
- **Paired comparisons:** C1 versus each alternative on tasks scored by both configurations; two-sided Wilcoxon signed-rank tests with zero differences dropped; Holm–Bonferroni adjustment across the three comparisons within each track; percentile bootstrap 95% CIs of the mean paired difference (10,000 resamples of paired differences, seed `20261028`).

## Hardware and Local Inference
Acer One Z14-55N (Intel Core i3-N305, 8 cores / 8 threads, 8 GB DDR5 RAM, CPU only, Linux Mint). Model: quantized `qwen2.5:7b` [13] (Q4_K_M GGUF format via Ollama).

---

<!-- src: manuscript/05_results.md -->
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

---

<!-- src: manuscript/06_discussion.md -->
# 5. Discussion

## 5.1 Principal Findings & Trade-offs
This empirical benchmark provides a rigorous, two-sided evaluation of multi-agent LLM systems for automated computable phenotyping on the OMOP Common Data Model:

1. **Domain-Specific Expressivity (Neurological Track):** In targeted clinical domains with rich hierarchical concept spaces, full multi-agent cooperation (C1) raised mean concept recall to 0.6082 and achieved a mean F1 of 0.6208 ± 0.410, compared to single-agent C2 (mean F1 = 0.3242, recall 0.2597) and ablated baselines C3–C4 (~0.2700 recall). Bootstrap 95% confidence intervals excluded zero across all pairwise comparisons (mean paired differences +0.2651 to +0.3190; lower 95% CI bounds +0.0638 to +0.0971). While unadjusted Wilcoxon comparisons reached nominal significance for all three comparisons (p = 0.0312–0.0391), Holm–Bonferroni correction yields non-significance (p = 0.0938). Thus, the claim of multi-agent benefit rests on the uniform directionality of paired differences and bootstrap stability rather than unadjusted asymptotic significance.
2. **Operational Dependability (V5.3 General Track):** On complex multi-temporal phenotypes, execution reliability proved to be the primary operational bottleneck. C1 produced scored definitions for 11 of 20 tasks (mean scored F1 = 0.2477 vs. 0.2215 for C2). However, under intention-to-evaluate accounting (where unscored runs count as 0), monolithic single-agent prompting (C2) was more dependable overall (mean F1 = 0.1550 vs. 0.1362 for C1); this difference was not tested formally and should be read as descriptive.
3. **Precision Discipline:** Mean precision ranged from 0.8390 to 1.0000 across all eight track–configuration arms, computed over scored runs. None of the 47 selected concept identifiers was absent from the vocabulary, consistent with grounding candidate concepts through deterministic DuckDB vocabulary queries. Because C4 (no validator) had the highest V5.3 mean precision (0.9375), high precision is better attributed to grounded retrieval than to the validator.

## 5.2 Hypothesized Failure Mechanisms
We identify two distinct behavioral hypotheses to explain performance divergences across architectures:

- **Handoff Friction (Hypothesis):** In multi-agent pipelines, dividing responsibility across Planner, Concept Resolver, Builder, and Critic roles introduces intermediate communication boundaries. When clinical criteria involve nested disjunctive branches (such as Task T01: ADHD diagnosis vs. drug exposure criteria), semantic omissions in early planning cascade into incomplete cohort specifications downstream.
- **Premature Pruning (Hypothesis):** We hypothesize that single-agent baselines often experience premature cognitive closure, retrieving a narrow cluster of initial concepts while terminating search prior to exploring descendant hierarchies. Conversely, multi-agent pipelines explore deeper concept sets but face structural JSON formatting friction that risks premature pruning before the deterministic validator, discarding valid candidate concepts prior to evaluation.

## 5.3 Methodological Implications for Low-Resource RWE
Executing agentic AI pipelines on edge hardware (consumer 8-core CPU, 8 GB RAM) without external cloud leakage is technically viable for observational health research. However, we expect that realizing multi-agent expressivity will require grammar-guided decoding and robust schema constraints (not tested here) to prevent formatting attrition from nullifying semantic gains.

---

<!-- src: manuscript/07_limitations.md -->
# 6. Limitations

1. **Concept-level evaluation only:** Fidelity was assessed at the concept-set level against Reference v2. Patient-level agreement of the generated cohorts was not evaluated and remains future work.
2. **Single Local Model Scale:** Experiments were conducted using a single quantized 7B model (`qwen2.5:7b`) due to the 8 GB RAM consumer hardware budget.
3. **Single Run Allocation:** Primary benchmark tasks were executed as single deterministic passes under fixed seeds rather than multi-run stochastic distributions.
4. **Development Set Contamination:** System development utilized task T01. The remaining 19 tasks in V5.3 and all 12 tasks in Neuro were evaluated without task-specific optimization.
5. **Conditional paired comparisons (V5.3):** Paired tests are restricted to tasks scored by both configurations (10–11 of 20 in V5.3), a subset defined partly by C1 success; the comparisons therefore favour C1, and intention-to-evaluate means (All = 0) are reported alongside.
6. **Benchmark redundancy and reference error:** Three V5.3 tasks (T01, T06 and T10) target ADHD under different definitions, two neurological tasks (N06 and N07) target acute disseminated encephalomyelitis, and T08 and N01 both derive from the Imfeld Alzheimer's disease definition, so the effective diversity of the benchmark is lower than its task count. One reference (T10) was built from the wrong cohort and was corrected after the runs (Section 3); other reference errors of this kind cannot be fully excluded.

---

<!-- src: manuscript/08_conclusion.md -->
# 7. Conclusion

This investigation evaluated the evidence fidelity and operational limits of multi-agent versus single-agent phenotyping using a locally executed 7B large language model on consumer hardware. Multi-agent planning with iterative critique was associated with substantially higher concept recall in specialized clinical domains (mean recall 0.61 versus 0.26–0.27 for the alternatives), although the paired differences did not remain significant after Holm–Bonferroni correction. However, multi-agent architectures introduce substantial coordination overhead that reduces completion reliability in complex, multi-criteria general cohorts. For clinical bioinformaticians deploying local AI systems for RWE life cycle support, single-agent architectures with deterministic schema validators provide the most robust baseline, while multi-agent critique should be targeted to dense clinical domains.

---

<!-- src: manuscript/09_declarations.md -->
# Declarations

### Data and Code Availability
All experimental pipelines, prompts, schema validators, task definitions, and evaluation scripts are open-source and version-controlled. The complete benchmark suite, blinded clinical questions (`tasks/benchmark_questions.jsonl`), frozen manifests (`results/codex_20261025/freeze_manifest_OFFICIAL.json`), and run logs are available at: https://github.com/bharathwaj005/agentic-omop-phenotyping. The OMOP vocabulary tables are accessible via OHDSI Athena (https://athena.ohdsi.org). Pipeline execution checks use the public synthetic OMOP Eunomia dataset.

### Funding
This research received no specific grant from any funding agency in the public, commercial, or not-for-profit sectors.

### Competing Interests
The author declares that he has no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

### Author Contributions
Bharathwaj: Conceptualization, Methodology, Software, Formal analysis, Investigation, Data Curation, Writing - Original Draft, Writing - Review & Editing, Visualization.

### Ethics Statement
This study used only public vocabulary resources and synthetic data; no human participants or identifiable patient data were involved, so ethical approval was not required.

### Declaration of generative AI and AI-assisted technologies in the writing process
During the preparation of this work the author(s) used Claude, Gemini and OpenAI Codex in order to assist with code development, debugging, analysis scripts and drafting text. After using these tools, the author(s) reviewed and edited the content as needed and take(s) full responsibility for the content of the publication.

---

<!-- src: manuscript/10_references.md -->
# References

1. Friedman C, Rubin J, Brown J, et al. Toward a science of learning systems: a research agenda for the high-functioning Learning Health System. *Journal of the American Medical Informatics Association*. 2015;22(1):43-50. doi:10.1136/amiajnl-2014-002977.
2. Sapkota R, Roumeliotis KI, Karkee M. AI agents vs. agentic AI: a conceptual taxonomy, applications and challenges. *Information Fusion*. 2025:103599.
3. Wang X, et al. Causal-Copilot: an autonomous causal analysis agent. *arXiv preprint arXiv:2504.13263*. 2025.
4. Li H, Pan W, Rajendran S, Zang C, Wang F. TrialGenie: empowering clinical trial design with agentic intelligence and real world data. *medRxiv*. 2025.
5. Wu H, et al. EHRFlow: a large language model-driven iterative multi-agent electronic health record data analysis workflow. *KDD '24 Workshop*. 2024.
6. Moeller-Grell N, et al. FastOMOP: a foundational architecture for reliable agentic real-world evidence generation on OMOP CDM data. *arXiv preprint arXiv:2604.24572*. 2026.
7. Liu Y, et al. Benchmarking large language model-based agent systems for clinical decision tasks. *npj Digital Medicine*. 2026;9(1):259. doi:10.1038/s41746-026-02443-6.
8. Jiang Y, et al. MedAgentBench: a virtual EHR environment to benchmark medical LLM agents. *NEJM AI*. 2025;2(9). doi:10.1056/AIdbp2500144.
9. Bandi A, et al. The rise of agentic AI: a review of definitions, frameworks, architectures, applications, evaluation metrics, and challenges. *Future Internet*. 2025;17(9):404.
10. Chen H, He X, Dai H, Huang Y, Liu M, Bian J. Agentic authoring of OMOP concept sets from natural language. *medRxiv*. 2026. doi:10.64898/2026.06.02.26354704.
11. Overhage JM, Ryan PB, Reich CG, Hartzema AG, Stang PE. Validation of a common data model for active safety surveillance research. *Journal of the American Medical Informatics Association*. 2012;19(1):54-60. doi:10.1136/amiajnl-2011-000376.
12. Hripcsak G, Duke JD, Shah NH, et al. Observational Health Data Sciences and Informatics (OHDSI): opportunities for observational researchers. *Studies in Health Technology and Informatics*. 2015;216:574-578.
13. Qwen Team. Qwen2.5 technical report. *arXiv preprint arXiv:2412.15115*. 2024.
