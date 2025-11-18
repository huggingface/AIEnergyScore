#!/bin/bash
# run_non_docker.sh - Non-Docker runner for AIEnergyScore with batch support
#
# Usage:
#   Direct mode: ./run_non_docker.sh [OPTIONS] [benchmark arguments...]
#   Batch mode:  ./run_non_docker.sh --batch [BATCH_OPTIONS]
#
# Direct Mode Options:
#   -n, --num-samples NUM       Number of prompts to test (default: 10)
#      --num-prompts NUM        (alias for --num-samples)
#   -b, --backend BACKEND       Backend type: pytorch, vllm, optimum (default: pytorch)
#   -e, --endpoint URL          vLLM endpoint URL (default: http://localhost:8000/v1)
#   -h, --help                  Show this help message
#
# Batch Mode Options (use with --batch):
#   --csv FILE                  Path to models CSV file (default: oct_2025_models.csv)
#   --output-dir DIR            Output directory for results (default: ./batch_results)
#   --model-name PATTERN        Filter by model name (substring match)
#   --class CLASS               Filter by model class (A, B, or C)
#   --task TASK                 Filter by task type (e.g., text_gen, image_gen)
#   --reasoning-state STATE     Filter by reasoning state (e.g., 'On', 'Off', 'On (High)')
#   --prompts-file FILE         Path to prompts CSV file (optional)
#
# Environment Variables:
#   RESULTS_DIR                 Results directory (default: ./results)
#   HF_HOME                     HuggingFace cache location (default: ~/.cache/huggingface)
#   HF_TOKEN                    HuggingFace API token for gated models (optional)
#   PYTHON_BIN                  Python binary to use (default: auto-detected)
#   VENV_DIR                    Virtual environment directory (default: .venv)
#
# Examples:
#   # Direct execution (default: 10 prompts)
#   ./run_non_docker.sh backend.model=openai/gpt-oss-20b
#
#   # Custom number of prompts
#   ./run_non_docker.sh -n 20 backend.model=openai/gpt-oss-20b
#   ./run_non_docker.sh -n 100 -b vllm -e http://localhost:8021/v1
#
#   # Batch execution
#   ./run_non_docker.sh --batch --model-name llama --reasoning-state "On"
#   ./run_non_docker.sh --batch --csv custom_models.csv --output-dir ./my_results

set -e

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Color output for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
HF_CACHE="${HF_HOME:-${HOME}/.cache/huggingface}"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/.venv}"
NUM_SAMPLES=10
BACKEND="${BENCHMARK_BACKEND:-pytorch}"
ENDPOINT="${VLLM_ENDPOINT:-http://localhost:8000/v1}"
BATCH_MODE=false

# Batch mode defaults
CSV_FILE="oct_2025_models.csv"
OUTPUT_DIR="./batch_results"
MODEL_NAME=""
MODEL_CLASS=""
TASK_TYPE=""
REASONING_STATE=""
PROMPTS_FILE=""

# Function to display help
show_help() {
    grep "^#" "$0" | head -40 | sed 's/^# \?//'
    exit 0
}

# Function to log with color
log() {
    local level=$1
    shift
    case $level in
        INFO)
            echo -e "${GREEN}[INFO]${NC} $*"
            ;;
        WARN)
            echo -e "${YELLOW}[WARN]${NC} $*"
            ;;
        ERROR)
            echo -e "${RED}[ERROR]${NC} $*" >&2
            ;;
        DEBUG)
            echo -e "${BLUE}[DEBUG]${NC} $*"
            ;;
    esac
}

# Function to check dependencies
check_dependencies() {
    log INFO "Checking dependencies..."

    # Check Python
    if [ -n "${PYTHON_BIN}" ]; then
        PYTHON="${PYTHON_BIN}"
    elif [ -f "${VENV_DIR}/bin/python3" ]; then
        PYTHON="${VENV_DIR}/bin/python3"
        log INFO "Using virtual environment Python: ${PYTHON}"
    elif command -v python3 &> /dev/null; then
        PYTHON="python3"
    else
        log ERROR "Python 3 not found. Please install Python 3 or set PYTHON_BIN"
        exit 1
    fi

    # Verify Python version
    PYTHON_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log INFO "Python version: ${PYTHON_VERSION}"

    # Check for virtual environment
    if [ ! -d "${VENV_DIR}" ]; then
        log WARN "Virtual environment not found at ${VENV_DIR}"
        log INFO "Creating virtual environment..."
        python3 -m venv "${VENV_DIR}"
    fi

    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"

    # Check for ai_energy_benchmarks
    if ! $PYTHON -c "import ai_energy_benchmarks" 2>/dev/null; then
        log ERROR "ai_energy_benchmarks not installed"
        log INFO "Please install with: pip install -e /path/to/ai_energy_benchmarks"
        exit 1
    fi

    # Check GPU availability
    if $PYTHON -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
        GPU_COUNT=$($PYTHON -c "import torch; print(torch.cuda.device_count())")
        log INFO "GPUs available: ${GPU_COUNT}"
    else
        log WARN "No CUDA GPUs detected or PyTorch CUDA not available"
    fi
}

# Function to setup HuggingFace authentication
setup_hf_auth() {
    local HF_TOKEN_FILE="${HOME}/.cache/huggingface/token"

    if [ -n "${HF_TOKEN}" ]; then
        log INFO "Using HF_TOKEN from environment variable"
        export HF_TOKEN
    elif [ -f "${HF_TOKEN_FILE}" ]; then
        log INFO "Found HuggingFace token file"
        export HF_TOKEN=$(cat "${HF_TOKEN_FILE}")
    else
        log WARN "No HuggingFace authentication found"
        log WARN "For gated models, either:"
        log WARN "  1. Run: huggingface-cli login"
        log WARN "  2. Set HF_TOKEN environment variable"
    fi
}

# Function to clean up GPU memory
cleanup_gpu() {
    log DEBUG "Cleaning up GPU memory..."
    $PYTHON -c "
import torch
import gc
if torch.cuda.is_available():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print('GPU memory cleaned')
" 2>/dev/null || true
}

# Function to run direct benchmark
run_direct_benchmark() {
    local args=("$@")

    log INFO "============================================"
    log INFO "AIEnergyScore Non-Docker Runner (Direct Mode)"
    log INFO "============================================"
    log INFO "Backend:       ${BACKEND}"
    log INFO "Num Samples:   ${NUM_SAMPLES}"
    log INFO "Results dir:   ${RESULTS_DIR}"
    if [ "${BACKEND}" = "vllm" ]; then
        log INFO "vLLM Endpoint: ${ENDPOINT}"
    fi
    log INFO "============================================"

    # Create results directory
    mkdir -p "${RESULTS_DIR}"

    # Cleanup GPU before starting
    cleanup_gpu

    # Build command based on backend
    if [ "${BACKEND}" = "pytorch" ] || [ "${BACKEND}" = "optimum" ]; then
        # Use run_ai_energy_benchmark.py for local models
        cmd=(
            "${PYTHON}" "${SCRIPT_DIR}/run_ai_energy_benchmark.py"
            "--config-name" "text_generation"
            "--config-path" "${SCRIPT_DIR}"
            "scenario.num_samples=${NUM_SAMPLES}"
            "backend.type=${BACKEND}"
            "${args[@]}"
        )
    else
        # For vLLM backend, use batch_runner directly
        cmd=(
            "${PYTHON}" "${SCRIPT_DIR}/batch_runner.py"
            "--backend" "vllm"
            "--endpoint" "${ENDPOINT}"
            "--num-prompts" "${NUM_SAMPLES}"
            "--output-dir" "${RESULTS_DIR}"
        )

        # Parse model from arguments
        for arg in "${args[@]}"; do
            if [[ $arg == backend.model=* ]]; then
                model="${arg#backend.model=}"
                cmd+=("--model-name" "${model}")
            fi
        done
    fi

    # Set environment variables
    export BENCHMARK_BACKEND="${BACKEND}"
    export HF_HOME="${HF_CACHE}"
    export RESULTS_DIR="${RESULTS_DIR}"

    # Execute benchmark
    log INFO "Running benchmark..."
    log DEBUG "Command: ${cmd[*]}"

    if "${cmd[@]}"; then
        log INFO "Benchmark completed successfully"

        # Display results summary if available
        if [ -d "${RESULTS_DIR}" ]; then
            latest_result=$(find "${RESULTS_DIR}" -name "*.csv" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
            if [ -n "${latest_result}" ]; then
                log INFO "Latest result: ${latest_result}"
            fi
        fi
    else
        log ERROR "Benchmark failed"
        exit 1
    fi
}

# Function to run batch benchmarks
run_batch_benchmarks() {
    log INFO "============================================"
    log INFO "AIEnergyScore Non-Docker Runner (Batch Mode)"
    log INFO "============================================"
    log INFO "CSV File:      ${CSV_FILE}"
    log INFO "Output dir:    ${OUTPUT_DIR}"
    log INFO "Backend:       ${BACKEND}"

    [ -n "${MODEL_NAME}" ] && log INFO "Model filter:  ${MODEL_NAME}"
    [ -n "${MODEL_CLASS}" ] && log INFO "Class filter:  ${MODEL_CLASS}"
    [ -n "${TASK_TYPE}" ] && log INFO "Task filter:   ${TASK_TYPE}"
    [ -n "${REASONING_STATE}" ] && log INFO "Reasoning:     ${REASONING_STATE}"

    log INFO "============================================"

    # Build batch runner command
    cmd=(
        "${PYTHON}" "${SCRIPT_DIR}/batch_runner.py"
        "--csv" "${CSV_FILE}"
        "--output-dir" "${OUTPUT_DIR}"
        "--backend" "${BACKEND}"
    )

    # Add optional parameters
    [ -n "${MODEL_NAME}" ] && cmd+=("--model-name" "${MODEL_NAME}")
    [ -n "${MODEL_CLASS}" ] && cmd+=("--class" "${MODEL_CLASS}")
    [ -n "${TASK_TYPE}" ] && cmd+=("--task" "${TASK_TYPE}")
    [ -n "${REASONING_STATE}" ] && cmd+=("--reasoning-state" "${REASONING_STATE}")
    [ -n "${PROMPTS_FILE}" ] && cmd+=("--prompts-file" "${PROMPTS_FILE}")
    # Always pass num-prompts if specified (batch_runner has its own default)
    [ -n "${NUM_SAMPLES}" ] && cmd+=("--num-prompts" "${NUM_SAMPLES}")

    if [ "${BACKEND}" = "vllm" ]; then
        cmd+=("--endpoint" "${ENDPOINT}")
    fi

    # Set environment for non-docker execution
    export USE_DOCKER=false
    export BENCHMARK_BACKEND="${BACKEND}"
    export HF_HOME="${HF_CACHE}"

    # Execute batch runner
    log INFO "Starting batch execution..."
    log DEBUG "Command: ${cmd[*]}"

    if "${cmd[@]}"; then
        log INFO "Batch execution completed successfully"

        # Display summary
        if [ -f "${OUTPUT_DIR}/aggregated_results.csv" ]; then
            log INFO "Results saved to: ${OUTPUT_DIR}/aggregated_results.csv"

            # Count successful/failed runs
            if [ -f "${OUTPUT_DIR}/aggregated_results.csv" ]; then
                success_count=$(grep -c ",success," "${OUTPUT_DIR}/aggregated_results.csv" 2>/dev/null || echo "0")
                fail_count=$(grep -c ",failed," "${OUTPUT_DIR}/aggregated_results.csv" 2>/dev/null || echo "0")
                log INFO "Summary: ${success_count} successful, ${fail_count} failed"
            fi
        fi
    else
        log ERROR "Batch execution failed"
        exit 1
    fi
}

# Parse arguments
DIRECT_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            ;;
        --batch)
            BATCH_MODE=true
            shift
            ;;
        -n|--num-samples|--num-prompts)
            NUM_SAMPLES="$2"
            shift 2
            ;;
        -b|--backend)
            BACKEND="$2"
            shift 2
            ;;
        -e|--endpoint)
            ENDPOINT="$2"
            shift 2
            ;;
        --csv)
            CSV_FILE="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --model-name)
            MODEL_NAME="$2"
            shift 2
            ;;
        --class)
            MODEL_CLASS="$2"
            shift 2
            ;;
        --task)
            TASK_TYPE="$2"
            shift 2
            ;;
        --reasoning-state)
            REASONING_STATE="$2"
            shift 2
            ;;
        --prompts-file)
            PROMPTS_FILE="$2"
            shift 2
            ;;
        *)
            DIRECT_ARGS+=("$1")
            shift
            ;;
    esac
done

# Cleanup handler
cleanup() {
    log INFO "Cleaning up..."
    cleanup_gpu
    deactivate 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Main execution
check_dependencies
setup_hf_auth

if [ "${BATCH_MODE}" = true ]; then
    run_batch_benchmarks
else
    run_direct_benchmark "${DIRECT_ARGS[@]}"
fi

log INFO "Done!"
