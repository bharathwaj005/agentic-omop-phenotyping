# User Retry Plan for Infrastructure & Missing Runs

```bash
cd /home/bharathwaj/jbi && source .venv/bin/activate
mkdir -p results/official_infra_retries_20261028/
export JBI_RUN_DEADLINE_S=1200
./.venv/bin/python scripts/run_benchmark.py \
  --track v53 \
  --questions tasks/benchmark_questions.jsonl \
  --model qwen2.5:7b \
  --out results/official_infra_retries_20261028 \
  --configs C1,C2,C3,C4 \
  --freeze-manifest results/codex_20261025/freeze_manifest_OFFICIAL.json
```
