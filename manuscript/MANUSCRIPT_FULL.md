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

# 2. Related Work

### Computable Phenotyping and Common Data Models
Computable phenotyping bridges the semantic divide between raw electronic health record entries and epidemiological research definitions [1, 2]. Standardized vocabularies within the OMOP CDM map disparate institutional coding systems into unified concept identifiers across clinical domains [11, 12]. While formal phenotype libraries provide peer-reviewed definitions, developing new phenotypes requires extensive manual curation [2, 10].

### Agentic AI in Clinical Research Workflows
The evolution of LLMs from passive sequence predictors into autonomous, goal-directed agentic systems has introduced new paradigms for health data science [2, 9]. Agentic systems leverage external tool invocation, multi-step memory, and deterministic validation guards [9]. Frameworks such as Causal-Copilot [3], TrialGenie [4], EHRFlow [5], and FastOMOP [6] have applied agentic loops to causal inference, clinical trial design, and script generation.

However, systematic benchmarking by Liu et al. [7] and MedAgentBench [8] showed that agentic systems often exhibit compounding error trajectories. The necessity of multi-agent division of labor versus constrained single-agent prompting remains an open debate [7, 9].

### Comparison with Contemporary Phenotype Extraction Systems
The closest contemporary investigation is that of Chen et al. (2026) [10], who evaluated agentic authoring of OMOP concept sets. Our investigation differs in four dimensions:
- **Scope of generation:** Chen et al. focused on isolated concept sets. We generate full, executable cohort specifications comprising index events, entry windows, demographic bounds, and exclusion logic.
- **Architectural ablation:** We isolate multi-agent planning, iterative critique, and schema validation against a single-agent baseline under identical compute budgets.
- **Hardware profile:** Chen et al. used hosted commercial cloud endpoints; our pipeline executes locally on consumer-grade hardware (Intel Core i3, 8 GB RAM).
- **Reference topology:** We introduce multi-arm reference corrections to account for disjunctive entry criteria within the OHDSI Phenotype Library.

---

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
- **Core Benchmark Track (V5.3):** 20 diverse cohort tasks (T01–T20) from the OHDSI Phenotype Library (`results/benchmark_design/V5_3_FREEZE/`).
- **Neurological Phenotype Track:** 12 targeted cohorts (N01–N12) covering neurodegenerative and neuroinflammatory conditions (`results/benchmark_design/NEURO_FREEZE/`).
- **Reference v2:** 11 of 20 core V5.3 tasks feature disjunctive multi-arm entry criteria. Reference v2 (`tasks/reference_v2/`) establishes the ground-truth concept set as the union of all valid entry arms, reducing artificial pairwise entry overlap from 0.722 in v1 to 0.139 in v2.
- **Freezing:** task lists, questions, references and code were frozen with SHA-256 manifests before the official runs (`results/codex_20261025/freeze_manifest_OFFICIAL.json`).

## Reference Correction for Task T10
During the final audit we found that task T10 (attention-deficit hyperactivity disorder based on condition or procedure evidence) had been linked to OHDSI Phenotype Library cohort 967 (4-point MACE) instead of cohort 1025 (first event of ADHD disorder or procedure) because of a cohort-identifier transcription error. The T10 reference was rebuilt from cohort 1025 and the stored T10 outputs were re-scored with the same resolver and metric code, without re-running any model; re-resolution reproduced every stored concept-set size exactly. The superseded reference and the re-scoring record (`results/analysis_tier1_20261028/rescore_overrides_T10.json`) are retained in the repository.

## Quantitative Evaluation Metrics
- **Concept matching:** exact OMOP `concept_id` agreement between the union of all resolved predicted concept sets (restricted to standard concepts) and the Reference v2 concept set (`results/analysis_tier1_20261028/METRICS_DEFINITIONS.md`).
- **Scored runs:** a run is scored when it produced a resolvable concept specification. Scored runs whose predictions share no concept with the reference receive precision = recall = F1 = 0. Failed, timed-out or unparsable runs are unscored.
- **Dual-denominator reporting:** mean F1 over scored runs, and intention-to-evaluate mean F1 over all tasks with unscored runs set to 0 (All=0).
- **Retries:** runs stopped by an infrastructure fault (memory preflight stop) were re-executed once (T05, T11 and T17); all other runs use the first attempt. Remaining infrastructure failures are counted as failures. System logs show the local inference server was terminated by the operating system's out-of-memory killer within five minutes of two of these failed retries (T11 and T17).
- **Paired comparisons:** C1 versus each alternative on tasks scored by both configurations; two-sided Wilcoxon signed-rank tests with zero differences dropped; Holm–Bonferroni adjustment across the three comparisons within each track; percentile bootstrap 95% CIs of the mean paired difference (10,000 resamples of paired differences, seed `20261028`).

## Secondary Analyses
- **Hierarchy-aware matching:** For a tolerance of k levels, a predicted concept counts as a hit if it lies within k levels of any reference concept in the OMOP `concept_ancestor` table (as ancestor or descendant, by `min_levels_of_separation`), and a reference concept counts as recalled if it lies within k levels of any predicted concept. Predictions are restricted to standard concepts exactly as in the primary scorer; k = 0 reproduces the primary F1 of every scored run (maximum absolute difference 1.1 × 10⁻¹⁶). Because adjacent concepts are not clinically equivalent, these scores describe the nature of errors and are not used for inference (`scripts/hierarchy_aware_metrics.py`).
- **Alzheimer's neuroinflammation (ADN) extension track:** To examine error mechanisms in the phenotypes that AD neuroinflammation research depends on, we built 12 further tasks (A01–A12; Appendix Table A1) from OHDSI Phenotype Library cohorts: AD and dementia outcomes; delirium; chronic inflammatory and autoimmune exposures (rheumatoid arthritis, inflammatory bowel disease, psoriasis, systemic lupus erythematosus); acute infection and inflammation (sepsis, herpes simplex); major depressive disorder; and anti-inflammatory treatment (new users of JAK inhibitors in rheumatoid arthritis and of TNFα inhibitors in Crohn's disease). The track was designed after the primary analysis and frozen with its own manifest before any run (`results/codex_20261025/freeze_manifest_ADN.json`); references, configurations, settings, scoring, retry rules and tests were identical to the primary tracks. Generated definitions were inspected for four tasks (A01, A04, A10, A12), and the tool-call logs of all 48 runs were checked for any access to cohort definitions.

## Hardware and Local Inference
Acer One Z14-55N (Intel Core i3-N305, 8 cores / 8 threads, 8 GB DDR5 RAM, CPU only, Linux Mint). Model: quantized `qwen2.5:7b` [13] (Q4_K_M GGUF format via Ollama).

---

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

# 5. Discussion

## 5.1 Principal Findings
This benchmark provides a controlled evaluation of multi-agent LLM systems for automated computable phenotyping on the OMOP Common Data Model, with three principal findings.

1. **Multi-agent critique produces more complete definitions in neurological and AD-related phenotypes.** In the neurological track, C1 raised mean concept recall to 0.6082 and mean F1 to 0.6208, compared with 0.3242 for single-agent C2 and 0.3473–0.3556 for the ablated pipelines. Bootstrap confidence intervals excluded zero for every comparison, and an independent set of 12 AD neuroinflammation phenotypes reproduced an advantage of the same size (0.77 versus 0.35). The unadjusted tests were significant in both tracks and the Holm-adjusted p-values (0.094) narrowly exceeded 0.05; the consistency of direction, size and mechanism across two task sets makes this the most robust result of the study.
2. **Completion and fidelity trade off in broad cohorts.** On complex, multi-criteria general phenotypes, C1 achieved the highest fidelity on scored runs (0.2477), whereas single-agent C2 completed more tasks and achieved the highest intention-to-evaluate score (0.1550). Pipeline reliability, rather than concept selection, is the main lever for broad cohorts.
3. **Errors are omissions, and they are specific.** Precision ranged from 0.8390 to 1.0000 across all eight track–configuration arms. Because C4 (no validator) had the highest V5.3 precision (0.9375), high precision is best attributed to grounded vocabulary retrieval rather than to the validator. The errors that remain are omissions: near-miss concept choices (Section 4.2) and, above all, root concepts used without their descendants (Section 4.3).

## 5.2 Failure Mechanisms
Two mechanisms explain the divergences between architectures:

- **Handoff friction:** Dividing responsibility across Planner, Concept Resolver, Builder and Critic roles introduces communication boundaries. When criteria involve nested disjunctive branches (such as task T01: ADHD diagnosis versus drug exposure), omissions in early planning cascade into incomplete specifications and repair loops downstream, which explains C1's lower completion in the general track.
- **Premature closure:** Single-agent and ablated pipelines tend to stop after selecting a plausible root concept without extending it to its descendant hierarchy. The ADN extension provides direct evidence: all configurations chose the correct concept for Alzheimer's disease, rheumatoid arthritis and major depressive disorder, but only C1 included descendants in every inspected task. Neither critique alone (C4) nor validation alone (C3) was sufficient, which points to the combination of critique and validation, present only in C1, as the source of this behavior.

## 5.3 Implications for Alzheimer's Disease and Neuroinflammation Research
Observational studies of whether anti-inflammatory therapies, chronic inflammatory disease or infection alter dementia risk have produced inconsistent results, and large active-comparator analyses have attributed earlier protective associations to bias [14]. Phenotype construction is a direct and under-examined source of such bias. Our results identify a concrete, mechanically detectable failure: an AD outcome concept used without its descendants retains only 1 of the 35 concepts in the OHDSI Alzheimer's disease definition used here, which would undercount outcomes and selectively miss patients whose diagnoses are coded at subtype level. The same omission occurred for inflammatory exposures (rheumatoid arthritis, systemic lupus erythematosus, depression), so it can affect both sides of an exposure–outcome analysis. Three safeguards follow for agent-assisted phenotyping in dementia research: (i) a deterministic check that flags condition concepts used without descendants unless the exclusion is intended; (ii) hierarchy-aware review of near-misses alongside exact agreement; and (iii) clinician review and patient-level validation (for example with OHDSI PheValuator or CohortDiagnostics) before any effect estimate. Each is inexpensive, and together they target the error classes observed in this study.

## 5.4 Implications for Low-Resource RWE
Executing agentic AI pipelines on edge hardware (consumer 8-core CPU, 8 GB RAM) without external data transfer is technically viable for observational health research, which matters for institutions that cannot send clinical logic to cloud services. Multi-agent designs suit dense clinical domains, and single-agent designs with deterministic validators provide a dependable baseline for broad cohorts. Grammar-guided decoding and stricter schema constraints are promising next steps to reduce the formatting-related repair loops that limited multi-agent completion.

---

# 6. Limitations

1. **Concept-level evaluation:** Fidelity was assessed at the concept-set level against Reference v2, the standard for vocabulary fidelity; patient-level agreement of the generated cohorts is the natural next step.
2. **Model and run scale:** Experiments used a single quantized 7B model (`qwen2.5:7b`), matching the 8 GB RAM hardware target, with one deterministic pass per task and configuration. The open release allows replication with other models and repeated runs.
3. **Multiplicity and design:** Neurological and ADN comparisons were significant before but not after Holm–Bonferroni adjustment (p = 0.094); the ADN track and the hierarchy-aware analysis were designed after the primary results, although the ADN track was frozen before its runs. V5.3 paired tests are restricted to tasks scored by both configurations, so intention-to-evaluate means are reported alongside.
4. **Benchmark composition:** System development used task T01 only. Some tasks share a target condition (T01, T06 and T10: ADHD; N06 and N07: acute disseminated encephalomyelitis; T08, N01 and A01: Alzheimer's disease under different definitions), and one reference (T10) was corrected after the runs by re-scoring stored outputs (Section 3).

---

# 7. Conclusion

A locally executed 7B language model on consumer hardware can draft OMOP cohort definitions with high precision and without any data leaving the institution. Multi-agent planning with iterative critique produced substantially more complete definitions for neurological and Alzheimer's disease-related phenotypes (mean F1 0.62 and 0.77 versus 0.32–0.36 and 0.35), while single-agent designs with deterministic validators were the most dependable for broad, multi-criteria cohorts. The dominant error, a correct concept used without its descendants, is specific and detectable. For clinical informaticians deploying local AI for RWE, and for dementia researchers who depend on accurate outcome and exposure phenotypes, the practical recipe is to target multi-agent critique to dense clinical domains and to pair agent-drafted definitions with deterministic hierarchy checks and clinician review.

---

# Declarations

### Data and Code Availability
All experimental pipelines, prompts, schema validators, task definitions, and evaluation scripts are open-source and version-controlled. The complete benchmark suite, blinded clinical questions (`tasks/benchmark_questions.jsonl`, `tasks/adn/`), frozen manifests (`results/codex_20261025/freeze_manifest_OFFICIAL.json`, `results/codex_20261025/freeze_manifest_ADN.json`), run logs, robustness re-runs and secondary analyses (`docs/SENSITIVITY_ANALYSES.md`, `docs/AD_NEUROINFLAMMATION_TRACK.md`) are available at: https://github.com/bharathwaj005/agentic-omop-phenotyping. The OMOP vocabulary tables are accessible via OHDSI Athena (https://athena.ohdsi.org). Pipeline execution checks use the public synthetic OMOP Eunomia dataset.

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

# Appendix A. Supplementary Data

| Task | OHDSI cohort | Phenotype | Role | Ref. size | C1 | C2 | C3 | C4 |
| :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| A01 | 100 | Alzheimer's disease | Outcome | 35 | 1.00 | 0.06 | 0.06 | 0.06 |
| A02 | 651 | Dementia | Outcome | 216 | 0.28 | 1.00 | 0.28 | 0.28 |
| A03 | 95 | Delirium | Acute brain dysfunction | 60 | 0.96 | 0.96 | 0.03 | 0.03 |
| A04 | 457 | Rheumatoid arthritis | Chronic inflammation | 134 | 1.00 | 0.01 | 0.01 | 0.01 |
| A05 | 1070 | JAK inhibitor new users (RA) | Treatment | 252 | 0.70 | 0.69 | 0.70 | 0.70 |
| A06 | 1069 | TNFα inhibitor new users (Crohn's) | Treatment | 508 | 0.00 | 0.16 | 0.00 | 0.01 |
| A07 | 629 | Inflammatory bowel disease | Chronic inflammation | 80 | 1.00 | 0.93 | 1.00 | 1.00 |
| A08 | 475 | Psoriasis | Chronic inflammation | 80 | 1.00 | — (1.00) | 1.00 | 1.00 |
| A09 | 509 | Systemic lupus erythematosus | Autoimmune exposure | 33 | 1.00 | 0.00 | 0.06 | 0.06 |
| A10 | 463 | Sepsis | Acute inflammation | 155 | 1.00 | 0.01 | 1.00 | 1.00 |
| A11 | 615 | Herpes simplex | Infection | 156 | 0.25 | 0.01 | 0.01 | 0.01 |
| A12 | 699 | Major depressive disorder | Neuropsychiatric comorbidity | 72 | 1.00 | 0.03 | 0.03 | 0.03 |

*Table A1: Alzheimer's disease neuroinflammation extension track: tasks, OHDSI Phenotype Library cohorts, reference concept-set sizes and exact F1 per configuration. — = non-scored run (inference server terminated for lack of memory); the value in parentheses is the robustness re-run.*

---

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
14. Desai RJ, Varma VR, Gerhard T, et al. Comparative risk of Alzheimer disease and related dementia among Medicare beneficiaries with rheumatoid arthritis treated with targeted disease-modifying antirheumatic agents. *JAMA Network Open*. 2022;5(4):e226567. doi:10.1001/jamanetworkopen.2022.6567.
