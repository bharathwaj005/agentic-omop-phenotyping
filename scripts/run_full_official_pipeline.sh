#!/bin/bash
set -euo pipefail
cd /home/bharathwaj/jbi
source .venv/bin/activate
set -a && . ./.env && set +a
export PYTHONPATH=.
export JBI_RUN_DEADLINE_S=1200
export JBI_HTTP_TIMEOUT_S=600

echo "[$(date -Is)] PHASE 1: Launching V5.3 Track (C1, C2, C3, C4 across 20 cohorts)..."
python scripts/run_benchmark.py \
  --track v53 --resume --resume \
  --questions tasks/benchmark_questions.jsonl \
  --model qwen2.5:7b \
  --out results/codex_20261025/runs/official_v53_qwen7b \
  --configs C1,C2,C3,C4 \
  --freeze-manifest results/codex_20261025/freeze_manifest_OFFICIAL.json 2>&1 | tee results/codex_20261025/runs/official_v53_qwen7b.log

echo "[$(date -Is)] PHASE 1 COMPLETE. Generating preliminary V5.3 benchmark status..."
python scripts/benchmark_status.py results/codex_20261025/runs/official_v53_qwen7b || true

echo "[$(date -Is)] PHASE 2: Chaining Neuro Track (C1, C2, C3, C4 across 12 neuro tasks)..."
python scripts/run_benchmark.py \
  --track neuro --resume --resume \
  --questions tasks/neuro_questions.jsonl \
  --model qwen2.5:7b \
  --out results/codex_20261025/runs/official_neuro_qwen7b \
  --configs C1,C2,C3,C4 \
  --freeze-manifest results/codex_20261025/freeze_manifest_OFFICIAL.json 2>&1 | tee results/codex_20261025/runs/official_neuro_qwen7b.log

echo "[$(date -Is)] PHASE 2 COMPLETE. Generating Neuro benchmark status..."
python scripts/benchmark_status.py results/codex_20261025/runs/official_neuro_qwen7b || true
echo "[$(date -Is)] ENTIRE OFFICIAL BENCHMARK PIPELINE EXECUTED SUCCESSFULLY."
