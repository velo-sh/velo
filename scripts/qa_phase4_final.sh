#!/bin/bash
# Phase 4.0 Final Verification Script
# Run this BEFORE committing and as CI final gate
#
# Usage: ./scripts/qa_phase4_final.sh

set -e

# Source paths SSOT
source "$(dirname "${BASH_SOURCE[0]}")/lib/paths.sh"

echo "=============================================="
echo "Phase 4.0 Final Verification"
echo "=============================================="

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS="${GREEN}✅ PASS${NC}"
FAIL="${RED}❌ FAIL${NC}"

# Track failures
FAILURES=0

# Step 1: Build
echo ""
echo -e "${YELLOW}[1/6] Building binaries...${NC}"
cargo build --release 2>&1 || { echo -e "$FAIL"; FAILURES=$((FAILURES+1)); }
echo -e "$PASS"

# Step 2: Fix venv permissions (common issue)
echo ""
echo -e "${YELLOW}[2/6] Fixing venv permissions...${NC}"
# Fix all python binaries in .venv
find .venv -name "python*" -type f -exec chmod +x {} \; 2>/dev/null || true
find .venv -name "python*" -type l -exec chmod +x {} \; 2>/dev/null || true
# Fix benchmark venvs
find ../velo-benchmarks -name "python*" -exec chmod +x {} \; 2>/dev/null || true
echo -e "$PASS"

# Helper function to ensure permissions before uv run
fix_perms() {
    chmod +x .venv/bin/python3 2>/dev/null || true
    chmod +x .venv/bin/python 2>/dev/null || true
}

# Step 3: Tier 0 Smoke Tests
echo ""
echo -e "${YELLOW}[3/6] Running Tier 0 (Smoke)...${NC}"
fix_perms
if uv run pytest tests/qa/test_phase4*.py -m tier0 -q; then
    echo -e "$PASS"
else
    echo -e "$FAIL"
    FAILURES=$((FAILURES+1))
fi

# Step 4: All Agent Tests
echo ""
echo -e "${YELLOW}[4/6] Running Agent Tests...${NC}"
fix_perms
if uv run pytest tests/qa/test_phase4_analyze.py tests/qa/test_phase4_agent_*.py -v --tb=short; then
    echo -e "$PASS"
else
    echo -e "$FAIL"
    FAILURES=$((FAILURES+1))
fi

# Step 5: Integration Tests (Real Projects)
echo ""
echo -e "${YELLOW}[5/6] Running Integration Tests (SLOW)...${NC}"
fix_perms
if uv run pytest tests/qa/test_phase4_integration.py -v --tb=short; then
    echo -e "$PASS"
else
    echo -e "$FAIL"
    FAILURES=$((FAILURES+1))
fi

# Step 6: Benchmarks
echo ""
echo -e "${YELLOW}[6/6] Running Benchmarks...${NC}"
fix_perms
# Fix benchmark project venvs specifically
find ../velo-benchmarks -name "python*" -type f -exec chmod +x {} \; 2>/dev/null || true
find ../velo-benchmarks -name "python*" -type l -exec chmod +x {} \; 2>/dev/null || true
if uv run python "$BENCHMARKS_SCRIPTS/benchmark_projects.py" --all; then
    echo -e "$PASS"
else
    echo -e "$FAIL"
    FAILURES=$((FAILURES+1))
fi

# Summary
echo ""
echo "=============================================="
if [ $FAILURES -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL CHECKS PASSED${NC}"
    echo "Ready for merge!"
    exit 0
else
    echo -e "${RED}❌ $FAILURES CHECKS FAILED${NC}"
    echo "Fix issues before merging."
    exit 1
fi
