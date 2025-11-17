#!/bin/bash
# Helper script to run AIEnergyScore Docker container with proper volume mounts
# Usage: ./run_docker.sh [OPTIONS] [docker run arguments...]
#
# Options:
#   -n, --num-samples NUM    Number of prompts to test (default: 10)
#                           Applies to all backends (pytorch, vllm, optimum)
#   -h, --help              Show this help message
#
# Environment Variables:
#   DOCKER_IMAGE            Docker image name (default: ai_energy_score)
#   RESULTS_DIR             Results directory (default: ./results)
#   HF_HOME                 HuggingFace cache location (default: ~/.cache/huggingface)
#   HF_TOKEN                HuggingFace API token for gated models (optional)
#   BENCHMARK_BACKEND       Backend selection: optimum, pytorch, vllm (default: pytorch)
#
# Authentication for Gated Models:
#   This script automatically detects and mounts your HuggingFace token for
#   accessing gated models. Two methods are supported:
#   1. Token file (automatic): If you've logged in via 'huggingface-cli login',
#      your token at ~/.huggingface/token will be automatically mounted
#   2. Environment variable: Set HF_TOKEN to explicitly pass your token
#
# Examples:
#   ./run_docker.sh --config-name text_generation backend.model=openai/gpt-oss-20b
#   ./run_docker.sh -n 100 --config-name text_generation backend.model=openai/gpt-oss-120b
#   BENCHMARK_BACKEND=pytorch ./run_docker.sh -n 50 --config-name text_generation backend.model=openai/gpt-oss-20b
#   ./run_docker.sh --config-name text_generation backend.model=openai/gpt-oss-20b scenario.num_samples=100
#   HF_TOKEN=hf_xxx ./run_docker.sh --config-name text_generation backend.model=google/gemma-3-1b-pt

set -e

# Default configuration
IMAGE_NAME="${DOCKER_IMAGE:-ai_energy_score}"
RESULTS_DIR="${RESULTS_DIR:-$(pwd)/results}"
HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface}"
HF_TOKEN_FILE="${HOME}/.cache/huggingface/token"
NUM_SAMPLES=10

# Function to show help
show_help() {
    head -n 15 "$0" | grep "^#" | sed 's/^# \?//'
    exit 0
}

# Parse arguments
DOCKER_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            ;;
        -n|--num-samples)
            NUM_SAMPLES="$2"
            shift 2
            ;;
        *)
            DOCKER_ARGS+=("$1")
            shift
            ;;
    esac
done

# Create results directory if it doesn't exist
mkdir -p "${RESULTS_DIR}"

# Verify HF cache directory exists
if [ ! -d "${HF_CACHE}" ]; then
    echo "Warning: HuggingFace cache directory not found at ${HF_CACHE}"
    echo "Models will be downloaded on first run and cached at this location"
    mkdir -p "${HF_CACHE}"
fi

# Check for HuggingFace authentication
HF_AUTH_AVAILABLE=false
if [ -n "${HF_TOKEN}" ]; then
    HF_AUTH_AVAILABLE=true
    echo "Note: Using HF_TOKEN from environment variable for authentication"
elif [ -f "${HF_TOKEN_FILE}" ]; then
    HF_AUTH_AVAILABLE=true
    echo "Note: Found HuggingFace token file at ${HF_TOKEN_FILE}"
fi

if [ "${HF_AUTH_AVAILABLE}" = false ]; then
    echo ""
    echo "Warning: No HuggingFace authentication found"
    echo "If you need to access gated models (e.g., google/gemma-3-1b-pt):"
    echo "  1. Login via: huggingface-cli login"
    echo "  2. Or set HF_TOKEN environment variable"
    echo ""
fi

# Check if running with vLLM backend (doesn't need HF cache mount)
BACKEND="${BENCHMARK_BACKEND:-pytorch}"
VOLUME_MOUNTS="-v ${RESULTS_DIR}:/results"

if [ "$BACKEND" != "vllm" ]; then
    # Mount HF cache for pytorch and optimum backends
    VOLUME_MOUNTS="${VOLUME_MOUNTS} -v ${HF_CACHE}:/home/user/.cache/huggingface"
fi

# Mount HuggingFace token file if it exists (for gated model access)
if [ -f "${HF_TOKEN_FILE}" ]; then
    VOLUME_MOUNTS="${VOLUME_MOUNTS} -v ${HF_TOKEN_FILE}:/home/user/.huggingface/token:ro"
fi

# Get image build date
IMAGE_CREATED=$(docker inspect --format='{{.Created}}' "${IMAGE_NAME}" 2>/dev/null | cut -d'T' -f1 || echo "unknown")

# Display configuration
echo "============================================"
echo "AIEnergyScore Docker Runner"
echo "============================================"
echo "Image:         ${IMAGE_NAME}"
echo "Image Built:   ${IMAGE_CREATED}"
echo "Backend:       ${BACKEND}"
echo "Num Samples:   ${NUM_SAMPLES}"
echo "Results dir:   ${RESULTS_DIR}"
if [ "$BACKEND" != "vllm" ]; then
    echo "HF Cache:      ${HF_CACHE}"
fi
echo "User:          $(id -u):$(id -g)"
echo "============================================"
echo ""

# Build docker run command
ENV_VARS="-e HOME=/home/user -e BENCHMARK_BACKEND=${BACKEND}"
if [ "$BACKEND" = "vllm" ] && [ -n "$VLLM_ENDPOINT" ]; then
    ENV_VARS="$ENV_VARS -e VLLM_ENDPOINT=${VLLM_ENDPOINT}"
fi

# Pass HF_TOKEN if set (for gated model access)
if [ -n "${HF_TOKEN}" ]; then
    ENV_VARS="${ENV_VARS} -e HF_TOKEN=${HF_TOKEN}"
fi

# Build additional arguments
# For all backends, append scenario.num_samples from -n flag (default: 20)
EXTRA_ARGS=()
if [ "$BACKEND" = "pytorch" ] || [ "$BACKEND" = "vllm" ] || [ "$BACKEND" = "optimum" ]; then
    EXTRA_ARGS+=("scenario.num_samples=${NUM_SAMPLES}")
fi

# shellcheck disable=SC2086
exec docker run --gpus all --shm-size 1g \
    --user "$(id -u):$(id -g)" \
    ${VOLUME_MOUNTS} \
    ${ENV_VARS} \
    "${IMAGE_NAME}" \
    "${DOCKER_ARGS[@]}" \
    "${EXTRA_ARGS[@]}"
