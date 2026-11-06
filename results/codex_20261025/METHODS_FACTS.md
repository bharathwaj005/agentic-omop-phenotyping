# Methods facts (fact sheet)

## Configurations and budgets

- C1: multi-agent pipeline; critic enabled; validator enabled.
- C2: single-agent pipeline; validator enabled; no critic.
- C3: multi-agent pipeline; validator enabled; critic disabled.
- C4: multi-agent pipeline; critic enabled; validator disabled.
- LLM call cap per run: 30.
- Total token cap per run: 150,000.
- Single-agent vocabulary tool cap: 18 per run.
- Concept-agent vocabulary tool cap: 6 per concept set; aggregate tracker cap: 18.
- Validator repair retries: 3.
- Critic rounds: 2.
- These limits are defined in `src/pipelines/budget.py`; allocation of the token cap among configurations: UNVERIFIED.

## Prompt files and SHA-256

- `src/llm/prompts/single_agent.md`: `5a80507b35df1f4055e02883bbb3401eb5ddfc7eab14e8d3aef86b49b08de44f`.
- `src/llm/prompts/planner.md`: `1782943d30f3dc299ebd0eb787be1a6e58a6c3482036708334912e5cae0deaa8`.
- `src/llm/prompts/concept.md`: `6e8fc8740c1a5ac33a42ad06439cd59abada79f4ecf39ed22ed20aba432cbf3e`.
- `src/llm/prompts/builder.md`: `e0d33e94cd381766c333745c45dc53f82e2eb0d615ba2ec2d6c14b22d94ce17b`.
- `src/llm/prompts/critic.md`: `268b058e898a4fffe5e74982ef07c43ed85ea8340066a0f87ca3d1f3cd7287b7`.
- Hashes verified 2026-10-25 from current prompt bytes; model-specific prompt variants: UNVERIFIED.

## Validator checks

- Structural errors: unsupported domain, empty entry set, concept set containing only exclusions.
- Structural warnings: duplicate concept item, empty non-entry set, unfilled non-entry set.
- Vocabulary errors: concept ID absent, invalid/deprecated, not standard, domain mismatch.
- Resolved-set errors/warnings: empty entry set error; empty non-entry set warning; `very_broad_set` warning above 2,000 resolved concepts.
- Entry-set warning: one resolved concept without descendant expansion raises `entry_single_concept_no_descendants` and instructs the agent to check `get_descendants`.
- Existing narrowness warning: `possibly_too_narrow` for one resolved entry concept, including when descendants were requested.
- Post-execution warning: empty cohort (`empty_cohort`).
- Implementation: `src/tools/validator.py`.

## Duplicate-tool guard and search recovery

- Signature: `(action, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))`.
- First exact duplicate: return the same corrective message, use the prior observation, continue without executing or charging a tool call.
- Second duplicate retry: stop with failure reason `repeated identical vocabulary tool call after 2 corrective retries`.
- Parity regression: single-agent and concept-agent produce the same correction, stop result, reason, and one executed tool call.
- Recovery rules: one clinical idea at a time; concise searches normally 1–3 words; select the appropriate domain; after no match change one query dimension; consider Drug and Procedure domains separately for therapy evidence; search justified medication ingredients individually; stop after two unsuccessful searches for the same idea; do not invent concepts or silently broaden eligibility.
- Prompt hashes: see the five prompt hashes above.

## Deadline

- Environment variable: `JBI_RUN_DEADLINE_S`; unset means no deadline.
- Semantics: a new monotonic-clock deadline starts for every task × configuration run; a timeout does not stop later runs.
- The HTTP client caps request timeout and retry backoff to the remaining current-run time.
- Expiry status is `timeout`; trace/checkpoint state is saved. The benchmark orchestrator checkpoints after each run.
- Deadline value for the benchmark: UNVERIFIED; must be selected from user-run pilot timings.

## Benchmark construction and gates

- Cohort definition source: OHDSI Phenotype Library cohort JSON files; dataset release/version: UNVERIFIED.
- V5.3 core: 20 selected cohort definitions in `results/benchmark_design/V5_3_FREEZE/BENCHMARK_FINAL20_V5_3_FINAL.csv`; complexity distribution: 13 complex, 4 medium, 3 simple; source freeze marks 20/20 Eunomia-evaluable.
- V5.3 redundancy gate: 190 entry-set pairs; threshold 0.90; v1 maximum 0.722222; v2 V5.3-only maximum 0.1385281385 and zero pairs at or above threshold.
- Neuro freeze: 12 cohorts, N01–N12; complexity distribution: 2 complex, 3 medium, 7 simple.
- Neuro candidates screened: 14; exclusions: cohort 33, entry Jaccard 0.9065 vs V5.3 cohort 864; cohort 1080, entry Jaccard 1.0000 vs Neuro cohort 235; threshold 0.90.
- Neuro selected cohorts: 255, 863, 552, 1026, 287, 535, 1079, 544, 235, 550, 229, 1066.
- Neuro `patient_evaluable`: direct entry-concept event coverage in Eunomia; 255 has 136 distinct matching people; 287 has 3; the other 10 have 0. This is not full cohort execution.
- Reference v1: frozen files under `tasks/reference/`; eight V5.3 tasks have multi-codeset entry definitions that are incomplete in the v1 entry field.
- Reference v2: preserves all resolved concept sets (`all_concept_ids` unchanged), reads every primary-criteria entry arm, and unions every arm codeset for entry concepts. The v1 entry set is a subset of v2 for each cohort; single-arm entries are identical.
- V2 reference manifest SHA-256: `4f807ba055ed1a71d5ded423fab5bd27041efdb1cd27ea4f32ccaf6afaf688bb`.
- V5.3 v2 gate pair CSV and Neuro candidate gate summary: `results/codex_20261024/gate_v2_pairs.csv` and `results/codex_20261024/gate_v2_summary.txt`.
- Reason for v2: include all entry arms from each definition while retaining the v1 all-concept sets.
- Complexity assignment methodology and task-selection adjudication protocol: UNVERIFIED.

## Scoring definitions

- Full scope: union of all predicted resolved concept sets vs union of all reference concept IDs.
- Entry scope: union of all predicted entry concept sets/arms vs union of reference entry concept IDs.
- Precision: intersection / predicted set size.
- Recall: intersection / reference set size.
- F1: harmonic mean of precision and recall.
- Jaccard: intersection / union.
- The pilot and analysis reports score both v1 and v2; planned primary reporting uses v2. Primary/secondary scope designation in the study protocol: UNVERIFIED.
- Failed/missing runs remain counted; absent metrics remain missing and are not converted to zero.

## Data sources and versions

- Athena OMOP vocabulary database: 1,738,346 rows in `concept`; read-only count verified 2026-10-25.
- Athena `vocabulary_version` row: `2026-02-01 SNOMED CT International Edition; 2026-03-01 SNOMED CT US Edition; 2026-04-08 SNOMED CT UK Edition`.
- Eunomia source: Synthea synthetic health database; CDM version 5.3.1; vocabulary version `v5.0 18-JAN-19`.
- Eunomia persons: 2,694.
- Eunomia rows: condition_occurrence 65,332; drug_exposure 67,707; procedure_occurrence 37,409; measurement 44,053; observation 1,477; visit_occurrence 1,037; device_exposure 0; death 0.
- Eunomia counts were queried through a read-only DuckDB connection on 2026-10-25.
- Phenotype Library package version: UNVERIFIED.

## Hardware and runtime

- Python: 3.12.3.
- Logical CPU count: 8; architecture: x86_64; physical CPU model: UNVERIFIED.
- Installed RAM: 8,047,120,384 bytes; GPU: UNVERIFIED (GPU inventory utility unavailable).
- Operating-system release and benchmark-time load: UNVERIFIED.
