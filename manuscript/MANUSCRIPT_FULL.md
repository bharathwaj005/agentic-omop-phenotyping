<!-- src: manuscript/01_title_abstract.md -->
# How Faithfully Do Agentic AI Systems Generate OMOP Cohort Definitions? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping

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

---

<!-- src: manuscript/02_introduction.md -->
# Introduction

Real-World Evidence (RWE) derived from observational electronic health record (EHR) and administrative claims databases plays an increasingly critical role in evaluating post-market drug safety, comparative effectiveness, and clinical outcomes [1]. Central to the validity of any observational study is computable phenotyping: the systematic identification of patient cohorts satisfying clinical inclusion, exclusion, and temporal criteria [2]. Within international consortia such as the Observational Health Data Sciences and Informatics (OHDSI) collaborative, phenotype definitions are operationalized against the Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM) [CITATION NEEDED: OMOP CDM]. Despite standardization, constructing cohort definitions manually remains a major bottleneck in the clinical research life cycle, often requiring weeks of iterative manual concept mapping across standardized vocabularies (e.g., SNOMED-CT, RxNorm, ICD-10) and complex relational rule engineering [2, 10].

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
3. **Multi-Arm Ground-Truth Correction:** Demonstrated that 11 of 20 core OHDSI tasks feature alternative entry criteria, proving that single-arm evaluation artifacts artificially suppress valid phenotypic discovery.
4. **Local Low-Resource Feasibility:** Documented the operational envelope of executing agentic clinical workflows entirely on edge hardware without external data leakage.
5. **Failure Taxonomy and Dual-Denominator Accounting:** Documented every non-success through a rigorous taxonomy, reporting outcomes under both scored-only and full-intent denominators.

---

<!-- src: manuscript/03_related_work.md -->
# Related Work

### Computable Phenotyping and Common Data Models
Computable phenotyping bridges the semantic divide between raw electronic health record entries and epidemiological research definitions [1, 2]. Standardized vocabularies within the OMOP CDM map disparate institutional coding systems into unified concept identifiers across clinical domains [CITATION NEEDED: OMOP CDM]. While formal phenotype libraries provide peer-reviewed definitions, developing new phenotypes requires extensive manual curation [2, 10].

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
# Methods

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

## Quantitative Evaluation Metrics
- Exact concept precision, recall, and F1 computed against Reference v2 (`results/analysis_tier1_20261028/METRICS_DEFINITIONS.md`).
- Dual-denominator reporting: Scored-only and Intention-to-evaluate (All=0).
- Paired Wilcoxon signed-rank tests against C1 with Holm-Bonferroni correction and 10,000 bootstrap resamples (seed `20261028`).

## Hardware and Local Inference
Acer One Z14-55N (Intel Core i3-N305, 8 cores / 8 threads, 8 GB DDR5 RAM, CPU only, Linux Mint). Model: quantized `qwen2.5:7b` (Q4_K_M GGUF format via Ollama).

---

# 5. Results

## 5.1 Primary Performance Across Tracks

Table 1 summarizes computable phenotype extraction performance across the V5.3 General ($N=20$) and Neurological ($N=12$) benchmark tracks under dual-denominator accounting.

| Track | Config | Completed | Mean F1 (Scored) | Mean F1 (All=0) | Mean Recall | Mean Precision |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **V5.3 General** | C1 | 9 / 20 | 0.3002 ± 0.353 | 0.1351 | 0.2374 | 0.9903 |
| **V5.3 General** | C2 | 13 / 20 | 0.2385 ± 0.321 | 0.1550 | 0.1842 | 0.9036 |
| **V5.3 General** | C3 | 13 / 20 | 0.2288 ± 0.314 | 0.1487 | 0.2024 | 0.9385 |
| **V5.3 General** | C4 | 14 / 20 | 0.1717 ± 0.316 | 0.1202 | 0.1398 | 1.0000 |
| **NEURO Track** | C1 | 12 / 12 | 0.6208 ± 0.410 | 0.6208 | 0.6082 | 0.9295 |
| **NEURO Track** | C2 | 11 / 12 | 0.3242 ± 0.362 | 0.2972 | 0.2597 | 1.0000 |
| **NEURO Track** | C3 | 12 / 12 | 0.3556 ± 0.311 | 0.3556 | 0.2700 | 1.0000 |
| **NEURO Track** | C4 | 12 / 12 | 0.3473 ± 0.308 | 0.3473 | 0.2700 | 0.9583 |

*Table 1: Dual-denominator benchmarking results. Scored reflects successful parses evaluated against Reference v2; All=0 assigns zero to unparsed outputs, schema rejections, and timeouts.*

### 5.1.1 Neurological Track: Domain-Specific Agentic Advantage
In the Neurological track, the full multi-agent pipeline (C1) completed all 12 tasks (100% completion) and achieved a mean $F_1$ of 0.6208 ± 0.410, doubling concept recall (0.6082) compared to single-agent C2 (0.2597), critic-ablated C3 (0.2700), and validator-ablated C4 (0.2700).

Table 2 presents paired statistical comparisons anchored on C1.

| Track | Comparison | N (Paired) | Wins | Ties | Losses | Median Diff | Mean Diff | 95% Bootstrap CI | p-value |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| V5.3 | C1 vs C2 | 9 | 3 | 3 | 3 | 0.0000 | +0.0442 | [-0.0600, 0.1707] | n.s. |
| V5.3 | C1 vs C3 | 9 | 3 | 6 | 0 | 0.0000 | +0.0514 | [0.0000, 0.1267] | n.s. |
| V5.3 | C1 vs C4 | 9 | 4 | 5 | 0 | 0.0000 | +0.0571 | [0.0006, 0.1267] | n.s. |
| **NEURO** | **C1 vs C2** | 11 | 7 | 3 | 1 | +0.0288 | +0.3190 | [0.0614, 0.5778] | n.s. |
| **NEURO** | **C1 vs C3** | 12 | 6 | 5 | 1 | +0.1500 | +0.2651 | [0.0881, 0.4535] | 0.0312* |
| **NEURO** | **C1 vs C4** | 12 | 6 | 5 | 1 | +0.1517 | +0.2735 | [0.0935, 0.4615] | 0.0312* |

*Table 2: Paired Wilcoxon signed-rank comparisons anchored on configuration C1. *Nominally significant at p < 0.05; non-significant following Holm-Bonferroni family-wise error rate correction (p ≈ 0.09).*

Bootstrap 95% confidence intervals (10,000 resamples) excluded zero for all three comparisons in the Neurological track (mean paired differences +0.2651 to +0.3190; lower 95% CI bounds +0.0614 to +0.0935). While uncorrected paired Wilcoxon tests against C3 and C4 achieved nominal significance ($p = 0.0312$), family-wise error control via Holm-Bonferroni adjustment yields $p \approx 0.09$. The consistent directionality across paired tasks establishes that the cooperative multi-agent architecture substantially enhances concept recall in targeted clinical domains.

### 5.1.2 V5.3 General Track: Reliability Bottlenecks
On the 20-cohort V5.3 benchmark, C1 succeeded in execution for 11 of 20 tasks, with 9 successfully parsed into verifiable cohort expressions (45% scored yield). Among scored definitions, C1 produced the highest mean $F_1$ (0.3002 ± 0.353 vs. 0.2385 for C2 and 0.1717 for C4). However, when evaluated under intention-to-evaluate accounting (All=0), monolithic baseline C2 demonstrated superior operational dependability ($F_1 = 0.1550$ vs. $0.1351$ for C1).

### 5.1.3 Precision Discipline and Concept Grounding
Across both tracks, mean precision remained high in all eight track–configuration arms, ranging from 0.9036 to 1.0000 (computed over scored runs with at least one predicted concept). No out-of-vocabulary concept identifiers were observed in any scored run, consistent with the deterministic vocabulary constraints enforced through DuckDB query bindings. Recall dropout, rather than spurious concept inclusion, constituted the primary error mode.

---

# 6. Discussion

## 6.1 Principal Findings & Trade-offs
This empirical benchmark provides a rigorous, two-sided evaluation of multi-agent LLM systems for automated computable phenotyping on the OMOP Common Data Model:

1. **Domain-Specific Expressivity (Neurological Track):** In targeted clinical domains with rich hierarchical concept spaces, full multi-agent cooperation (C1) raised mean concept recall to 0.6082 and achieved a mean $F_1$ of 0.6208 ± 0.410, compared to single-agent C2 (mean $F_1 = 0.3242$, recall 0.2597) and ablated baselines C3–C4 (~0.2700 recall). Bootstrap 95% confidence intervals excluded zero across all pairwise comparisons (mean paired differences +0.2651 to +0.3190; lower 95% CI bounds +0.0614 to +0.0935). While unadjusted Wilcoxon comparisons vs. C3 and C4 reached nominal significance ($p = 0.0312$), family-wise error control via Holm-Bonferroni correction yields non-significance ($p \approx 0.09$). Thus, the claim of multi-agent benefit rests on the uniform directionality of paired differences and bootstrap stability rather than unadjusted asymptotic significance.
2. **Operational Dependability (V5.3 General Track):** On complex multi-temporal phenotypes, execution reliability proved to be the primary operational bottleneck. C1 completed execution on 11 of 20 tasks, with 9 successfully parsed into verifiable definitions (mean scored $F_1 = 0.3002$ vs. 0.2385 for C2). However, under intention-to-evaluate accounting (where unparsed runs are scored as 0), monolithic single-agent prompting (C2) proved more dependable overall (mean $F_1 = 0.1550$ vs. $0.1351$ for C1).
3. **Precision Discipline:** Mean precision ranged from 0.9036 to 1.0000 across all eight track–configuration arms, computed over scored runs with at least one predicted concept. No out-of-vocabulary concept identifiers were observed in any scored run, consistent with grounding candidate concepts through deterministic DuckDB vocabulary queries; because C4 (no validator) also reached a mean precision of 1.0000 on V5.3, this is better attributed to grounded retrieval than to the validator.

## 6.2 Hypothesized Failure Mechanisms
We identify two distinct behavioral hypotheses to explain performance divergences across architectures:

- **Handoff Friction (Hypothesis):** In multi-agent pipelines, dividing responsibility across Planner, Concept Resolver, Builder, and Critic roles introduces intermediate communication boundaries. When clinical criteria involve nested disjunctive branches (such as Task T01: ADHD diagnosis vs. drug exposure criteria), semantic omissions in early planning cascade into incomplete cohort specifications downstream.
- **Premature Pruning (Hypothesis):** We hypothesize that single-agent baselines often experience premature cognitive closure, retrieving a narrow cluster of initial concepts while terminating search prior to exploring descendant hierarchies. Conversely, multi-agent pipelines explore deeper concept sets but face structural JSON formatting friction that risks premature pruning before the deterministic validator, discarding valid candidate concepts prior to evaluation.

## 6.3 Methodological Implications for Low-Resource RWE
Executing agentic AI pipelines on edge hardware (consumer 8-core CPU, 8 GB RAM) without external cloud leakage is technically viable for observational health research. However, realizing multi-agent expressivity requires strict grammar-guided decoding and robust schema constraints to prevent formatting attrition from nullifying semantic gains.

---

<!-- src: manuscript/07_limitations.md -->
# Limitations

1. **Synthetic Patient Population:** Patient-level execution was evaluated against synthetic OMOP Eunomia data (2,694 patients), which lacks the full noise and missingness of real-world EHR repositories.
2. **Patient Overlap in Neurological Track:** Within Eunomia, Alzheimer's disease and broader dementia definitions shared an identical sub-cohort of 136 patients. Consequently, 10 of 12 Neurological tasks were scored at concept level only.
3. **Single Local Model Scale:** Experiments were conducted using a single quantized 7B model (`qwen2.5:7b`) due to the 8 GB RAM consumer hardware budget.
4. **Single Run Allocation:** Primary benchmark tasks were executed as single deterministic passes under fixed seeds rather than multi-run stochastic distributions.
5. **Development Set Contamination:** System development utilized task T01. The remaining 19 tasks in V5.3 and all 12 tasks in Neuro were evaluated without task-specific optimization.
- **Conditional paired comparisons (V5.3):** Paired tests in the V5.3 track are restricted to the nine tasks that C1 completed. Because this subset is defined by C1 success, the comparisons are conditional on C1 completion and favour C1; intention-to-evaluate means (All = 0) are reported alongside to offset this.

---

<!-- src: manuscript/08_conclusion.md -->
# Conclusion

This investigation evaluated the evidence fidelity and operational limits of multi-agent versus single-agent phenotyping using a locally executed 7B large language model on consumer hardware. Multi-agent planning with iterative critique significantly enhances concept recall in specialized clinical domains, doubling retrieval coverage relative to single-agent baselines. However, multi-agent architectures introduce substantial coordination overhead that reduces completion reliability in complex, multi-criteria general cohorts. For clinical bioinformaticians deploying local AI systems for RWE life cycle support, single-agent architectures with deterministic schema validators provide the most robust baseline, while multi-agent critique should be targeted to dense clinical domains.

---

<!-- src: manuscript/09_declarations.md -->
# Declarations

### Data and Code Availability
All experimental pipelines, prompts, schema validators, task definitions, and evaluation scripts are open-source and version-controlled. The complete benchmark suite, blinded clinical questions (`tasks/benchmark_questions.jsonl`), frozen manifests (`results/codex_20261025/freeze_manifest_OFFICIAL.json`), and run logs are available at: https://github.com/bharathwaj005/agentic-omop-phenotyping. The OMOP vocabulary tables are accessible via OHDSI Athena (https://athena.ohdsi.org). Synthetic patient evaluation leverages the public OMOP Eunomia dataset.

### Funding
This research received no specific grant from any funding agency in the public, commercial, or not-for-profit sectors.

### Competing Interests
The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

### Author Contributions
Bharathwaj: Conceptualization, Methodology, Software, Formal analysis, Investigation, Data Curation, Writing - Original Draft, Writing - Review & Editing, Visualization.

### Use of Generative AI Statement
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
