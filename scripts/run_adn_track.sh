#!/bin/bash
# Run the Alzheimer's-disease neuroinflammation (ADN) extension track: 12 tasks x 4 configurations.
# Expect several hours on an 8-core CPU laptop (each run is capped at 20 minutes).
# Resume after an interruption with:  bash scripts/run_adn_track.sh --resume
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a && . ./.env && set +a
export PYTHONPATH=.
export JBI_RUN_DEADLINE_S=1200
export JBI_HTTP_TIMEOUT_S=600
OUT="${ADN_OUT:-results/adn_runs/qwen7b_$(date +%Y%m%d)}"
mkdir -p "$(dirname "$OUT")"
echo "[$(date -Is)] ADN track -> $OUT"
python scripts/run_benchmark.py \
  --track adn \
  --questions tasks/adn/ad_neuroinflammation_questions.jsonl \
  --model qwen2.5:7b \
  --out "$OUT" \
  --configs C1,C2,C3,C4 "$@" 2>&1 | tee "$OUT.log"
python scripts/analyze_adn_track.py "$OUT"
