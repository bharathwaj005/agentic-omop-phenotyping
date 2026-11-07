# Alzheimer's-disease neuroinflammation (ADN) extension track

**Status:** extension for follow-on research. Not part of the submitted results.

## Why this track

Neuroinflammation research on Alzheimer's disease (AD) that uses routine health records depends on cohort definitions for three kinds of phenotype:
1. **AD and dementia outcomes.**
2. **Exposures that plausibly change the brain's inflammatory state:** systemic autoimmune and inflammatory disease, severe infection, depression, anti-inflammatory treatment.
3. **Acute brain dysfunction:** delirium.

The ADN track tests whether agentic pipelines can draft these definitions faithfully. Every task is anchored on a peer-reviewed (`[P][R]`) or published (`[P]`) OHDSI Phenotype Library cohort. That gives a reference built in exactly the same way as the main benchmark.

## Tasks

| Task | OHDSI cohort | Phenotype | Role in AD-neuroinflammation studies |
|---|---|---|---|
| A01 | 100 | [P][R] Alzheimer's disease | outcome |
| A02 | 651 | [P][R] Dementia | outcome (broader) |
| A03 | 95 | [P] Delirium | acute brain dysfunction / effect modifier |
| A04 | 457 | [P][R] Rheumatoid arthritis | chronic systemic inflammation |
| A05 | 1070 | [P] New users of JAK inhibitors nested in RA | anti-inflammatory treatment (comparator) |
| A06 | 1069 | [P] New users of TNFα inhibitors nested in Crohn's disease | anti-inflammatory treatment |
| A07 | 629 | [P][R] Inflammatory bowel disease | chronic systemic inflammation |
| A08 | 475 | [P][R] Psoriasis | chronic systemic inflammation |
| A09 | 509 | [P][R] Systemic lupus erythematosus | autoimmune exposure |
| A10 | 463 | [P][R] Sepsis | acute systemic inflammation |
| A11 | 615 | [P][R] Herpes simplex | infection (viral hypothesis of AD) |
| A12 | 699 | [P][R] Major depressive disorder | neuropsychiatric comorbidity |

The main benchmark already contains:
- N12: new users of TNFα inhibitors nested in RA (cohort 1066);
- N01 / T08: Alzheimer's disease (Imfeld definition);
- N02: incident cognitive impairment.

## Build, run, analyse

```bash
.venv/bin/python scripts/build_adn_track.py     # builds tasks/adn/ and tasks/reference_adn/ (prints a sanity sample per task)
bash scripts/run_adn_track.sh                    # 48 runs; several hours; resumable with --resume
.venv/bin/python scripts/analyze_adn_track.py results/codex_20261025/runs/adn_qwen7b_<date>
```

## Tasks that need expert-built references

The Phenotype Library has no ready cohort for these phenotypes, so each needs a clinician-built reference and validation before it is added:

- **Herpes zoster infection and zoster vaccination.** Exposure in natural-experiment studies of dementia.
- **New users of anti-amyloid monoclonal antibodies** (lecanemab, donanemab), plus **ARIA proxies**. ARIA (amyloid-related imaging abnormalities) proxies are cerebral oedema or microhaemorrhage after initiation.
- **Measurement-domain phenotypes (LOINC, with value thresholds):**
  - CRP, ESR;
  - CSF Aβ42, p-tau and t-tau;
  - plasma p-tau217;
  - amyloid PET;
  - APOE genotype.
- **MCI → AD conversion** within a defined window.
- **Long-term NSAID users,** with a lag window before outcome.
- **Periodontitis and traumatic brain injury.**

## Cautions

- Routine records rarely capture inflammatory biology directly (cytokines, microglial activation). These phenotypes are **proxies**.
- For exposure–outcome questions, use **lag windows** (exclude exposure in the 1–3 years before AD diagnosis) to reduce reverse causation from prodromal disease.
- Use **active comparators** to limit confounding by indication.

## Results (exploratory; not part of the submitted paper)

Run: qwen2.5:7b (Ollama, local CPU, 8 GB RAM laptop), 12 tasks x 4 configurations, 7 Nov 2026. Freeze manifest: `results/codex_20261025/freeze_manifest_ADN.json`. Outputs: `results/codex_20261025/runs/adn_qwen7b_20261107/` (`adn_stats.md` holds all tables). Scoring, retry and test rules are the same as in the main paper: tests use tasks scored by both configurations (two-sided Wilcoxon, Holm across the three comparisons with C1); All=0 tests are shown as a secondary view.

**Retries.** The runner retries a failed run once when its error matches its pre-specified infrastructure list (connection refused or reset, unreachable host, DNS failure, HTTP 5xx, process killed). A08 C3 failed with "connection refused", was retried, and scored 1.00. A08 C2 failed with "RemoteDisconnected", which is not on the list, so it was not retried, although the system log shows the Ollama server was killed by the out-of-memory killer at 16:10:48, the minute A08 C2 failed. The primary analysis keeps the pre-specified rule. A separate sensitivity re-run of A08 C2 (results/codex_20261025/runs/adn_sensitivity_C2_20261107_1827.log) F1 = 1.00.

### Primary analysis

| Config | Scored | Mean F1 (scored) | Mean F1 (All=0) |
| --- | --- | --- | --- |
| C1 | 12 / 12 | 0.7654 | 0.7654 |
| C2 | 11 / 12 | 0.3518 | 0.3225 |
| C3 | 12 / 12 | 0.3486 | 0.3486 |
| C4 | 12 / 12 | 0.3489 | 0.3489 |

| Comparison | n (both scored) | Mean Δ | p | p (Holm) | p, All=0 (n=12) | p (Holm), All=0 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 vs C2 | 11 | +0.392 | 0.0488 | 0.0938 | 0.0244 | 0.0732 |
| C1 vs C3 | 12 | +0.417 | 0.0312 | 0.0938 | 0.0312 | 0.0732 |
| C1 vs C4 | 12 | +0.416 | 0.0312 | 0.0938 | 0.0312 | 0.0732 |

### Sensitivity analysis (A08 C2 re-run included)

| Config | Scored | Mean F1 (scored) | Mean F1 (All=0) |
| --- | --- | --- | --- |
| C1 | 12 / 12 | 0.7654 | 0.7654 |
| C2 | 12 / 12 | 0.4059 | 0.4059 |
| C3 | 12 / 12 | 0.3486 | 0.3486 |
| C4 | 12 / 12 | 0.3489 | 0.3489 |

| Comparison | n (both scored) | Mean Δ | p | p (Holm) | p, All=0 (n=12) | p (Holm), All=0 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 vs C2 | 12 | +0.359 | 0.0488 | 0.0938 | 0.0488 | 0.0938 |
| C1 vs C3 | 12 | +0.417 | 0.0312 | 0.0938 | 0.0312 | 0.0938 |
| C1 vs C4 | 12 | +0.416 | 0.0312 | 0.0938 | 0.0312 | 0.0938 |

### Per-task F1 (X = failed run)

| Task | C1 | C2 | C3 | C4 |
| --- | --- | --- | --- | --- |
| A01 | 1.00 | 0.06 | 0.06 | 0.06 |
| A02 | 0.28 | 1.00 | 0.28 | 0.28 |
| A03 | 0.96 | 0.96 | 0.03 | 0.03 |
| A04 | 1.00 | 0.01 | 0.01 | 0.01 |
| A05 | 0.70 | 0.69 | 0.70 | 0.70 |
| A06 | 0.00 | 0.16 | 0.00 | 0.01 |
| A07 | 1.00 | 0.93 | 1.00 | 1.00 |
| A08 | 1.00 | X (re-run 1.00) | 1.00 | 1.00 |
| A09 | 1.00 | 0.00 | 0.06 | 0.06 |
| A10 | 1.00 | 0.01 | 1.00 | 1.00 |
| A11 | 0.25 | 0.01 | 0.01 | 0.01 |
| A12 | 1.00 | 0.03 | 0.03 | 0.03 |

### What drives the difference

- **One decision explains most of the gap: including descendants.** In every inspected task, all four configurations chose the correct root concept (Alzheimer's disease, rheumatoid arthritis, sepsis, major depressive disorder). C1 set `include_descendants = true`; C2–C4 usually did not, so they matched only the root concept and scored F1 = 0.01–0.06 against references that contain every subtype. When C3 and C4 included descendants (A08, A10), they also reached F1 = 1.00.
- **Why it matters for Alzheimer's research.** An AD or dementia cohort built without descendants silently drops subtype codes (for example, AD with behavioural or psychotic features). That changes case counts and can bias exposure–outcome estimates. Validators for agentic phenotyping should check the descendant flag on condition concepts explicitly.
- **Hard tasks for every configuration.** Drug-exposure cohorts nested in a disease remained difficult: A06 (TNFα inhibitors in Crohn's disease) scored F1 ≤ 0.16 everywhere, and A05 (JAK inhibitors in RA) about 0.70 in all configurations.

### No reference leakage

Across all runs the agents called only OMOP vocabulary tools (`search_concepts`, `get_concept`, `map_to_standard`, `get_descendants`, `get_ancestors`). None can read Phenotype Library cohort definitions, and no tool output mentioned a cohort definition or the library.

### Caveats

- Twelve tasks, one model, one run per cell. C1's mean advantage is large, but the smallest Holm-adjusted p is 0.094 in the primary analysis and 0.094 with the A08 C2 re-run, so the advantage is **not** confirmed at α = 0.05. Treat it as a hypothesis for a larger study.
- Most ADN phenotypes are single-root "concept plus descendants" definitions, which makes them easier than the NEURO track.
- Which agent step in C1 sets the descendant flag has not yet been determined from the traces.

### Testable follow-up

Add a deterministic post-processing rule ("standard condition concepts include descendants unless explicitly excluded") to C2–C4 and re-run. If most of the gap closes, the benefit of the multi-agent design on this track is mainly this single safeguard.
