#!/bin/bash
# CI-ready QA test runner
# Usage: ./scripts/ci-qa.sh

set -e

echo "============================================================"
echo "  Velo QA Adversarial Test Suite"
echo "============================================================"
echo ""

# Colors (only if terminal supports)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    GREEN=''
    RED=''
    NC=''
fi

# Check prerequisites
if [ ! -f "target/release/velo" ]; then
    echo "Building release binary..."
    cargo build --release --quiet
fi

# Check uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Ensure pytest is installed
if ! uv run python -c "import pytest" 2>/dev/null; then
    echo "Installing pytest..."
    uv pip install pytest
fi

# Run QA tests
echo "Running QA adversarial tests..."
echo ""

if uv run python -m pytest tests/qa/ -v --tb=short; then
    echo ""
    echo -e "${GREEN}✅ All QA tests passed!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}❌ Some QA tests failed${NC}"
    exit 1
fi
