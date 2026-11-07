# Target-trial emulation protocol (draft)

## TNFα inhibitors versus JAK inhibitors in rheumatoid arthritis and incident dementia

**Status:** draft protocol for a follow-on study; not part of the submitted paper.

**Question:** among adults with rheumatoid arthritis who start a targeted therapy, does starting a TNFα inhibitor rather than a JAK inhibitor change the risk of incident dementia (all-cause) and Alzheimer's disease?

Observational studies have reported lower dementia risk with TNFα inhibitors in RA, but the evidence is mixed and prone to confounding by indication. An active-comparator, new-user emulation reduces that bias.

## Protocol components

| Component | Target trial | Emulation in OMOP data |
|---|---|---|
| Eligibility | Adults ≥ 50 years with RA; no prior dementia, MCI, AD or anti-dementia drugs; ≥ 365 days of prior observation; no prior TNFi or JAKi | RA diagnosis cohort; exclusions via OMOP condition/drug history |
| Treatment strategies | (1) initiate a TNFα inhibitor; (2) initiate a JAK inhibitor | OHDSI cohorts **1066** (new users of TNFα inhibitors nested in RA) and **1070** (new users of JAK inhibitors nested in RA) |
| Assignment | Randomised | Propensity-score matching or stratification on a large set of baseline covariates (OHDSI FeatureExtraction default set) |
| Outcomes | Incident dementia; incident AD | OHDSI cohorts **864** (earliest event of dementia), **862** (earliest event of AD, Imfeld), sensitivity with **651** and **100** |
| Follow-up | From initiation until outcome, death, end of data, or 5 years | Time-at-risk starting **365 days after index** (lag for prodromal reverse causation); sensitivity with 0 and 730 days |
| Causal contrast | Intention-to-treat and per-protocol | On-treatment (persistence window 30 days) and ITT time-at-risk |
| Analysis | Hazard ratio | Cox model in OHDSI CohortMethod; empirical calibration with ≥ 50 negative-control outcomes; report minimum detectable relative risk |

## Diagnostics to pass before unblinding

- **Covariate balance:** standardised mean difference < 0.1 after matching.
- **Empirical equipoise:** ≥ 35% of patients with preference scores 0.3–0.7.
- **Calibration:** negative-control estimates centred near HR 1 after calibration.
- **Power:** minimum detectable relative risk reported.

## Role of the agentic pipeline

The pipeline from this repository **drafts** the exposure and outcome cohort definitions. A clinician then reviews them (`docs/review/`) and validates them with PheValuator or CohortDiagnostics before any effect estimate is produced. Only human-validated definitions enter the analysis.

## Data sources to consider

- Institutional OMOP databases (with ethics approval).
- OHDSI network studies.
- Large OMOP research programmes such as All of Us (check eligibility).

Synthetic data (Eunomia) is suitable only for testing the code.
