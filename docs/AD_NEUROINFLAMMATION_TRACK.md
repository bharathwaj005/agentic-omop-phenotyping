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
.venv/bin/python scripts/analyze_adn_track.py results/adn_runs/<run_dir>
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
