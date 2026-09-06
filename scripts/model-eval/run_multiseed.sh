#!/usr/bin/env bash
# Multi-seed evaluation for the three tasks where q8_0 diverged from q4_K_M.
# Runs seeds 1-5 x 1 round each (5 independent samples per model per task).
#
# Usage: bash scripts/model-eval/run_multiseed.sh

set -euo pipefail
cd "$(dirname "$0")"

SEEDS=(1 2 3 4 5)
export EVAL_ROUNDS=1

for seed in "${SEEDS[@]}"; do
    echo "=== seed $seed ==="
    EVAL_SEED="$seed" python3 run.py seed-probe-"$seed"
done

echo ""
echo "=== all seeds done ==="
echo "Analyse with:  python3 analyse_multiseed.py"
