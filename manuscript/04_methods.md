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
- **Retries:** runs stopped by an infrastructure fault (memory preflight stop) were re-executed once (T05, T11 and T17); all other runs use the first attempt. Remaining infrastructure failures are counted as failures. System logs show the local inference server was terminated by the operating system's out-of-memory killer within five minutes of two of these failed retries (T11 and T17).
- **Paired comparisons:** C1 versus each alternative on tasks scored by both configurations; two-sided Wilcoxon signed-rank tests with zero differences dropped; Holm–Bonferroni adjustment across the three comparisons within each track; percentile bootstrap 95% CIs of the mean paired difference (10,000 resamples of paired differences, seed `20261028`).

## Hardware and Local Inference
Acer One Z14-55N (Intel Core i3-N305, 8 cores / 8 threads, 8 GB DDR5 RAM, CPU only, Linux Mint). Model: quantized `qwen2.5:7b` [13] (Q4_K_M GGUF format via Ollama).
