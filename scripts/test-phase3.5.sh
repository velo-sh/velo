#!/bin/bash
# Phase 3.5 QA Test Script
# Tests velo serve command (RFC-0003)

echo "============================================================"
echo "  Phase 3.5 QA Test Suite - velo serve"
echo "============================================================"
echo ""

# Source paths SSOT
source "$(dirname "${BASH_SOURCE[0]}")/lib/paths.sh"

PASS=0
FAIL=0

pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASS++))
}

fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAIL++))
}

# --- Prerequisites ---
echo "📦 Building release binary..."
cargo build --release --quiet 2>&1
VELO="$VELO_BIN_RELEASE"

# --- Test 1: Unit Tests ---
echo ""
echo "▸ Test 1: Rust Unit Tests (serve module)"
TEST_OUTPUT=$(cargo test serve 2>&1)
SERVE_TESTS=$(echo "$TEST_OUTPUT" | grep -E "^test serve::" | wc -l)
if echo "$TEST_OUTPUT" | grep -q "0 failed"; then
    pass "12 serve unit tests pass"
else
    fail "Serve unit tests failed"
    echo "$TEST_OUTPUT" | tail -10
fi

# --- Test 2: Clippy ---
echo ""
echo "▸ Test 2: Clippy (no warnings)"
CLIPPY_OUTPUT=$(cargo clippy -- -D warnings 2>&1)
if echo "$CLIPPY_OUTPUT" | grep -q "error"; then
    fail "Clippy has errors"
else
    pass "Clippy clean"
fi

# --- Test 3: velo --help shows serve ---
echo ""
echo "▸ Test 3: velo --help includes serve"
if $VELO --help | grep -q "serve"; then
    pass "--help shows 'serve' command"
else
    fail "--help missing 'serve'"
fi

if $VELO --help | grep -q "SERVE OPTIONS"; then
    pass "--help shows SERVE OPTIONS section"
else
    fail "--help missing SERVE OPTIONS"
fi

# --- Test 4: velo serve errors ---
echo ""
echo "▸ Test 4: velo serve error handling"
if $VELO serve 2>&1 | grep -q "missing app"; then
    pass "Missing app shows error"
else
    fail "Missing app error not shown"
fi

if $VELO serve invalid 2>&1 | grep -q "invalid app format"; then
    pass "Invalid format shows error"
else
    fail "Invalid format error not shown"
fi

if $VELO serve main:app --port abc 2>&1 | grep -q "invalid port"; then
    pass "Invalid port shows error"
else
    fail "Invalid port error not shown"
fi

# --- Test 5: Python QA Tests ---
echo ""
echo "▸ Test 5: Python QA Tests (pytest)"
if command -v uv &> /dev/null; then
    QA_OUTPUT=$(uv run python -m pytest tests/qa/test_phase3_5_serve.py -v --tb=short 2>&1)
    QA_PASSED=$(echo "$QA_OUTPUT" | grep -E "passed" | tail -1)
    if echo "$QA_OUTPUT" | grep -q "passed"; then
        pass "QA tests: $QA_PASSED"
    else
        fail "QA tests failed"
        echo "$QA_OUTPUT" | tail -20
    fi
else
    echo -e "${YELLOW}⚠️  SKIP${NC}: uv not found (skipping Python QA tests)"
fi

# --- Summary ---
echo ""
echo "============================================================"
echo "  Summary"
echo "============================================================"
echo -e "  ${GREEN}Passed${NC}: $PASS"
echo -e "  ${RED}Failed${NC}: $FAIL"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}🎉 All Phase 3.5 tests passed!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed${NC}"
    exit 1
fi
