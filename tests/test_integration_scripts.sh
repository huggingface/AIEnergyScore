#!/bin/bash
# Integration tests for run_docker.sh and run_non_docker.sh
#
# These tests verify end-to-end script behavior without actually
# running benchmarks (which would be too slow for tests).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# Helper to check if virtual environment exists
check_venv() {
    if [ ! -d "$PROJECT_DIR/.venv" ]; then
        echo -e "${YELLOW}⚠ Virtual environment not found. Some tests will be skipped.${NC}"
        return 1
    fi
    return 0
}

echo "=========================================================================="
echo "Integration Tests for Shell Scripts"
echo "=========================================================================="
echo ""

echo "Test Suite 1: Script Existence and Permissions"
echo "--------------------------------------------------------------------------"

# Test 1: run_docker.sh exists
if [ -f "$PROJECT_DIR/run_docker.sh" ]; then
    print_result "run_docker.sh exists" "true"
else
    print_result "run_docker.sh exists" "false"
fi

# Test 2: run_non_docker.sh exists
if [ -f "$PROJECT_DIR/run_non_docker.sh" ]; then
    print_result "run_non_docker.sh exists" "true"
else
    print_result "run_non_docker.sh exists" "false"
fi

# Test 3: run_docker.sh is executable
if [ -x "$PROJECT_DIR/run_docker.sh" ]; then
    print_result "run_docker.sh is executable" "true"
else
    print_result "run_docker.sh is executable" "false"
fi

# Test 4: run_non_docker.sh is executable
if [ -x "$PROJECT_DIR/run_non_docker.sh" ]; then
    print_result "run_non_docker.sh is executable" "true"
else
    print_result "run_non_docker.sh is executable" "false"
fi

echo ""
echo "Test Suite 2: Help Output Validation"
echo "--------------------------------------------------------------------------"

# Test 5: run_docker.sh help mentions default samples
help_output=$("$PROJECT_DIR/run_docker.sh" -h 2>&1)
if echo "$help_output" | grep -q "default: 10"; then
    print_result "run_docker.sh help shows default: 10" "true"
else
    print_result "run_docker.sh help shows default: 10" "false"
fi

# Test 6: run_non_docker.sh help mentions direct mode
help_output=$("$PROJECT_DIR/run_non_docker.sh" -h 2>&1)
if echo "$help_output" | grep -qi "direct mode"; then
    print_result "run_non_docker.sh help mentions Direct Mode" "true"
else
    print_result "run_non_docker.sh help mentions Direct Mode" "false"
fi

# Test 7: run_non_docker.sh help mentions batch mode
if echo "$help_output" | grep -qi "batch mode"; then
    print_result "run_non_docker.sh help mentions Batch Mode" "true"
else
    print_result "run_non_docker.sh help mentions Batch Mode" "false"
fi

# Test 8: run_non_docker.sh help shows -n option
if echo "$help_output" | grep -q "\-n,.*--num-samples"; then
    print_result "run_non_docker.sh help shows -n option" "true"
else
    print_result "run_non_docker.sh help shows -n option" "false"
fi

# Test 9: run_non_docker.sh help shows --batch option
if echo "$help_output" | grep -q "\-\-batch"; then
    print_result "run_non_docker.sh help shows --batch option" "true"
else
    print_result "run_non_docker.sh help shows --batch option" "false"
fi

echo ""
echo "Test Suite 3: Required Files Validation"
echo "--------------------------------------------------------------------------"

# Test 10: batch_runner.py exists
if [ -f "$PROJECT_DIR/batch_runner.py" ]; then
    print_result "batch_runner.py exists" "true"
else
    print_result "batch_runner.py exists" "false"
fi

# Test 11: run_ai_energy_benchmark.py exists
if [ -f "$PROJECT_DIR/run_ai_energy_benchmark.py" ]; then
    print_result "run_ai_energy_benchmark.py exists" "true"
else
    print_result "run_ai_energy_benchmark.py exists" "false"
fi

# Test 12: model_config_parser.py exists
if [ -f "$PROJECT_DIR/model_config_parser.py" ]; then
    print_result "model_config_parser.py exists" "true"
else
    print_result "model_config_parser.py exists" "false"
fi

# Test 13: oct_2025_models.csv exists
if [ -f "$PROJECT_DIR/oct_2025_models.csv" ]; then
    print_result "oct_2025_models.csv exists" "true"
else
    print_result "oct_2025_models.csv exists" "false"
fi

echo ""
echo "Test Suite 4: Python Module Validation (if venv exists)"
echo "--------------------------------------------------------------------------"

if check_venv; then
    # Test 14: Can import model_config_parser
    if "$PROJECT_DIR/.venv/bin/python3" -c "from model_config_parser import ModelConfigParser" 2>/dev/null; then
        print_result "Can import ModelConfigParser" "true"
    else
        print_result "Can import ModelConfigParser" "false"
    fi

    # Test 15: Can import batch_runner
    if "$PROJECT_DIR/.venv/bin/python3" -c "import batch_runner" 2>/dev/null; then
        print_result "Can import batch_runner" "true"
    else
        print_result "Can import batch_runner" "false"
    fi

    # Test 16: Can parse CSV
    cd "$PROJECT_DIR"
    if "$PROJECT_DIR/.venv/bin/python3" -c "from model_config_parser import ModelConfigParser; parser = ModelConfigParser('oct_2025_models.csv'); configs = parser.parse(); assert len(configs) > 0" 2>/dev/null; then
        print_result "Can parse oct_2025_models.csv" "true"
    else
        print_result "Can parse oct_2025_models.csv" "false"
    fi

    # Test 17: Filtering works
    cd "$PROJECT_DIR"
    if "$PROJECT_DIR/.venv/bin/python3" -c "from model_config_parser import ModelConfigParser; parser = ModelConfigParser('oct_2025_models.csv'); configs = parser.parse(); filtered = parser.filter_configs(configs, model_name='gpt-oss'); assert len(filtered) > 0" 2>/dev/null; then
        print_result "Model filtering works correctly" "true"
    else
        print_result "Model filtering works correctly" "false"
    fi
else
    echo -e "${YELLOW}Skipping Python module tests (no venv)${NC}"
fi

echo ""
echo "Test Suite 5: Documentation Consistency"
echo "--------------------------------------------------------------------------"

# Test 18: README mentions both modes
if grep -qi "direct mode" "$PROJECT_DIR/README.md" && grep -qi "batch mode" "$PROJECT_DIR/README.md"; then
    print_result "README.md documents both modes" "true"
else
    print_result "README.md documents both modes" "false"
fi

# Test 19: README mentions default is 10
if grep -q "default.*10" "$PROJECT_DIR/README.md"; then
    print_result "README.md mentions default is 10" "true"
else
    print_result "README.md mentions default is 10" "false"
fi

# Test 20: README explains --model-name for batch mode
if grep -qi "model-name.*batch" "$PROJECT_DIR/README.md"; then
    print_result "README.md explains --model-name for batch mode" "true"
else
    print_result "README.md explains --model-name for batch mode" "false"
fi

# Test 21: README warns about Hydra args in batch mode
if grep -qi "hydra.*batch.*ignore\|batch.*hydra.*ignore" "$PROJECT_DIR/README.md"; then
    print_result "README.md warns about Hydra args in batch mode" "true"
else
    print_result "README.md warns about Hydra args in batch mode" "false"
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
    echo -e "${GREEN}✓ All integration tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some integration tests failed${NC}"
    exit 1
fi
