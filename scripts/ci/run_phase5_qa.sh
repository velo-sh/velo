#!/bin/bash
# Phase 5.0 Fast Loader: CI Test Runner
# 
# Usage:
#   ./scripts/ci/run_phase5_qa.sh           # Run all tests
#   ./scripts/ci/run_phase5_qa.sh --smoke   # Run only L0 smoke tests
#   ./scripts/ci/run_phase5_qa.sh --fast    # Skip slow tests
#
# Exit codes:
#   0: All tests passed
#   1: Tests failed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚀 Phase 5.0 Fast Loader QA Suite"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Parse arguments
RUN_MODE="full"
PYTEST_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --smoke)
            RUN_MODE="smoke"
            PYTEST_ARGS="-m smoke"
            shift
            ;;
        --fast)
            RUN_MODE="fast"
            PYTEST_ARGS="--ignore=tests/qa/phase5/test_l5_chaos.py"
            shift
            ;;
        --security)
            RUN_MODE="security"
            PYTEST_ARGS="-m security"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo ""
echo "Mode: ${RUN_MODE}"
echo "Working Directory: ${PROJECT_ROOT}"
echo ""

# Step 1: Check Python environment
echo "📦 Checking Python environment..."
if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv not found. Please install uv.${NC}"
    exit 1
fi

# Step 2: Check Rust build (optional)
if [ -f "target/release/velo" ]; then
    echo -e "${GREEN}✓ Velo binary found (release)${NC}"
elif [ -f "target/debug/velo" ]; then
    echo -e "${YELLOW}⚠ Using debug build${NC}"
else
    echo -e "${YELLOW}⚠ Velo binary not found - some tests may be skipped${NC}"
fi

# Step 3: Run tests
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📋 Running Tests"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test directories
TEST_DIRS=(
    "tests/qa/test_phase5_loader.py"
    "tests/qa/phase5/"
)

# Run pytest
uv run pytest ${TEST_DIRS[@]} \
    --tb=short \
    -v \
    --junitxml=test-results/phase5-qa.xml \
    ${PYTEST_ARGS} \
    "$@"

TEST_EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "  ${GREEN}✅ All tests passed${NC}"
else
    echo -e "  ${RED}❌ Tests failed${NC}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit $TEST_EXIT_CODE
