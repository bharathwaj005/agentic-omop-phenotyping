# Reproducing the study

## 0. Requirements

- Linux or macOS, Python 3.12, ~8 GB RAM, ~15 GB disk for the vocabulary database.
- [Ollama](https://ollama.com) with `qwen2.5:7b` (exact version and model digest: `docs/MODEL_PROVENANCE.json`).
- OMOP standardized vocabularies downloaded from [OHDSI Athena](https://athena.ohdsi.org) (SNOMED, RxNorm, RxNorm Extension, ICD10CM, ICD9CM, LOINC, ATC, CPT4 as licensed).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock          # exact versions used; requirements.txt has ranges
.venv/bin/python -m src.db.load_vocab                # builds data/vocab.duckdb from the Athena CSVs
```

The test suite runs without `.env`: missing settings get safe test defaults (`PROJECT_ROOT` = this folder, storage roots under a git-ignored `.local/` folder, model names as labels for the fake LLM). To re-run models, create `.env` from `.env.example`.

## 1. Regenerate all tables and figures from the frozen runs (no model calls)

```bash
.venv/bin/python scripts/run_tier1_analysis.py
.venv/bin/python scripts/format_tier1_tables.py
.venv/bin/python -m pytest -q tests
```

`git diff results/analysis_tier1_20261028` should show no numeric changes.

## 2. Re-run the models (hours on a CPU laptop)

Create `.env` with `A_BASE_URL=http://127.0.0.1:11434/v1` (local Ollama; no API key needed), then:

```bash
bash scripts/run_neuro_track.sh                      # 12 tasks x 4 configurations
.venv/bin/python scripts/run_benchmark.py --track v53 --questions tasks/benchmark_questions.jsonl \
    --model qwen2.5:7b --out results/rerun_v53 --configs C1,C2,C3,C4
```

Each run is capped at 1,200 s and requires ≥ 3 GiB free memory before model loading (the runner checks this). Model outputs vary across hardware and Ollama versions; expect similar but not byte-identical results.

## 3. Secondary analyses

```bash
.venv/bin/python scripts/hierarchy_aware_metrics.py   # near-match F1 at k = 0, 1, 2 hierarchy levels
.venv/bin/python scripts/make_review_sheet.py         # clinician review sheet (docs/review/)
.venv/bin/python scripts/build_adn_track.py           # Alzheimer's neuroinflammation extension track
bash scripts/run_adn_track.sh                          # run it (hours)
```
