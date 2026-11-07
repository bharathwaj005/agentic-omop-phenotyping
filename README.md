# Agentic OMOP Phenotyping

Code, benchmark tasks, frozen results and manuscript for:

> **How Faithfully Do Agentic AI Systems Generate OMOP Cohort Definitions? A Controlled, Low-Resource Evaluation of Multi-Agent Phenotyping**
> Submitted to the *Journal of Biomedical Informatics*, Special Issue "Agentic AI for Real-World Evidence Life Cycle Support".

The study asks whether a multi-agent LLM pipeline (planner → concept resolver → cohort builder → validator ↔ critic) writes more faithful OMOP cohort definitions than a single agent, when everything runs **locally on a CPU-only laptop** (Intel i3-N305, 8 GB RAM, `qwen2.5:7b` via Ollama, no cloud calls).

## Key results (release `v1.0-jbi-submission`)

32 tasks from the OHDSI Phenotype Library × 4 configurations = **128 runs**. F1 = exact concept-ID agreement with the multi-arm reference (Reference v2).

| Track | Config | Scored | Mean F1 (scored) | Mean F1 (All=0) | Precision |
|---|---|---|---|---|---|
| V5.3 general (20 tasks) | C1 multi-agent | 11/20 | **0.2477** | 0.1362 | 0.9012 |
|  | C2 single agent | 14/20 | 0.2215 | **0.1550** | 0.8390 |
|  | C3 no critic | 15/20 | 0.1998 | 0.1498 | 0.8800 |
|  | C4 no validator | 16/20 | 0.1517 | 0.1213 | 0.9375 |
| Neurological (12 tasks) | C1 multi-agent | 12/12 | **0.6208** | **0.6208** | 0.9295 |
|  | C2 / C3 / C4 | 11–12/12 | 0.32–0.36 | 0.30–0.36 | 0.96–1.00 |

Neurological track, C1 vs each alternative: bootstrap 95% CIs exclude zero for all three comparisons; Wilcoxon p = 0.031–0.039 (Holm-adjusted p = 0.094). Full tables: `results/analysis_tier1_20261028/table_main_results.md` and `paired_tests_formatted.md`.

**Errata:** task T10 was originally scored against the wrong OHDSI cohort (967, 4-point MACE) and has been corrected to cohort 1025 (ADHD) without re-running any model. See [`docs/ERRATA.md`](docs/ERRATA.md).

## Repository layout

| Path | Contents |
|---|---|
| `src/` | Pipeline: agents, DuckDB vocabulary tools, schema, validator, metrics |
| `scripts/run_benchmark.py` | Runs a track (`v53`, `neuro`, `adn`) with all safeguards |
| `scripts/run_tier1_analysis.py`, `scripts/format_tier1_tables.py` | Regenerate every table from the frozen runs |
| `tasks/` | Blinded questions, Reference v1/v2 concept sets, OHDSI cohort definitions |
| `results/codex_20261025/runs/official_*` | Frozen reports, traces and raw model replies for all 128 runs |
| `results/analysis_tier1_20261028/` | Official tables, statistics, figures, T10 re-scoring record |
| `results/benchmark_design/` | Frozen benchmark-design manifests used by the runner's preflight |
| `tests/` | Metric unit tests and release-integrity tests |
| `docs/` | Reproduction guide, errata, ADN extension track, target-trial protocol, review kit |
| `manuscript/` | Manuscript source (Markdown) with checksums |

## Reproduce the tables (minutes, no model calls)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock   # or requirements.txt
# Build the OMOP vocabulary database from an OHDSI Athena download (licence terms apply; not redistributed):
.venv/bin/python -m src.db.load_vocab
.venv/bin/python scripts/run_tier1_analysis.py && .venv/bin/python scripts/format_tier1_tables.py
.venv/bin/python -m pytest -q tests
```

Re-running the models themselves (hours on a CPU laptop) is described in [`docs/REPRODUCE.md`](docs/REPRODUCE.md). Model and environment provenance: [`docs/MODEL_PROVENANCE.json`](docs/MODEL_PROVENANCE.json).

## Extensions (not part of the submitted results)

- **Hierarchy-aware metrics** — `scripts/hierarchy_aware_metrics.py` re-scores runs counting parent/child concepts within k levels as near-matches (`results/analysis_tier1_20261028/hierarchy_aware_metrics.md`).
- **Alzheimer's-disease neuroinflammation track (ADN)** — 12 new tasks built on OHDSI Phenotype Library cohorts (AD, dementia, delirium, RA, IBD, psoriasis, SLE, sepsis, HSV, depression, TNFα/JAK-inhibitor initiation). See [`docs/AD_NEUROINFLAMMATION_TRACK.md`](docs/AD_NEUROINFLAMMATION_TRACK.md).
- **Clinician review kit** — `scripts/make_review_sheet.py` and `scripts/review_agreement.py` (Cohen's kappa).
- **Target-trial emulation protocol** — TNFα inhibitors vs JAK inhibitors in rheumatoid arthritis and incident dementia: [`docs/TTE_PROTOCOL_TNFi_dementia.md`](docs/TTE_PROTOCOL_TNFi_dementia.md).

## Data and licensing

Code: MIT licence (`LICENSE`). OMOP vocabularies come from OHDSI Athena under their own licences and are **not** included. Execution checks use the public synthetic Eunomia dataset. No patient data are included.

## Citation

See [`CITATION.cff`](CITATION.cff) (GitHub shows a "Cite this repository" button).
