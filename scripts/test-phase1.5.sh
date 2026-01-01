#!/bin/bash
# Phase 1.5 QA Test Script
# Tests all RFC-0001 features

echo "============================================================"
echo "  Phase 1.5 QA Test Suite"
echo "============================================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

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
VELO="./target/release/velo"

# --- Test 1: Unit Tests ---
echo ""
echo "▸ Test 1: Unit Tests (cargo test)"
TEST_OUTPUT=$(cargo test 2>&1)
if echo "$TEST_OUTPUT" | grep -q "28 passed"; then
    pass "28 unit tests pass"
else
    fail "Unit tests failed"
    echo "$TEST_OUTPUT" | tail -5
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

# --- Test 3: Binary Size ---
echo ""
echo "▸ Test 3: Binary Size (< 500KB)"
SIZE=$(ls -l target/release/velo | awk '{print $5}')
SIZE_KB=$((SIZE / 1024))
if [ "$SIZE_KB" -lt 500 ]; then
    pass "Binary size: ${SIZE_KB}KB"
else
    fail "Binary too large: ${SIZE_KB}KB"
fi

# --- Test 4: velo --help ---
echo ""
echo "▸ Test 4: velo --help"
if $VELO --help | grep -q "velo info"; then
    pass "--help shows 'velo info'"
else
    fail "--help missing 'velo info'"
fi

if $VELO --help | grep -q "\-\-profile"; then
    pass "--help shows '--profile'"
else
    fail "--help missing '--profile'"
fi

# --- Test 5: velo info ---
echo ""
echo "▸ Test 5: velo info"
INFO_OUTPUT=$($VELO info 2>&1)

if echo "$INFO_OUTPUT" | grep -q "Hardware"; then
    pass "velo info shows Hardware"
else
    fail "velo info missing Hardware"
fi

if echo "$INFO_OUTPUT" | grep -q "Python Environment"; then
    pass "velo info shows Python Environment"
else
    fail "velo info missing Python Environment"
fi

if echo "$INFO_OUTPUT" | grep -q "Cache Status"; then
    pass "velo info shows Cache Status"
else
    fail "velo info missing Cache Status"
fi

# --- Test 6: velo run --profile ---
echo ""
echo "▸ Test 6: velo run --profile"
PROFILE_OUTPUT=$($VELO run --profile tests/corpus/hello.py 2>&1)

if echo "$PROFILE_OUTPUT" | grep -q "Running with profiling"; then
    pass "--profile runs"
else
    fail "--profile failed to start"
fi

if echo "$PROFILE_OUTPUT" | grep -q "Total execution time"; then
    pass "--profile shows execution time"
else
    fail "--profile missing execution time"
fi

# --- Test 7: velo run (normal) ---
echo ""
echo "▸ Test 7: velo run (normal execution)"
RUN_OUTPUT=$($VELO run tests/corpus/hello.py 2>&1)

if echo "$RUN_OUTPUT" | grep -q "Hello from Velo"; then
    pass "velo run executes script"
else
    fail "velo run failed"
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
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed${NC}"
    exit 1
fi
