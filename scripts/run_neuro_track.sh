#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a && . ./.env && set +a
export PYTHONPATH=.
export JBI_RUN_DEADLINE_S=1200
export JBI_HTTP_TIMEOUT_S=600

echo "[$(date -Is)] Starting Neuro Track Benchmark..."
python scripts/run_benchmark.py \
  --track neuro \
  --questions tasks/neuro_questions.jsonl \
  --model qwen2.5:7b \
  --out results/codex_20261025/runs/official_neuro_qwen7b \
  --configs C1,C2,C3,C4 \
  --freeze-manifest results/codex_20261025/freeze_manifest_OFFICIAL.json 2>&1 | tee results/codex_20261025/runs/official_neuro_qwen7b.log

echo "[$(date -Is)] Neuro Track Finished. Generating benchmark status..."
python scripts/benchmark_status.py results/codex_20261025/runs/official_neuro_qwen7b || true
