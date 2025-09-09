#!/bin/bash
set -e

RESULTS_DIR="/results"

python /launch_backend.py
# python /check_h100.py
if [[ $? = 0 ]]; then
    mkdir -p "${RESULTS_DIR}"
    # Force Hydra (used by optimum-benchmark) to write outputs into /results
    optimum-benchmark --config-dir /optimum-benchmark/energy_star/ "$@" hydra.run.dir="${RESULTS_DIR}"
    # Post-run summarizer: reads benchmark_report.json and prints/writes GPU_ENERGY_WH
    python /summarize_gpu_wh.py "${RESULTS_DIR}"
fi
