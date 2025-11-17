#!/bin/bash
# Test script for run_docker.sh and run_non_docker.sh argument parsing
#
# Tests:
# - Default NUM_SAMPLES values
# - -n, --num-samples flag parsing
# - --batch flag detection
# - Backend selection
# - Help flag

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to print test results
print_result() {
    local test_name="$1"
    local passed="$2"

    if [ "$passed" = "true" ]; then
        echo -e "${GREEN}✓${NC} $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}✗${NC} $test_name"
        ((TESTS_FAILED++))
    fi
}

# Helper to extract NUM_SAMPLES from script
get_num_samples_from_script() {
    local script="$1"
    grep "^NUM_SAMPLES=" "$script" | head -1 | cut -d'=' -f2
}

echo "=========================================================================="
echo "Shell Script Argument Parsing Tests"
echo "=========================================================================="
echo ""

# Test 1: run_docker.sh default NUM_SAMPLES
echo "Test Suite 1: run_docker.sh defaults"
echo "--------------------------------------------------------------------------"

default_value=$(get_num_samples_from_script "$PROJECT_DIR/run_docker.sh")
if [ "$default_value" = "10" ]; then
    print_result "run_docker.sh default NUM_SAMPLES is 10" "true"
else
    print_result "run_docker.sh default NUM_SAMPLES is 10 (got $default_value)" "false"
fi

# Test 2: run_non_docker.sh default NUM_SAMPLES
default_value=$(get_num_samples_from_script "$PROJECT_DIR/run_non_docker.sh")
if [ "$default_value" = "10" ]; then
    print_result "run_non_docker.sh default NUM_SAMPLES is 10" "true"
else
    print_result "run_non_docker.sh default NUM_SAMPLES is 10 (got $default_value)" "false"
fi

echo ""
echo "Test Suite 2: run_non_docker.sh default values"
echo "--------------------------------------------------------------------------"

# Test 3: Check default BACKEND value in script
if grep -q '^BACKEND="\${BENCHMARK_BACKEND:-pytorch}"' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Default BACKEND is pytorch" "true"
else
    print_result "Default BACKEND is pytorch" "false"
fi

# Test 4: Check default ENDPOINT value in script
if grep -q 'ENDPOINT="\${VLLM_ENDPOINT:-http://localhost:8000/v1}"' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Default ENDPOINT is http://localhost:8000/v1" "true"
else
    print_result "Default ENDPOINT is http://localhost:8000/v1" "false"
fi

# Test 5: Check default BATCH_MODE is false
if grep -q '^BATCH_MODE=false' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Default BATCH_MODE is false" "true"
else
    print_result "Default BATCH_MODE is false" "false"
fi

echo ""
echo "Test Suite 3: run_non_docker.sh argument handling in code"
echo "--------------------------------------------------------------------------"

# Test 6: Script accepts -n flag
if grep -q '\-n|\-\-num-samples|\-\-num-prompts' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script handles -n, --num-samples, --num-prompts flags" "true"
else
    print_result "Script handles -n, --num-samples, --num-prompts flags" "false"
fi

# Test 7: Script accepts --batch flag
if grep -q '\-\-batch' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script handles --batch flag" "true"
else
    print_result "Script handles --batch flag" "false"
fi

# Test 8: Script accepts -b, --backend flag
if grep -q '\-b|\-\-backend' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script handles -b, --backend flag" "true"
else
    print_result "Script handles -b, --backend flag" "false"
fi

# Test 9: Script accepts -e, --endpoint flag
if grep -q '\-e|\-\-endpoint' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script handles -e, --endpoint flag" "true"
else
    print_result "Script handles -e, --endpoint flag" "false"
fi

# Test 10: Script has batch mode branch
if grep -q 'if.*BATCH_MODE.*true' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script has batch mode conditional logic" "true"
else
    print_result "Script has batch mode conditional logic" "false"
fi

# Test 11: Script calls batch_runner.py in batch mode
if grep -q 'batch_runner\.py' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script calls batch_runner.py" "true"
else
    print_result "Script calls batch_runner.py" "false"
fi

# Test 12: Script calls run_ai_energy_benchmark.py in direct mode
if grep -q 'run_ai_energy_benchmark\.py' "$PROJECT_DIR/run_non_docker.sh"; then
    print_result "Script calls run_ai_energy_benchmark.py" "true"
else
    print_result "Script calls run_ai_energy_benchmark.py" "false"
fi

echo ""
echo "Test Suite 4: Help flag behavior"
echo "--------------------------------------------------------------------------"

# Test 13: -h flag shows help (run_docker.sh)
if "$PROJECT_DIR/run_docker.sh" -h 2>&1 | grep -q "Usage:"; then
    print_result "run_docker.sh -h shows help" "true"
else
    print_result "run_docker.sh -h shows help" "false"
fi

# Test 14: --help flag shows help (run_docker.sh)
if "$PROJECT_DIR/run_docker.sh" --help 2>&1 | grep -q "Usage:"; then
    print_result "run_docker.sh --help shows help" "true"
else
    print_result "run_docker.sh --help shows help" "false"
fi

# Test 15: -h flag shows help (run_non_docker.sh)
if "$PROJECT_DIR/run_non_docker.sh" -h 2>&1 | grep -q "Usage:"; then
    print_result "run_non_docker.sh -h shows help" "true"
else
    print_result "run_non_docker.sh -h shows help" "false"
fi

# Test 16: --help flag shows help (run_non_docker.sh)
if "$PROJECT_DIR/run_non_docker.sh" --help 2>&1 | grep -q "Usage:"; then
    print_result "run_non_docker.sh --help shows help" "true"
else
    print_result "run_non_docker.sh --help shows help" "false"
fi

echo ""
echo "=========================================================================="
echo "Test Summary"
echo "=========================================================================="
echo ""
echo "Passed: $TESTS_PASSED"
echo "Failed: $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
