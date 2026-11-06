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
