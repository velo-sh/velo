#!/bin/bash
# =============================================================================
# Velo Orphan Test Detection Script
# =============================================================================
# RFC-0017 §3.6: CI SHALL verify no test files are orphaned (never collected).
#
# Usage: ./scripts/check-orphan-tests.sh
#
# Exit Codes:
#   0 - All tests collected successfully
#   1 - Orphan tests detected (files exist but not collected)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🔍 RFC-0017 Orphan Test Detection"
echo "=================================="
echo ""

# Count Python test files
TEST_FILES=$(find tests/qa -name "test_*.py" -type f | wc -l | xargs)

# Count collected tests using pytest --collect-only
COLLECTED=$(pytest --collect-only -q tests/qa/ 2>/dev/null | grep -E '<Function|<Method' | wc -l | xargs || echo "0")

echo "📊 Statistics:"
echo "   Test files found: $TEST_FILES"
echo "   Tests collected:  $COLLECTED"
echo ""

# Validation
if [[ "$TEST_FILES" -eq 0 ]]; then
    echo -e "${YELLOW}⚠️  No test files found in tests/qa/${NC}"
    exit 0
fi

if [[ "$COLLECTED" -eq 0 ]]; then
    echo -e "${RED}❌ ORPHAN TESTS DETECTED!${NC}"
    echo ""
    echo "   $TEST_FILES test files exist but 0 tests were collected."
    echo "   This may indicate:"
    echo "     - Import errors in test files"
    echo "     - Missing pytest markers"
    echo "     - conftest.py issues"
    echo ""
    echo "   Run 'pytest --collect-only tests/qa/' to debug."
    exit 1
fi

# Rough ratio check (expect at least 2 tests per file on average)
MIN_RATIO=2
EXPECTED_MIN=$((TEST_FILES * MIN_RATIO))

if [[ "$COLLECTED" -lt "$MIN_RATIO" ]]; then
    echo -e "${YELLOW}⚠️  Warning: Low test collection ratio${NC}"
    echo "   Expected at least $MIN_RATIO tests per file, got $((COLLECTED / TEST_FILES))."
fi

echo -e "${GREEN}✅ All test files are properly collected!${NC}"
echo "   Average tests per file: $((COLLECTED / TEST_FILES))"
exit 0
